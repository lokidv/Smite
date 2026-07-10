#!/usr/bin/env bash
# =============================================================================
# ovpn-manager.sh — OpenVPN management layer (JSON subcommands)
# -----------------------------------------------------------------------------
# This is the OpenVPN equivalent of the WireGuard extended installer used by the
# wvpn panel.  It wraps angristan/openvpn-install.sh for PKI operations and owns
# per-client state: traffic accounting (حجم), expiry (تاریخ انقضا), reversible
# enable/disable, and quota/expiry enforcement.
#
# It is invoked by the Node panel (lib/ovpn-service.js) and always answers with
# a single JSON object on stdout.  Human logs from the base installer are never
# printed to stdout (they are captured) so the JSON stays clean.
#
#   add <name> [--explicit-limit] [--limit-gb N] [--days N] [--ip IP]
#   update <name> [--add-gb N] [--extend-days N] [--set-limit-gb N]
#                  [--set-expires-at TS] [--clear-expires]
#   info <name>
#   disable <name> [reason]
#   enable <name>
#   remove <name>
#   list
#   enforce
#   refresh-conf <name>
#   refresh-all-confs
#   apply-settings            # rebuild client template + ovpns + server DNS + restart
#   get-settings              # dump params as JSON (used by panel fallback)
# =============================================================================
set -uo pipefail

# ── paths ────────────────────────────────────────────────────────────────────
MGR_DIR="${OVPN_MGR_DIR:-/etc/openvpn/ovpn-manager}"
STATE="${MGR_DIR}/state.json"
PARAMS="${MGR_DIR}/params"
EVENTS="${MGR_DIR}/usage-events.log"
DENIED_LOG="${MGR_DIR}/denied.log"
CLIENTS_DIR="${MGR_DIR}/clients"
LOCK="${MGR_DIR}/.lock"
CCD_DIR="/etc/openvpn/server/ccd"
SERVER_CONF="/etc/openvpn/server/server.conf"
STATUS_LOG="/var/log/openvpn/status.log"
MGMT_SOCK="${OVPN_MGMT_SOCK:-/var/run/openvpn-server/server.sock}"
EASYRSA_DIR="/etc/openvpn/server/easy-rsa"
BASE_SCRIPT="${OVPN_BASE_SCRIPT:-/home/ovpn/openvpn-install.sh}"
TEMPLATE="/etc/openvpn/server/client-template.txt"
IPP_TXT="/etc/openvpn/server/ipp.txt"

GB=$((1073741824))
NOW="$(date +%s)"

# ── tiny helpers ─────────────────────────────────────────────────────────────
respond() { printf '%s\n' "$1"; }
ok()      { respond "$1"; }
fail()    { respond "{\"success\":false,\"error\":\"$(jq -rn --arg e "$1" '$e')\"}"; }

ensure_dirs() {
    mkdir -p "$MGR_DIR" "$CLIENTS_DIR" "$CCD_DIR" 2>/dev/null || true
    [ -f "$STATE" ] || printf '{"clients":{}}' >"$STATE"
    [ -f "$PARAMS" ] || : >"$PARAMS"
    [ -f "$EVENTS" ] || : >"$EVENTS"
}

# read a single KEY=VALUE from $PARAMS
param_get() { # <key>
    local k="$1"
    [ -f "$PARAMS" ] || return 0
    awk -F= -v k="$k" '$1==k{sub(/^[^=]*=/,""); print; found=1} END{}' "$PARAMS" | tail -n1
}

# set/replace a KEY=VALUE in $PARAMS
param_set() { # <key> <value>
    local k="$1" v="$2"
    ensure_dirs
    if grep -q "^${k}=" "$PARAMS" 2>/dev/null; then
        # portable in-place replace (no sed -i flags needed)
        local tmp; tmp="$(mktemp)"
        awk -F= -v k="$k" -v v="$v" '
            $1==k {print k"="v; next}
            {print}
        ' "$PARAMS" >"$tmp" && cat "$tmp" >"$PARAMS" && rm -f "$tmp"
    else
        printf '%s=%s\n' "$k" "$v" >>"$PARAMS"
    fi
}

# read state.json (raw), guaranteeing a clients object — never returns empty
state_raw() {
    local data
    data="$(cat "$STATE" 2>/dev/null || true)"
    if [ -z "$data" ]; then printf '{"clients":{}}'; return; fi
    if printf '%s' "$data" | jq -e . >/dev/null 2>&1; then
        printf '%s' "$data" | jq -c '{clients:(.clients // {})}'
    else
        printf '{"clients":{}}'
    fi
}

# atomic write of state under a lock (single writer = root via Node); refuses
# to write empty/invalid JSON so a failed jq can never corrupt state.json.
state_write() { # <json>
    local payload="$1" tmp
    [ -n "$payload" ] || return 0
    printf '%s' "$payload" | jq -e . >/dev/null 2>&1 || return 0
    tmp="${STATE}.tmp.$$"
    # state.json must stay world-readable: the client-connect hook runs as the
    # unprivileged openvpn user and reads it to deny disabled/expired/over-quota
    # clients at connect time. A restrictive root umask on the tmp file would
    # otherwise make that hook fail-open.
    printf '%s' "$payload" >"$tmp" && { chmod 644 "$tmp" 2>/dev/null || true; mv -f "$tmp" "$STATE"; }
}

