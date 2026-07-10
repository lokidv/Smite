#!/usr/bin/env bash
# OpenVPN client-connect hook.
# Real-time denial: blocks disabled / expired / over-quota clients at connect
# time (before a tunnel is established). Read-only on state.json. Always exits 0
# to allow unless an explicit deny rule matches (exit 1 => OpenVPN refuses).
set -uo pipefail
STATE="/etc/openvpn/ovpn-manager/state.json"
DENIED="/etc/openvpn/ovpn-manager/denied.log"
NAME="${common_name:-}"
[ -n "$NAME" ] || exit 0
[ -r "$STATE" ] || exit 0
command -v jq >/dev/null 2>&1 || exit 0

decision="$(jq -r --arg n "$NAME" '
    def num(x): (x | tonumber? // 0);
    (.clients[$n]) as $c |
    if ($c == null) then "allow"
    elif ($c.status == "disabled") then "deny"
    elif (($c.expiresAt // 0) > 0) and (now > ($c.expiresAt|num)) then "deny"
    elif (($c.dataLimitBytes // 0) > 0) and (($c.usedBytes|num) >= ($c.dataLimitBytes|num)) then "deny"
    else "allow" end
' "$STATE" 2>/dev/null || echo "allow")"

case "$decision" in
    deny)
        printf '%s %s denied\n' "$(date +%s)" "$NAME" >>"$DENIED" 2>/dev/null || true
        # A non-zero exit tells OpenVPN to refuse this client.
        exit 1
        ;;
esac
exit 0