# client exists in PKI (valid cert) ?
client_in_pki() { # <name>
    local n="$1"
    [ -f "${EASYRSA_DIR}/pki/index.txt" ] || return 1
    tail -n +2 "${EASYRSA_DIR}/pki/index.txt" | grep -E '^V' | grep -q "/CN=${n}\$"
}

cert_fingerprint() { # <name>
    local c="${EASYRSA_DIR}/pki/issued/$1.crt"
    [ -f "$c" ] && openssl x509 -in "$c" -fingerprint -sha256 -noout 2>/dev/null | cut -d= -f2 || true
}

cert_expiry_epoch() { # <name>
    local c="${EASYRSA_DIR}/pki/issued/$1.crt"
    [ -f "$c" ] || { echo "null"; return; }
    local d; d="$(openssl x509 -in "$c" -enddate -noout 2>/dev/null | cut -d= -f2)"
    [ -n "$d" ] && date -d "$d" +%s 2>/dev/null || echo "null"
}

ipv4_for() { # <name>  (virtual address from ipp.txt or status)
    local n="$1"
    if [ -f "$IPP_TXT" ]; then
        local ip; ip="$(awk -F, -v n="$n" '$1==n{print $2; found=1}' "$IPP_TXT" | tail -n1)"
        [ -n "$ip" ] && { echo "$ip"; return; }
    fi
    echo ""
}

# all valid client names from PKI index.txt (excludes server_*)
pki_client_names() {
    [ -f "${EASYRSA_DIR}/pki/index.txt" ] || return 0
    tail -n +2 "${EASYRSA_DIR}/pki/index.txt" \
        | grep -E '^V' | grep -v '/CN=server_' \
        | sed 's#.*/CN=##' | sort -u
}

# =============================================================================
#  Live traffic snapshot from the OpenVPN status log
# =============================================================================
# Emits a JSON object:  { "<name>": {"recv":N,"sent":N,"vpn":"...","since":N}, ... }
# Field indices are documented at the jq below (verified against the live
# status.log v1 header: ...,Virtual IPv6 Address,Bytes Received,Bytes Sent,...).
live_snapshot() {
    [ -f "$STATUS_LOG" ] || { echo '{}'; return; }
    # NOTE: grep returns 1 on no-match; combined with `set -o pipefail` that would
    # also trigger a trailing `|| echo`, so collect the lines explicitly first.
    local lines
    lines="$(grep '^CLIENT_LIST' "$STATUS_LOG" 2>/dev/null || true)"
    [ -n "$lines" ] || { echo '{}'; return; }
    # status.log v1 CLIENT_LIST fields (0-based):
    #   0 CLIENT_LIST, 1 CN, 2 RealAddr, 3 VirtualIPv4, 4 VirtualIPv6,
    #   5 BytesReceived, 6 BytesSent, 7 ConnectedSince(text), 8 ConnectedSince(t)
    printf '%s\n' "$lines" | jq -R -s '
            split("\n")
            | map(select(length>0))
            | map(split(","))
            | map(select(.[0]=="CLIENT_LIST" and length>=8))
            | reduce .[] as $r ({};
                .[($r[1]|tostring)] = {
                    recv: (($r[5]|tonumber? // 0)),
                    sent: (($r[6]|tonumber? // 0)),
                    vpn:  ($r[3]|tostring),
                    real: ($r[2]|tostring),
                    since:(($r[8]|tonumber? // 0))
                })
          ' 2>/dev/null || echo '{}'
}

# committed usedBytes from state + current in-flight session (recv+sent)
# Produces the "public" client object used by list/info.
build_client_obj() { # <name> <stateClientJson> <liveJson>
    local name="$1"
    jq -c --arg name "$name" --argjson live "$3" '
        . as $c |
        ($live[$name]) as $l |
        ((($c.usedBytes // 0)|tonumber) +
         (if $l then (($l.recv // 0)+($l.sent // 0)) else 0 end)) as $effUsed |
        {
            name: $name,
            ipv4: (if $l then $l.vpn else ($c.ipv4 // "") end),
            publicKey: ($c.fingerprint // ""),
            status: ($c.status // "active"),
            disabledReason: ($c.disabledReason // null),
            usedBytes: $effUsed,
            committedBytes: (($c.usedBytes // 0)|tonumber),
            liveBytes: (if $l then (($l.recv // 0)+($l.sent // 0)) else 0 end),
            dataLimitBytes: (if ($c.dataLimitBytes == null) then null else (($c.dataLimitBytes // 0)|tonumber) end),
            expiresAt: (if ($c.expiresAt == null) then null else (($c.expiresAt // 0)|tonumber) end),
            createdAt: (($c.createdAt // 0)|tonumber),
            connected: (if $l then true else false end),
            lastSeen: (($c.lastSeen // 0)|tonumber),
            certExpiry: ($c.certExpiry // null)
        }
    ' <<<"$2"
}

# =============================================================================
#  Accounting consolidation: fold usage-events.log into state.usedBytes
# =============================================================================
consolidate_events() {
    # reads EVENTS, adds recv+sent per client to state.usedBytes, truncates EVENTS
    [ -f "$EVENTS" ] || return 0
    [ -s "$EVENTS" ] || return 0
    local tmp; tmp="$(mktemp)"
    cp "$EVENTS" "$tmp"
    : >"$EVENTS"     # truncate (best-effort; disconnect hook may append concurrently)
    local sums
    sums="$(awk '
        NF>=4 { name=$2; g=$3+$4; tot[name]+=g }
        END { for (n in tot) printf "%s\t%s\n", n, tot[n] }
    ' "$tmp")"
    rm -f "$tmp"
    [ -n "$sums" ] || return 0
    exec 9>"$LOCK"; flock 9
    local cur; cur="$(state_raw)"
    local new
    new="$(jq --argjson sums "$(printf '%s\n' "$sums" | jq -R -s 'split("\n")|map(select(length>0))|map(split("\t"))|reduce .[] as $r ({}; .[$r[0]] = ($r[1]|tonumber))') " '
        . as $s |
        ($sums|to_entries) as $add |
        reduce $add[] as $a ($s;
            .clients[$a.key].usedBytes = ((.clients[$a.key].usedBytes // 0) + $a.value)
        )
    ' <<<"$cur" 2>/dev/null)"
    [ -n "$new" ] && state_write "$new"
    exec 9>&-
}

# =============================================================================
#  COMMAND: list
# =============================================================================
cmd_list() {
    ensure_dirs
    consolidate_events
    local live; live="$(live_snapshot)"
    local out
    out="$(state_raw | jq -c --argjson live "$live" '
        (.clients // {}) as $clients |
        $live as $live |
        ($clients | to_entries | map(
            (.key) as $name | .value as $c |
            ($live[$name]) as $l |
            ((($c.usedBytes // 0)|tonumber) +
              (if $l then (($l.recv // 0)+($l.sent // 0)) else 0 end)) as $effUsed |
            {
                key: $name,
                value: {
                    name: $name,
                    ipv4: (if $l then $l.vpn else ($c.ipv4 // "") end),
                    publicKey: ($c.fingerprint // ""),
                    status: ($c.status // "active"),
                    disabledReason: ($c.disabledReason // null),
                    usedBytes: $effUsed,
                    dataLimitBytes: (if ($c.dataLimitBytes == null) then null else (($c.dataLimitBytes // 0)|tonumber) end),
                    expiresAt: (if ($c.expiresAt == null) then null else (($c.expiresAt // 0)|tonumber) end),
                    createdAt: (($c.createdAt // 0)|tonumber),
                    connected: (if $l then true else false end),
                    lastSeen: (($c.lastSeen // 0)|tonumber),
                    certExpiry: ($c.certExpiry // null)
                }
            }
        )) | from_entries
    ')"
    ok "{\"success\":true,\"clients\":${out}}"
}

# =============================================================================
#  COMMAND: info <name>
# =============================================================================
cmd_info() {
    local name="$1"
    ensure_dirs
    consolidate_events
    local live; live="$(live_snapshot)"
    local c; c="$(state_raw | jq -c --arg n "$name" '.clients[$n] // empty')"
    if [ -z "$c" ]; then
        # exists in PKI but not tracked yet? adopt it.
        if client_in_pki "$name"; then
            adopt_client "$name" >/dev/null
            c="$(state_raw | jq -c --arg n "$name" '.clients[$n]')"
        else
            fail "Client not found"
            return
        fi
    fi
    local obj; obj="$(build_client_obj "$name" "$c" "$live")"
    ok "$(printf '%s' "$obj" | jq -c '{success:true} + .')"
}

# =============================================================================
#  COMMAND: add <name> [--explicit-limit] [--limit-gb N] [--days N] [--ip IP]
# =============================================================================
cmd_add() {
    local name="" explicit=0 limit_gb="" days="" ip=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --explicit-limit) explicit=1 ;;
            --limit-gb) limit_gb="$2"; shift ;;
            --days) days="$2"; shift ;;
            --ip) ip="$2"; shift ;;
            -*) ;;
            *) [ -z "$name" ] && name="$1" ;;
        esac
        shift
    done
    [ -n "$name" ] || { fail "name is required"; return; }

    ensure_dirs

    # already tracked?
    if [ -n "$(state_raw | jq -r --arg n "$name" '.clients[$n].createdAt // empty')" ]; then
        fail "Client already exists"
        return
    fi

    local conf="${CLIENTS_DIR}/${name}.ovpn"

    # Generate cert + .ovpn via the angristan base installer (captured, not echoed)
    local base_out base_rc
    base_out="$("$BASE_SCRIPT" client add "$name" --output "$conf" --cert-days 3650 2>&1)" || base_rc=$?
    base_rc=${base_rc:-0}
    if [ "$base_rc" -ne 0 ] || [ ! -s "$conf" ]; then
        fail "openvpn-install.sh failed to create client: $(printf '%s' "$base_out" | tail -n3 | tr '\n' ' ')"
        return
    fi

    # resolve volume
    local limit_bytes="null"
    if [ "$explicit" -eq 1 ]; then
        # Float-safe positivity test: printf '%.0f' rounds, so a sub-1GB limit
        # (e.g. 0.5GB == 500MB plan) would round to 0 and be mistaken for
        # "explicit unlimited". Compare as a float instead.
        if [ -n "$limit_gb" ] && [ "$(awk -v g="$limit_gb" 'BEGIN{print (g>0)?1:0}' 2>/dev/null)" = "1" ]; then
            limit_bytes="$(awk -v g="$limit_gb" 'BEGIN{printf "%d", g*1073741824}')"
        else
            limit_bytes="0"   # explicit unlimited
        fi
    else
        local def; def="$(param_get DEFAULT_DATA_LIMIT_GB)"
        if [ -n "$def" ] && [ "$(awk -v d="$def" 'BEGIN{print (d>0)?1:0}')" = "1" ]; then
            limit_bytes="$(awk -v g="$def" 'BEGIN{printf "%d", g*1073741824}')"
        fi
    fi

    # resolve expiry
    local expires="null"
    if [ -n "$days" ]; then
        expires="$(awk -v d="$days" -v now="$NOW" 'BEGIN{printf "%d", now + d*86400}')"
    fi

    local fp; fp="$(cert_fingerprint "$name")"
    local cexp; cexp="$(cert_expiry_epoch "$name")"

    exec 9>"$LOCK"; flock 9
    local cur; cur="$(state_raw)"
    local new
    new="$(jq -c --arg n "$name" --argjson lb "$limit_bytes" --argjson exp "$expires" \
              --arg fp "$fp" --argjson cexp "$cexp" --argjson now "$NOW" --arg ip "${ip:-}" '
        .clients[$n] = {
            createdAt: $now,
            dataLimitBytes: (if $lb == 0 then null else $lb end),
            expiresAt: $exp,
            usedBytes: 0,
            status: "active",
            disabledReason: null,
            lastSeen: 0,
            connected: false,
            ipv4: $ip,
            fingerprint: $fp,
            certExpiry: $cexp
        }
    ' <<<"$cur")"
    state_write "$new"
    exec 9>&-

    ok "{\"success\":true,\"name\":\"$(jq -rn --arg n "$name" '$n')\",\"confPath\":\"${conf}\"}"
}

# adopt an existing PKI client that isn't tracked yet
adopt_client() { # <name>
    local name="$1" fp cexp
    [ -n "$(state_raw | jq -r --arg n "$name" '.clients[$n].createdAt // empty')" ] && return 0
    fp="$(cert_fingerprint "$name")"; cexp="$(cert_expiry_epoch "$name")"
    exec 9>"$LOCK"; flock 9
    local cur; cur="$(state_raw)"
    local new
    new="$(jq -c --arg n "$name" --arg fp "$fp" --argjson cexp "$cexp" --argjson now "$NOW" '
        .clients[$n] = ((.clients[$n]) // {}) + {
            createdAt: ((.clients[$n].createdAt) // $now),
            dataLimitBytes: ((.clients[$n].dataLimitBytes) // null),
            expiresAt: ((.clients[$n].expiresAt) // null),
            usedBytes: ((.clients[$n].usedBytes) // 0),
            status: ((.clients[$n].status) // "active"),
            disabledReason: ((.clients[$n].disabledReason) // null),
            lastSeen: ((.clients[$n].lastSeen) // 0),
            connected: false,
            fingerprint: $fp,
            certExpiry: $cexp
        }
    ' <<<"$cur")"
    state_write "$new"
    exec 9>&-
}

# =============================================================================
#  COMMAND: update <name> [--add-gb] [--extend-days] [--set-limit-gb]
#                       [--set-expires-at] [--clear-expires]
# =============================================================================
cmd_update() {
    local name="" add_gb="" extend_days="" set_limit_gb="" set_expires="" clear_exp=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --add-gb) add_gb="$2"; shift ;;
            --extend-days) extend_days="$2"; shift ;;
            --set-limit-gb) set_limit_gb="$2"; shift ;;
            --set-expires-at) set_expires="$2"; shift ;;
            --clear-expires) clear_exp=1 ;;
            -*) ;;
            *) [ -z "$name" ] && name="$1" ;;
        esac
        shift
    done
    [ -n "$name" ] || { fail "name is required"; return; }
    ensure_dirs
    consolidate_events
    local c; c="$(state_raw | jq -r --arg n "$name" '.clients[$n].createdAt // empty')"
    [ -n "$c" ] || { fail "Client not found"; return; }

    exec 9>"$LOCK"; flock 9
    local cur; cur="$(state_raw)"
    local new
    new="$(jq -c --arg n "$name" \
              --argjson addGb "${add_gb:-null}" \
              --argjson setLimitGb "${set_limit_gb:-null}" \
              --argjson extendDays "${extend_days:-null}" \
              --argjson setExpires "${set_expires:-null}" \
              --argjson clearExp "$clear_exp" \
              --argjson now "$NOW" '
        .clients[$n] as $c |
        ($c.dataLimitBytes // null) as $limit |
        (if ($setLimitGb|type)=="number" then ($setLimitGb*1073741824|floor)
         elif ($addGb|type)=="number" then ((($limit // 0) + $addGb*1073741824)|floor)
         else $limit end) as $newLimit |
        ($c.expiresAt // null) as $exp |
        (if ($clearExp==1) then null
         elif ($setExpires|type)=="number" then $setExpires
         elif ($extendDays|type)=="number" then
           ((if ($exp != null and ($exp|tonumber) > 0 and ($exp|tonumber) > $now)
             then ($exp|tonumber) else $now end) + $extendDays*86400 | floor)
         else $exp end) as $newExp |
        .clients[$n].dataLimitBytes = (if $newLimit == 0 then null else $newLimit end) |
        .clients[$n].expiresAt = $newExp
        | .
    ' <<<"$cur")"
    state_write "$new"
    exec 9>&-

    # if quota was increased/cleared or expiry extended, lift a quota/expired block
    auto_reenable "$name" >/dev/null
    ok "{\"success\":true}"
}

# Effective usage + limit/expiry check (mirrors wginstaller withinLimits).
within_limits() { # <name> <stateJson> <liveJson>
    jq -e --arg n "$1" --argjson live "$3" --argjson now "$NOW" '
        .clients[$n] as $c |
        (($c.usedBytes // 0) +
         (if $live[$n] then (($live[$n].recv // 0)+($live[$n].sent // 0)) else 0 end)) as $used |
        (($c.dataLimitBytes // null)|if . == null then null else (.|tonumber) end) as $limit |
        (($c.expiresAt // null)|if . == null then null else (.|tonumber) end) as $exp |
        if ($limit != null and $limit > 0 and $used >= $limit) then false
        elif ($exp != null and $exp > 0 and $now >= $exp) then false
        else true end
    ' <<<"$2" >/dev/null 2>&1
}

# Lift expired/quota blocks only when limits are actually fixed (not manual).
auto_reenable() { # <name>
    local name="$1"
    local live; live="$(live_snapshot)"
    exec 9>"$LOCK"; flock 9
    local cur; cur="$(state_raw)"
    local st; st="$(printf '%s' "$cur" | jq -r --arg n "$name" '.clients[$n].status // "active"')"
    local reason; reason="$(printf '%s' "$cur" | jq -r --arg n "$name" '.clients[$n].disabledReason // ""')"
    if [ "$st" = "disabled" ] && within_limits "$name" "$cur" "$live"; then
        case "$reason" in
            expired|quota_exceeded)
                local new
                new="$(jq -c --arg n "$name" '.clients[$n].status="active" | .clients[$n].disabledReason=null' <<<"$cur")"
                state_write "$new"
                rm -f "${CCD_DIR}/${name}" 2>/dev/null || true
                ;;
        esac
    fi
    exec 9>&-
}

# =============================================================================
#  enable / disable (reversible via OpenVPN ccd "disable")
# =============================================================================
cmd_disable() {
    local name="$1"; local reason="${2:-manual}"
    [ -n "$name" ] || { fail "name is required"; return; }
    ensure_dirs
    set_client_disabled "$name" "$reason"
    write_ccd_disable "$name"
    kill_live "$name" >/dev/null
    ok "{\"success\":true,\"name\":\"$(jq -rn --arg n "$name" '$n')\",\"status\":\"disabled\"}"
}

cmd_enable() {
    local name="$1"
    [ -n "$name" ] || { fail "name is required"; return; }
    ensure_dirs
    consolidate_events
    local live; live="$(live_snapshot)"
    exec 9>"$LOCK"; flock 9
    local cur; cur="$(state_raw)"
    local st; st="$(printf '%s' "$cur" | jq -r --arg n "$name" '.clients[$n].status // empty')"
    if [ -z "$st" ]; then
        exec 9>&-
        fail "Client not found"
        return
    fi
    if [ "$st" = "active" ]; then
        exec 9>&-
        ok "{\"success\":true,\"name\":\"$(jq -rn --arg n "$name" '$n')\",\"status\":\"active\",\"message\":\"already active\"}"
        return
    fi
    if ! within_limits "$name" "$cur" "$live"; then
        exec 9>&-
        fail "Client is still over quota or expired"
        return
    fi
    local new; new="$(jq -c --arg n "$name" '.clients[$n].status="active" | .clients[$n].disabledReason=null' <<<"$cur")"
    state_write "$new"
    exec 9>&-
    rm -f "${CCD_DIR}/${name}" 2>/dev/null || true
    ok "{\"success\":true,\"name\":\"$(jq -rn --arg n "$name" '$n')\",\"status\":\"active\"}"
}

set_client_disabled() { # <name> <reason>
    exec 9>"$LOCK"; flock 9
    local cur; cur="$(state_raw)"
    local new; new="$(jq -c --arg n "$1" --arg r "$2" '.clients[$n].status="disabled" | .clients[$n].disabledReason=$r' <<<"$cur")"
    state_write "$new"
    exec 9>&-
}

write_ccd_disable() { # <name>
    mkdir -p "$CCD_DIR" 2>/dev/null || true
    printf 'disable\n' >"${CCD_DIR}/$1"
}

# kill a live session via the OpenVPN management socket
kill_live() { # <name>
    [ -S "$MGMT_SOCK" ] || return 0
    command -v socat >/dev/null 2>&1 || return 0
    printf 'kill %s\n' "$1" | socat - UNIX-CONNECT:"$MGMT_SOCK" >/dev/null 2>&1 || true
}

# =============================================================================
#  COMMAND: remove <name>
# =============================================================================
cmd_remove() {
    local name="$1"
    [ -n "$name" ] || { fail "name is required"; return; }
    ensure_dirs
    if client_in_pki "$name"; then
        local out rc
        out="$("$BASE_SCRIPT" client revoke "$name" -f 2>&1)" || rc=$?
        rc=${rc:-0}
        if [ "$rc" -ne 0 ]; then
            fail "revoke failed: $(printf '%s' "$out" | tail -n2 | tr '\n' ' ')"
            return
        fi
    fi
    rm -f "${CLIENTS_DIR}/${name}.ovpn" "${CCD_DIR}/${name}" 2>/dev/null || true
    exec 9>"$LOCK"; flock 9
    local cur; cur="$(state_raw)"
    local new; new="$(jq -c --arg n "$name" 'del(.clients[$n])' <<<"$cur")"
    state_write "$new"
    exec 9>&-
    ok "{\"success\":true,\"name\":\"$(jq -rn --arg n "$name" '$n')\"}"
}

# =============================================================================
#  COMMAND: enforce  (called periodically by the Node scheduler)
# =============================================================================
cmd_enforce() {
    ensure_dirs
    exec 9>"$LOCK"
    if ! flock -n 9; then
        exec 9>&-
        ok '{"success":true,"skipped":true,"disabled":[]}'
        return
    fi
    flock -u 9
    exec 9>&-

    consolidate_events

    local live; live="$(live_snapshot)"

    # make sure every PKI client is tracked
    local n
    for n in $(pki_client_names); do
        adopt_client "$n" >/dev/null
    done

    exec 9>"$LOCK"; flock 9
    local cur; cur="$(state_raw)"

    # update live/connected/lastSeen + ccd for every tracked client, and disable violators
    local new disabled_names
    new="$(jq -c --argjson live "$live" --argjson now "$NOW" '
        def effUsed($n):
            (.clients[$n].usedBytes // 0) as $u |
            (if ($live[$n]) then (($live[$n].recv // 0)+($live[$n].sent // 0)) else 0 end) as $l |
            ($u + $l);
        (.clients // {}) as $clients |
        reduce ($clients|keys[]) as $n (.;
            ($live[$n]) as $l |
            (.clients[$n].dataLimitBytes // null) as $limit |
            (.clients[$n].expiresAt // null) as $exp |
            (.clients[$n].status // "active") as $st |
            (.clients[$n].disabledReason // null) as $reason |
            (effUsed($n)) as $effUsed |
            # Disable expired / over-quota active clients. The third branch
            # self-heals a transient false-disable: when a client disconnects
            # right at the quota boundary, the disconnect event plus a stale
            # status.log can double-count a session bytes total for a single
            # cycle, pushing effUsed past the limit. Once the disconnect bytes
            # are folded in (and the stale live snapshot clears) the disabled
            # client effUsed drops back below the limit, so we lift the block.
            # A client truly over quota has committed bytes >= limit (its
            # session bytes were committed via the disconnect hook on kill),
            # so it stays disabled.
            (if ($exp != null and $exp > 0 and $now > $exp and $st == "active")
                then {status:"disabled", reason:"expired"}
             elif ($limit != null and $effUsed >= $limit and $st == "active")
                then {status:"disabled", reason:"quota_exceeded"}
             elif ($st == "disabled" and $reason == "quota_exceeded"
                    and ($limit == null or $effUsed < $limit))
                then {status:"active", reason:null}
             else null end) as $action |
            .clients[$n].connected = (if $l then true else false end) |
            .clients[$n].lastSeen = (if $l then $now else (.clients[$n].lastSeen // 0) end) |
            .clients[$n].ipv4 = (if $l then $l.vpn else (.clients[$n].ipv4 // "") end) |
            (if $action then .clients[$n].status = $action.status | .clients[$n].disabledReason = $action.reason else . end)
        )
    ' <<<"$cur")"
    state_write "$new"
    exec 9>&-

    # discover disabled clients (this round + previously) and apply ccd/kill
    disabled_names="$(printf '%s' "$new" | jq -r '.clients | to_entries[] | select(.value.status=="disabled") | .key')"
    local disabled_json
    disabled_json="$(printf '%s\n' "$disabled_names" | jq -R -s 'split("\n")|map(select(length>0))')"

    local d
    for d in $disabled_names; do
        write_ccd_disable "$d"
        kill_live "$d" >/dev/null
    done

    # active clients must not carry a ccd disable file
    local active_names
    active_names="$(printf '%s' "$new" | jq -r '.clients | to_entries[] | select(.value.status=="active") | .key')"
    for d in $active_names; do
        [ -f "${CCD_DIR}/${d}" ] && rm -f "${CCD_DIR}/${d}" 2>/dev/null || true
    done

    ok "{\"success\":true,\"disabled\":${disabled_json}}"
}

# =============================================================================
#  Client template + .ovpn regeneration
# =============================================================================
# Rebuild /etc/openvpn/server/client-template.txt from current params.
rebuild_template() {
    local ip port proto mtu dns1 dns2 cipher hmac
    ip="$(param_get SERVER_PUB_IP)"
    port="$(param_get SERVER_PORT)"; port="${port:-1194}"
    proto="$(param_get SERVER_PROTOCOL)"; proto="${proto:-udp}"
    mtu="$(param_get CLIENT_MTU)"
    cipher="$(param_get CLIENT_CIPHER)"; cipher="${cipher:-AES-128-GCM}"
    hmac="$(param_get CLIENT_HMAC)"; hmac="${hmac:-SHA256}"
    local srv; srv="$(param_get SERVER_NAME)"; srv="${srv:-server}"
    local endpoint; endpoint="$(param_get CLIENT_ENDPOINT)"
    [ -n "$endpoint" ] && ip="$endpoint"
    [ -z "$ip" ] && ip="YOUR_SERVER_IP"

    {
        echo "client"
        case "$proto" in
            udp)  echo "proto udp"; echo "explicit-exit-notify" ;;
            udp6) echo "proto udp6"; echo "explicit-exit-notify" ;;
            tcp)  echo "proto tcp-client" ;;
            tcp6) echo "proto tcp6-client" ;;
            *)    echo "proto udp"; echo "explicit-exit-notify" ;;
        esac
        echo "remote ${ip} ${port}"
        echo "dev tun"
        echo "resolv-retry infinite"
        echo "nobind"
        echo "persist-key"
        echo "persist-tun"
        echo "remote-cert-tls server"
        echo "verify-x509-name ${srv} name"
        echo "auth ${hmac}"
        echo "auth-nocache"
        echo "cipher ${cipher}"
        echo "ignore-unknown-option data-ciphers"
        echo "data-ciphers ${cipher}"
        echo "ncp-ciphers ${cipher}"
        echo "tls-client"
        echo "tls-version-min 1.2"
        echo "ignore-unknown-option block-outside-dns"
        echo "setenv opt block-outside-dns"
        echo "verb 3"
        [ -n "$mtu" ] && echo "tun-mtu ${mtu}"
    } >"$TEMPLATE"
}

# Assemble a single client .ovpn from template + PKI material (mirrors angristan
# generateClientConfig, but uses our managed template).
regenerate_ovpn() { # <name>
    local name="$1" out="${CLIENTS_DIR}/${name}.ovpn"
    local auth="pki"
    [ -f "${EASYRSA_DIR}/AUTH_MODE_GENERATED" ] && auth="$(cat "${EASYRSA_DIR}/AUTH_MODE_GENERATED")"
    cp "$TEMPLATE" "$out" 2>/dev/null || return 1
    {
        if [ "$auth" = "fingerprint" ]; then
            local fp; fp="$(cat /etc/openvpn/server/server-fingerprint 2>/dev/null)"
            echo "peer-fingerprint ${fp}"
        else
            echo "<ca>"; cat "${EASYRSA_DIR}/pki/ca.crt"; echo "</ca>"
        fi
        echo "<cert>"; awk '/BEGIN/,/END CERTIFICATE/' "${EASYRSA_DIR}/pki/issued/${name}.crt" 2>/dev/null; echo "</cert>"
        echo "<key>"; cat "${EASYRSA_DIR}/pki/private/${name}.key" 2>/dev/null; echo "</key>"
        if grep -qs '^tls-crypt-v2' "$SERVER_CONF"; then
            local tk; tk="$(mktemp /etc/openvpn/server/tls-crypt-v2-client.XXXXXX)"
            if openvpn --tls-crypt-v2 /etc/openvpn/server/tls-crypt-v2.key --genkey tls-crypt-v2-client "$tk" 2>/dev/null; then
                echo "<tls-crypt-v2>"; cat "$tk"; echo "</tls-crypt-v2>"
            fi
            rm -f "$tk"
        elif grep -qs '^tls-crypt' "$SERVER_CONF"; then
            echo "<tls-crypt>"; cat /etc/openvpn/server/tls-crypt.key; echo "</tls-crypt>"
        elif grep -qs '^tls-auth' "$SERVER_CONF"; then
            echo "key-direction 1"; echo "<tls-auth>"; cat /etc/openvpn/server/tls-auth.key; echo "</tls-auth>"
        fi
    } >>"$out"
    chmod 600 "$out"
}

cmd_refresh_conf() {
    local name="$1"
    [ -n "$name" ] || { fail "name is required"; return; }
    ensure_dirs
    client_in_pki "$name" || { fail "Client cert not found"; return; }
    rebuild_template
    regenerate_ovpn "$name" || { fail "Failed to regenerate $name"; return; }
    ok "{\"success\":true,\"name\":\"$(jq -rn --arg n "$name" '$n')\"}"
}

cmd_refresh_all() {
    ensure_dirs
    rebuild_template
    local count=0 n
    for n in $(pki_client_names); do
        if regenerate_ovpn "$n"; then count=$((count+1)); fi
    done
    ok "{\"success\":true,\"count\":${count}}"
}

# =============================================================================
#  COMMAND: apply-settings  (called after the panel edits DNS/endpoint/mtu/limit)
# =============================================================================
cmd_apply_settings() {
    ensure_dirs
    rebuild_template

    # regenerate all client .ovpn
    local count=0 n
    for n in $(pki_client_names); do
        if regenerate_ovpn "$n"; then count=$((count+1)); fi
    done

    # update pushed DNS in server.conf from params — only rewrite + restart when
    # the pushed DNS actually changed. MTU / endpoint edits are purely client-side
    # (baked into the .ovpn above), so they must NOT bounce the server and kick
    # every connected user.
    local dns1 dns2 restarted=0
    dns1="$(param_get CLIENT_DNS_1)"
    dns2="$(param_get CLIENT_DNS_2)"
    if [ -n "$dns1" ] && [ -f "$SERVER_CONF" ]; then
        local desired current
        desired="$( { [ -n "$dns1" ] && printf 'push "dhcp-option DNS %s"\n' "$dns1"
                      [ -n "$dns2" ] && printf 'push "dhcp-option DNS %s"\n' "$dns2"; } )"
        current="$(grep '^push "dhcp-option DNS' "$SERVER_CONF" 2>/dev/null || true)"
        if [ "$desired" != "$current" ]; then
            local tmp; tmp="$(mktemp)"
            grep -v '^push "dhcp-option DNS' "$SERVER_CONF" >"$tmp"
            {
                cat "$tmp"
                printf '%s\n' "$desired"
            } >"$SERVER_CONF"
            rm -f "$tmp"
            systemctl restart openvpn-server@server 2>/dev/null || true
            restarted=1
        fi
    fi
    ok "{\"success\":true,\"count\":${count},\"restarted\":${restarted}}"
}

# =============================================================================
#  COMMAND: get-settings
# =============================================================================
cmd_get_settings() {
    ensure_dirs
    local ip port proto dns1 dns2 ep mtu def
    ip="$(param_get SERVER_PUB_IP)"; port="$(param_get SERVER_PORT)"
    proto="$(param_get SERVER_PROTOCOL)"; dns1="$(param_get CLIENT_DNS_1)"
    dns2="$(param_get CLIENT_DNS_2)"; ep="$(param_get CLIENT_ENDPOINT)"
    mtu="$(param_get CLIENT_MTU)"; def="$(param_get DEFAULT_DATA_LIMIT_GB)"
    local server_ep=""
    [ -n "$ip" ] && [ -n "$port" ] && server_ep="${ip}:${port}"
    jq -cn \
        --arg def "${def}" --arg d1 "${dns1:-1.1.1.1}" --arg d2 "${dns2:-1.0.0.1}" \
        --arg ep "${ep}" --arg mtu "${mtu}" --arg sep "${server_ep}" --arg proto "${proto}" \
        '{success:true, defaultDataLimitGB:$def, clientDns1:$d1, clientDns2:$d2,
          clientEndpoint:$ep, serverEndpoint:$sep, effectiveEndpoint:(if $ep != "" then $ep else $sep end),
          clientMtu:$mtu, protocol:$proto}'
}

# =============================================================================
#  dispatch
# =============================================================================
ensure_dirs
sub="${1:-}"; shift || true
case "$sub" in
    add)             cmd_add "$@" ;;
    update)          cmd_update "$@" ;;
    info)            cmd_info "$@" ;;
    disable)         cmd_disable "$@" ;;
    enable)          cmd_enable "$@" ;;
    remove)          cmd_remove "$@" ;;
    list)            cmd_list "$@" ;;
    enforce)         cmd_enforce "$@" ;;
    refresh-conf)    cmd_refresh_conf "$@" ;;
    refresh-all-confs) cmd_refresh_all "$@" ;;
    apply-settings)  cmd_apply_settings "$@" ;;
    get-settings)    cmd_get_settings "$@" ;;
    "")              fail "no subcommand" ;;
    *)               fail "unknown subcommand: $sub" ;;
esac
