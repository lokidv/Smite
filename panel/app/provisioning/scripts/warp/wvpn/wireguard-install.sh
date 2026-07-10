#!/bin/bash

# Secure WireGuard server installer (IPv4-only) with data quota support
# Based on https://github.com/angristan/wireguard-install

RED='\033[0;31m'
ORANGE='\033[0;33m'
GREEN='\033[0;32m'
NC='\033[0m'

CLIENTS_JSON="/etc/wireguard/clients.json"
LOCK_FILE="/var/lock/wireguard-clients.lock"
IP_FORWARD_CONF="/etc/sysctl.d/99-wvpn-ipforward.conf"

function enableIpForwardPersistent() {
	mkdir -p /etc/sysctl.d
	cat >"${IP_FORWARD_CONF}" <<'EOF'
# WVPN / WireGuard – IPv4 forwarding (persistent across reboots)
net.ipv4.ip_forward=1
EOF
	chmod 644 "${IP_FORWARD_CONF}"
	sysctl -w net.ipv4.ip_forward=1 2>/dev/null || true
	sysctl --system 2>/dev/null || true
}

function ensureWgPostUpIpForward() {
	local conf="/etc/wireguard/${SERVER_WG_NIC}.conf"
	[[ -f "${conf}" ]] || return 0
	if grep -q 'sysctl.*net\.ipv4\.ip_forward' "${conf}" 2>/dev/null; then
		return 0
	fi
	sed -i '/^PrivateKey = /a PostUp   = sysctl -w net.ipv4.ip_forward=1' "${conf}"
}

function isRoot() {
	if [ "${EUID}" -ne 0 ]; then
		echo "You need to run this script as root"
		exit 1
	fi
}

function checkVirt() {
	if [ "$(systemd-detect-virt)" == "openvz" ]; then
		echo "OpenVZ is not supported"
		exit 1
	fi
	if [ "$(systemd-detect-virt)" == "lxc" ]; then
		echo "LXC is not supported (yet)."
		exit 1
	fi
}

function checkOS() {
	source /etc/os-release
	OS="${ID}"
	if [[ ${OS} == "debian" || ${OS} == "raspbian" ]]; then
		if [[ ${VERSION_ID} -lt 10 ]]; then
			echo "Your version of Debian (${VERSION_ID}) is not supported. Please use Debian 10 Buster or later"
			exit 1
		fi
		OS=debian
	elif [[ ${OS} == "ubuntu" ]]; then
		RELEASE_YEAR=$(echo "${VERSION_ID}" | cut -d'.' -f1)
		if [[ ${RELEASE_YEAR} -lt 18 ]]; then
			echo "Your version of Ubuntu (${VERSION_ID}) is not supported. Please use Ubuntu 18.04 or later"
			exit 1
		fi
	elif [[ ${OS} == "fedora" ]]; then
		if [[ ${VERSION_ID} -lt 32 ]]; then
			echo "Your version of Fedora (${VERSION_ID}) is not supported. Please use Fedora 32 or later"
			exit 1
		fi
	elif [[ ${OS} == 'centos' ]] || [[ ${OS} == 'almalinux' ]] || [[ ${OS} == 'rocky' ]]; then
		if [[ ${VERSION_ID} == 7* ]]; then
			echo "Your version of CentOS (${VERSION_ID}) is not supported. Please use CentOS 8 or later"
			exit 1
		fi
	elif [[ -e /etc/oracle-release ]]; then
		source /etc/os-release
		OS=oracle
	elif [[ -e /etc/arch-release ]]; then
		OS=arch
	else
		echo "Unsupported distribution"
		exit 1
	fi
}

function requireJq() {
	if ! command -v jq &>/dev/null; then
		echo '{"success":false,"error":"jq is required but not installed"}'
		exit 1
	fi
}

function nowTs() {
	date +%s
}

function gbToBytes() {
	local gb="$1"
	awk -v gb="$gb" 'BEGIN { printf "%.0f", gb * 1024 * 1024 * 1024 }'
}

function getDefaultLimitGB() {
	if [[ -n "${DEFAULT_DATA_LIMIT_GB:-}" ]]; then
		echo "${DEFAULT_DATA_LIMIT_GB}"
		return 0
	fi
	if [[ -f /etc/wireguard/params ]]; then
		# shellcheck source=/dev/null
		source /etc/wireguard/params
		echo "${DEFAULT_DATA_LIMIT_GB:-}"
	fi
}

function resolveLimitGB() {
	local explicit="$1"
	if [[ -n "${explicit}" ]]; then
		echo "${explicit}"
		return 0
	fi
	getDefaultLimitGB
}

function loadServerParams() {
	if [[ ! -e /etc/wireguard/params ]]; then
		echo '{"success":false,"error":"WireGuard is not installed"}'
		exit 1
	fi
	# shellcheck source=/dev/null
	source /etc/wireguard/params
}

function getHomeDirForClient() {
	local CLIENT_NAME=$1
	if [ -z "${CLIENT_NAME}" ]; then
		echo "Error: getHomeDirForClient() requires a client name"
		exit 1
	fi
	if [ -e "/home/${CLIENT_NAME}" ]; then
		HOME_DIR="/home/${CLIENT_NAME}"
	elif [ "${SUDO_USER}" ]; then
		[[ "${SUDO_USER}" == "root" ]] && HOME_DIR="/root" || HOME_DIR="/home/${SUDO_USER}"
	else
		HOME_DIR="/root"
	fi
	echo "$HOME_DIR"
}

function isValidClientsFile() {
	local file="$1"
	[[ -s "${file}" ]] && jq -e '.clients | type == "object"' "${file}" >/dev/null 2>&1
}

function metaInit() {
	mkdir -p /etc/wireguard
	if isValidClientsFile "${CLIENTS_JSON}"; then
		return 0
	fi
	# Main file is missing or corrupt (e.g. after disk-full / crash):
	# restore the last good backup, otherwise recreate an empty skeleton
	# (importExistingPeers will rebuild entries from the wg conf).
	if isValidClientsFile "${CLIENTS_JSON}.bak"; then
		cp -p "${CLIENTS_JSON}.bak" "${CLIENTS_JSON}"
		return 0
	fi
	if [[ -f "${CLIENTS_JSON}" ]]; then
		mv "${CLIENTS_JSON}" "${CLIENTS_JSON}.corrupt" 2>/dev/null || true
	fi
	echo '{"version":1,"clients":{}}' >"${CLIENTS_JSON}"
	chmod 600 "${CLIENTS_JSON}"
}

function metaRead() {
	metaInit
	jq -c '.' "${CLIENTS_JSON}"
}

function metaWrite() {
	local json="$1"
	local tmp
	# Never replace the live file with invalid data (protects against a
	# failed jq pipeline handing us an empty string).
	if ! jq -e '.clients | type == "object"' <<<"${json}" >/dev/null 2>&1; then
		echo "metaWrite: refusing to write invalid clients JSON" >&2
		return 1
	fi
	tmp="$(mktemp "${CLIENTS_JSON}.XXXXXX")"
	printf '%s\n' "${json}" >"${tmp}"
	# Re-validate what actually landed on disk (catches partial writes when
	# the disk is full) before atomically replacing the live file.
	if ! isValidClientsFile "${tmp}"; then
		rm -f "${tmp}"
		echo "metaWrite: temp file failed validation, keeping previous clients.json" >&2
		return 1
	fi
	chmod 600 "${tmp}"
	if [[ -f "${CLIENTS_JSON}" ]]; then
		cp -p "${CLIENTS_JSON}" "${CLIENTS_JSON}.bak" 2>/dev/null || true
	fi
	mv "${tmp}" "${CLIENTS_JSON}"
}

function withLock() {
	local mode="$1"
	shift
	mkdir -p "$(dirname "${LOCK_FILE}")"
	touch "${LOCK_FILE}"
	(
		if [[ "${mode}" == "nonblock" ]]; then
			flock -n 200 || exit 0
		else
			flock -x 200
		fi
		"$@"
	) 200>"${LOCK_FILE}"
}

function clientExistsInMeta() {
	local name="$1"
	jq -e --arg n "${name}" '.clients[$n] != null' "${CLIENTS_JSON}" >/dev/null 2>&1
}

function clientConfPath() {
	local name="$1"
	local home
	home="$(getHomeDirForClient "${name}")"
	echo "${home}/${SERVER_WG_NIC}-client-${name}.conf"
}

function syncWireGuard() {
	local tmp
	tmp="$(mktemp)"
	wg-quick strip "${SERVER_WG_NIC}" >"${tmp}"
	wg syncconf "${SERVER_WG_NIC}" "${tmp}"
	rm -f "${tmp}"
}

function peerInConf() {
	local name="$1"
	grep -q -E "^### Client ${name}$" "/etc/wireguard/${SERVER_WG_NIC}.conf"
}

function removePeerFromConf() {
	local name="$1"
	if peerInConf "${name}"; then
		sed -i "/^### Client ${name}$/,/^$/d" "/etc/wireguard/${SERVER_WG_NIC}.conf"
		syncWireGuard
	fi
}

function addPeerToConf() {
	local name="$1"
	local pub="$2"
	local psk="$3"
	local ipv4="$4"
	if peerInConf "${name}"; then
		return 0
	fi
	cat >>"/etc/wireguard/${SERVER_WG_NIC}.conf" <<EOF

### Client ${name}
[Peer]
PublicKey = ${pub}
PresharedKey = ${psk}
AllowedIPs = ${ipv4}/32
EOF
	syncWireGuard
}

function findFreeIpv4() {
	local dot_ip candidate meta_ips
	meta_ips="$(jq -r '.clients[]?.ipv4 // empty' "${CLIENTS_JSON}" 2>/dev/null)"
	for dot_ip in $(seq 2 254); do
		candidate="${SERVER_WG_IPV4::-1}${dot_ip}"
		if [[ $(grep -c "${candidate}/32" "/etc/wireguard/${SERVER_WG_NIC}.conf") -ne 0 ]]; then
			continue
		fi
		if grep -qxF "${candidate}" <<<"${meta_ips}"; then
			continue
		fi
		echo "${candidate}"
		return 0
	done
	return 1
}

function parsePeerBlock() {
	local name="$1"
	local conf="/etc/wireguard/${SERVER_WG_NIC}.conf"
	local block pub psk ip
	block="$(awk "/^### Client ${name}$/,/^$/" "${conf}")"
	pub="$(echo "${block}" | awk -F' = ' '/^PublicKey/{print $2}')"
	psk="$(echo "${block}" | awk -F' = ' '/^PresharedKey/{print $2}')"
	ip="$(echo "${block}" | awk -F' = ' '/^AllowedIPs/{print $2}' | cut -d/ -f1)"
	echo "${pub}|${psk}|${ip}"
}

function importExistingPeers() {
	local conf="/etc/wireguard/${SERVER_WG_NIC}.conf"
	local meta name parsed pub psk ip rest now changed
	[[ -f "${conf}" ]] || return 0
	meta="$(metaRead)"
	now="$(nowTs)"
	changed=""
	# Single jq call to find conf peers missing from meta (normally none).
	while IFS= read -r name; do
		[[ -z "${name}" ]] && continue
		parsed="$(parsePeerBlock "${name}")"
		pub="${parsed%%|*}"
		rest="${parsed#*|}"
		psk="${rest%%|*}"
		ip="${rest##*|}"
		[[ -z "${pub}" || -z "${ip}" ]] && continue
		meta="$(jq -c \
			--arg n "${name}" \
			--arg pub "${pub}" \
			--arg psk "${psk}" \
			--arg ip "${ip}" \
			--argjson now "${now}" \
			'.clients[$n] = {
				name: $n,
				publicKey: $pub,
				presharedKey: $psk,
				ipv4: $ip,
				createdAt: $now,
				expiresAt: null,
				dataLimitBytes: null,
				usedBytes: 0,
				lastSnapshotRx: 0,
				lastSnapshotTx: 0,
				status: "active",
				disabledReason: null
			}' <<<"${meta}")"
		changed="1"
	done < <(grep -E '^### Client ' "${conf}" 2>/dev/null | awk '{print $3}' \
		| jq -R -r -n --argjson existing "$(jq -c '.clients | keys' <<<"${meta}")" \
			'[inputs | select(length > 0)] - $existing | .[]')
	if [[ -n "${changed}" ]]; then
		metaWrite "${meta}"
	fi
	return 0
}

function withinLimits() {
	local name="$1"
	local meta used limit expires now
	meta="$(metaRead)"
	now="$(nowTs)"
	used="$(jq -r --arg n "${name}" '.clients[$n].usedBytes // 0' <<<"${meta}")"
	limit="$(jq -r --arg n "${name}" '.clients[$n].dataLimitBytes // empty' <<<"${meta}")"
	expires="$(jq -r --arg n "${name}" '.clients[$n].expiresAt // empty' <<<"${meta}")"
	if [[ -n "${limit}" && "${limit}" != "null" && "${used}" -ge "${limit}" ]]; then
		return 1
	fi
	if [[ -n "${expires}" && "${expires}" != "null" && "${now}" -ge "${expires}" ]]; then
		return 1
	fi
	return 0
}

function resolveClientEndpoint() {
	if [[ -n "${CLIENT_ENDPOINT:-}" ]]; then
		echo "${CLIENT_ENDPOINT}"
	else
		echo "${SERVER_PUB_IP}:${SERVER_PORT}"
	fi
}

function readConfField() {
	local file="$1"
	local key="$2"
	grep -m1 -E "^${key} = " "${file}" 2>/dev/null | sed -E "s/^${key} = //"
}

function cmdRefreshConfInternal() {
	local name="$1"
	local meta home conf_file priv ipv4 psk
	if ! clientExistsInMeta "${name}"; then
		echo '{"success":false,"error":"Client not found"}'
		return 1
	fi
	home="$(getHomeDirForClient "${name}")"
	conf_file="${home}/${SERVER_WG_NIC}-client-${name}.conf"
	if [[ ! -f "${conf_file}" ]]; then
		echo '{"success":false,"error":"Client config file not found"}'
		return 1
	fi
	priv="$(readConfField "${conf_file}" "PrivateKey")"
	ipv4="$(readConfField "${conf_file}" "Address")"
	ipv4="${ipv4%/32}"
	if [[ -z "${priv}" || -z "${ipv4}" ]]; then
		echo '{"success":false,"error":"Invalid client config"}'
		return 1
	fi
	meta="$(metaRead)"
	psk="$(jq -r --arg n "${name}" '.clients[$n].presharedKey // empty' <<<"${meta}")"
	if [[ -z "${psk}" ]]; then
		psk="$(readConfField "${conf_file}" "PresharedKey")"
	fi
	CLIENT_PRE_SHARED_KEY="${psk}"
	buildClientConf "${name}" "${priv}" "${ipv4}"
	jq -n --arg name "${name}" --arg path "${conf_file}" '{success:true, name:$name, confPath:$path, message:"config refreshed"}'
}

function cmdRefreshConf() {
	local name="$1"
	if [[ -z "${name}" ]]; then
		echo '{"success":false,"error":"Client name is required"}'
		exit 1
	fi
	withLock block cmdRefreshConfInternal "${name}"
}

function cmdRefreshAllConfsInternal() {
	local name refreshed
	refreshed='[]'
	while IFS= read -r name; do
		if cmdRefreshConfInternal "${name}" >/dev/null 2>&1; then
			refreshed="$(jq -c --arg n "${name}" '. + [$n]' <<<"${refreshed}")"
		fi
	done < <(jq -r '.clients | keys[]' "${CLIENTS_JSON}")
	jq -n --argjson refreshed "${refreshed}" '{success:true, refreshed:$refreshed, count:($refreshed|length)}'
}

function cmdRefreshAllConfs() {
	withLock block cmdRefreshAllConfsInternal
}

function buildClientConf() {
	local name="$1"
	local priv="$2"
	local ipv4="$3"
	local home endpoint dns_line conf_file
	home="$(getHomeDirForClient "${name}")"
	conf_file="${home}/${SERVER_WG_NIC}-client-${name}.conf"
	endpoint="$(resolveClientEndpoint)"
	if [[ -n "${CLIENT_DNS_2:-}" && "${CLIENT_DNS_2}" != "${CLIENT_DNS_1}" ]]; then
		dns_line="${CLIENT_DNS_1},${CLIENT_DNS_2}"
	else
		dns_line="${CLIENT_DNS_1}"
	fi
	{
		echo "[Interface]"
		echo "PrivateKey = ${priv}"
		echo "Address = ${ipv4}/32"
		if [[ -n "${CLIENT_MTU:-}" && "${CLIENT_MTU}" =~ ^[0-9]+$ ]]; then
			echo "MTU = ${CLIENT_MTU}"
		fi
		echo "DNS = ${dns_line}"
		echo ""
		echo "[Peer]"
		echo "PublicKey = ${SERVER_PUB_KEY}"
		echo "PresharedKey = ${CLIENT_PRE_SHARED_KEY}"
		echo "Endpoint = ${endpoint}"
		echo "AllowedIPs = ${ALLOWED_IPS}"
	} >"${conf_file}"
	chmod 600 "${conf_file}"
}

function cmdAddInternal() {
	local name="$1"
	local limit_gb="$2"
	local days="$3"
	local ip_override="$4"
	local explicit_limit="$5"
	local meta now expires limit_bytes priv pub psk ipv4 home resolved_limit
	if [[ ! "${name}" =~ ^[a-zA-Z0-9_-]+$ || ${#name} -gt 64 ]]; then
		echo '{"success":false,"error":"Invalid client name"}'
		return 1
	fi
	if clientExistsInMeta "${name}"; then
		echo '{"success":false,"error":"Client already exists"}'
		return 1
	fi
	if [[ -n "${ip_override}" ]]; then
		ipv4="${SERVER_WG_IPV4::-1}${ip_override}"
	else
		ipv4="$(findFreeIpv4)" || {
			echo '{"success":false,"error":"No free IPv4 addresses"}'
			return 1
		}
	fi
	if grep -q "${ipv4}/32" "/etc/wireguard/${SERVER_WG_NIC}.conf"; then
		echo '{"success":false,"error":"IPv4 already in use"}'
		return 1
	fi
	now="$(nowTs)"
	expires="null"
	limit_bytes="null"
	if [[ -n "${days}" ]]; then
		expires="$((now + days * 86400))"
	fi
	if [[ "${explicit_limit}" == "1" ]]; then
		if [[ -z "${limit_gb}" || "${limit_gb}" == "0" ]]; then
			limit_bytes="null"
		else
			limit_bytes="$(gbToBytes "${limit_gb}")"
		fi
	else
		resolved_limit="$(resolveLimitGB "${limit_gb}")"
		if [[ -n "${resolved_limit}" ]]; then
			limit_bytes="$(gbToBytes "${resolved_limit}")"
		fi
	fi
	priv="$(wg genkey)"
	pub="$(echo "${priv}" | wg pubkey)"
	psk="$(wg genpsk)"
	CLIENT_PRE_SHARED_KEY="${psk}"
	buildClientConf "${name}" "${priv}" "${ipv4}"
	addPeerToConf "${name}" "${pub}" "${psk}" "${ipv4}"
	meta="$(metaRead)"
	meta="$(jq -c \
		--arg n "${name}" \
		--arg pub "${pub}" \
		--arg psk "${psk}" \
		--arg ip "${ipv4}" \
		--argjson now "${now}" \
		--argjson expires "${expires}" \
		--argjson limit "${limit_bytes}" \
		'.clients[$n] = {
			name: $n,
			publicKey: $pub,
			presharedKey: $psk,
			ipv4: $ip,
			createdAt: $now,
			expiresAt: (if $expires == null then null else $expires end),
			dataLimitBytes: (if $limit == null then null else $limit end),
			usedBytes: 0,
			lastSnapshotRx: 0,
			lastSnapshotTx: 0,
			status: "active",
			disabledReason: null
		}' <<<"${meta}")"
	metaWrite "${meta}"
	home="$(getHomeDirForClient "${name}")"
	jq -n \
		--arg name "${name}" \
		--arg confPath "${home}/${SERVER_WG_NIC}-client-${name}.conf" \
		--argjson expires "${expires}" \
		--argjson limit "${limit_bytes}" \
		'{success:true, name:$name, confPath:$confPath, expiresAt:(if $expires == null then null else $expires end), dataLimitBytes:(if $limit == null then null else $limit end)}'
}

function cmdAdd() {
	local name="" limit_gb="" days="" ip_override="" explicit_limit=""
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--limit-gb) limit_gb="$2"; shift 2 ;;
		--explicit-limit) explicit_limit="1"; shift ;;
		--days) days="$2"; shift 2 ;;
		--ip) ip_override="$2"; shift 2 ;;
		*) name="$1"; shift ;;
		esac
	done
	if [[ -z "${name}" ]]; then
		echo '{"success":false,"error":"Client name is required"}'
		exit 1
	fi
	if [[ -n "${limit_gb}" && -z "${explicit_limit}" ]]; then
		explicit_limit="1"
	fi
	withLock block cmdAddInternal "${name}" "${limit_gb}" "${days}" "${ip_override}" "${explicit_limit}"
}

function disableClientInMeta() {
	local name="$1"
	local reason="$2"
	local meta="$3"
	local status
	status="$(jq -r --arg n "${name}" '.clients[$n].status' <<<"${meta}")"
	if [[ "${status}" == "disabled" ]]; then
		echo "${meta}"
		return 0
	fi
	removePeerFromConf "${name}"
	jq -c \
		--arg n "${name}" \
		--arg reason "${reason}" \
		'.clients[$n].status = "disabled" | .clients[$n].disabledReason = $reason' <<<"${meta}"
}

# Fully removes a client (peer from conf + conf file + meta entry) and
# returns the updated meta JSON on stdout. Used by enforcement so that an
# expired or over-quota service is disconnected AND deleted; any remaining
# volume/time is forfeited and the user must purchase again to get a new config.
function removeClientInMeta() {
	local name="$1"
	local meta="$2"
	local home
	removePeerFromConf "${name}"
	home="$(getHomeDirForClient "${name}")"
	rm -f "${home}/${SERVER_WG_NIC}-client-${name}.conf"
	jq -c --arg n "${name}" 'del(.clients[$n])' <<<"${meta}"
}

function cmdDisableInternal() {
	local name="$1"
	local reason="$2"
	local meta
	if ! clientExistsInMeta "${name}"; then
		echo '{"success":false,"error":"Client not found"}'
		return 1
	fi
	meta="$(metaRead)"
	local status
	status="$(jq -r --arg n "${name}" '.clients[$n].status' <<<"${meta}")"
	if [[ "${status}" == "disabled" ]]; then
		jq -n --arg name "${name}" '{success:true, name:$name, status:"disabled", message:"already disabled"}'
		return 0
	fi
	removePeerFromConf "${name}"
	meta="$(jq -c \
		--arg n "${name}" \
		--arg reason "${reason}" \
		'.clients[$n].status = "disabled" | .clients[$n].disabledReason = $reason' <<<"${meta}")"
	metaWrite "${meta}"
	jq -n --arg name "${name}" --arg reason "${reason}" '{success:true, name:$name, status:"disabled", reason:$reason}'
}

function cmdDisable() {
	local name="$1"
	local reason="${2:-manual}"
	if [[ -z "${name}" ]]; then
		echo '{"success":false,"error":"Client name is required"}'
		exit 1
	fi
	withLock block cmdDisableInternal "${name}" "${reason}"
}

function cmdEnableInternal() {
	local name="$1"
	local meta pub psk ip
	if ! clientExistsInMeta "${name}"; then
		echo '{"success":false,"error":"Client not found"}'
		return 1
	fi
	meta="$(metaRead)"
	local status
	status="$(jq -r --arg n "${name}" '.clients[$n].status' <<<"${meta}")"
	if [[ "${status}" == "active" ]]; then
		jq -n --arg name "${name}" '{success:true, name:$name, status:"active", message:"already active"}'
		return 0
	fi
	if ! withinLimits "${name}"; then
		echo '{"success":false,"error":"Client is still over quota or expired"}'
		return 1
	fi
	pub="$(jq -r --arg n "${name}" '.clients[$n].publicKey' <<<"${meta}")"
	psk="$(jq -r --arg n "${name}" '.clients[$n].presharedKey' <<<"${meta}")"
	ip="$(jq -r --arg n "${name}" '.clients[$n].ipv4' <<<"${meta}")"
	addPeerToConf "${name}" "${pub}" "${psk}" "${ip}"
	# Re-added peers start with fresh wg counters, so reset the snapshots to
	# avoid mis-measuring the next usage diff.
	meta="$(jq -c \
		--arg n "${name}" \
		'.clients[$n].status = "active" | .clients[$n].disabledReason = null
		 | .clients[$n].lastSnapshotRx = 0 | .clients[$n].lastSnapshotTx = 0' <<<"${meta}")"
	metaWrite "${meta}"
	jq -n --arg name "${name}" '{success:true, name:$name, status:"active"}'
}

function cmdEnable() {
	local name="$1"
	if [[ -z "${name}" ]]; then
		echo '{"success":false,"error":"Client name is required"}'
		exit 1
	fi
	withLock block cmdEnableInternal "${name}"
}

function cmdRemoveInternal() {
	local name="$1"
	local home
	if ! clientExistsInMeta "${name}"; then
		if peerInConf "${name}"; then
			removePeerFromConf "${name}"
		fi
		home="$(getHomeDirForClient "${name}")"
		rm -f "${home}/${SERVER_WG_NIC}-client-${name}.conf"
		echo '{"success":true,"name":"'"${name}"'","message":"removed from config"}'
		return 0
	fi
	removePeerFromConf "${name}"
	home="$(getHomeDirForClient "${name}")"
	rm -f "${home}/${SERVER_WG_NIC}-client-${name}.conf"
	local meta
	meta="$(metaRead)"
	meta="$(jq -c --arg n "${name}" 'del(.clients[$n])' <<<"${meta}")"
	metaWrite "${meta}"
	jq -n --arg name "${name}" '{success:true, name:$name, message:"removed"}'
}

function cmdRemove() {
	local name="$1"
	if [[ -z "${name}" ]]; then
		echo '{"success":false,"error":"Client name is required"}'
		exit 1
	fi
	withLock block cmdRemoveInternal "${name}"
}

function cmdUpdateInternal() {
	local name="$1"
	local add_gb="$2"
	local extend_days="$3"
	local set_limit_gb="$4"
	local set_expires_at="$5"
	local clear_expires="$6"
	local meta now expires limit add_bytes should_enable
	if ! clientExistsInMeta "${name}"; then
		echo '{"success":false,"error":"Client not found"}'
		return 1
	fi
	meta="$(metaRead)"
	now="$(nowTs)"
	if [[ -n "${set_limit_gb}" ]]; then
		limit="$(gbToBytes "${set_limit_gb}")"
		meta="$(jq -c --arg n "${name}" --argjson limit "${limit}" '.clients[$n].dataLimitBytes = $limit' <<<"${meta}")"
	fi
	if [[ -n "${add_gb}" ]]; then
		add_bytes="$(gbToBytes "${add_gb}")"
		meta="$(jq -c --arg n "${name}" --argjson add "${add_bytes}" '
			.clients[$n].dataLimitBytes = (
				if (.clients[$n].dataLimitBytes == null) then $add
				else (.clients[$n].dataLimitBytes + $add)
				end
			)' <<<"${meta}")"
	fi
	if [[ -n "${set_expires_at}" ]]; then
		meta="$(jq -c --arg n "${name}" --argjson ts "${set_expires_at}" '.clients[$n].expiresAt = $ts' <<<"${meta}")"
	fi
	if [[ -n "${extend_days}" ]]; then
		expires="$(jq -r --arg n "${name}" '.clients[$n].expiresAt // 0' <<<"${meta}")"
		if [[ "${expires}" == "null" || "${expires}" == "0" || "${expires}" -lt "${now}" ]]; then
			expires="${now}"
		fi
		expires="$((expires + extend_days * 86400))"
		meta="$(jq -c --arg n "${name}" --argjson ts "${expires}" '.clients[$n].expiresAt = $ts' <<<"${meta}")"
	fi
	if [[ "${clear_expires}" == "1" ]]; then
		meta="$(jq -c --arg n "${name}" '.clients[$n].expiresAt = null' <<<"${meta}")"
	fi
	metaWrite "${meta}"
	should_enable="$(jq -r --arg n "${name}" '.clients[$n].status' <<<"${meta}")"
	if [[ "${should_enable}" == "disabled" ]] && withinLimits "${name}"; then
		cmdEnableInternal "${name}" >/dev/null
	fi
	meta="$(metaRead)"
	jq -n --argjson client "$(jq -c --arg n "${name}" '.clients[$n]' <<<"${meta}")" '{success:true, client:$client}'
}

function cmdUpdate() {
	local name="" add_gb="" extend_days="" set_limit_gb="" set_expires_at="" clear_expires=""
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--add-gb) add_gb="$2"; shift 2 ;;
		--extend-days) extend_days="$2"; shift 2 ;;
		--set-limit-gb) set_limit_gb="$2"; shift 2 ;;
		--set-expires-at) set_expires_at="$2"; shift 2 ;;
		--clear-expires) clear_expires="1"; shift ;;
		*) name="$1"; shift ;;
		esac
	done
	if [[ -z "${name}" ]]; then
		echo '{"success":false,"error":"Client name is required"}'
		exit 1
	fi
	withLock block cmdUpdateInternal "${name}" "${add_gb}" "${extend_days}" "${set_limit_gb}" "${set_expires_at}" "${clear_expires}"
}

function cmdInfo() {
	local name="$1"
	if [[ -z "${name}" ]]; then
		echo '{"success":false,"error":"Client name is required"}'
		exit 1
	fi
	if ! clientExistsInMeta "${name}"; then
		echo '{"success":false,"error":"Client not found"}'
		exit 1
	fi
	jq -c --arg n "${name}" '{success:true, client:.clients[$n]}' "${CLIENTS_JSON}"
}

function cmdList() {
	jq -c '{success:true, clients:.clients}' "${CLIENTS_JSON}"
}

# `wg show <nic> transfer` prints tab-separated lines: <pubkey>\t<rx>\t<tx>
# Convert them to a JSON map {pubkey: {rx, tx}} in a single jq call.
function transferLinesToJson() {
	local input="$1"
	if [[ -z "${input}" ]]; then
		echo '{}'
		return 0
	fi
	jq -R -c -n '
		[inputs
		 | select(length > 0)
		 | split("\t")
		 | select(length >= 3)
		 | select((.[1] | test("^[0-9]+$")) and (.[2] | test("^[0-9]+$")))
		 | {key: .[0], value: {rx: (.[1] | tonumber), tx: (.[2] | tonumber)}}]
		| from_entries' <<<"${input}" 2>/dev/null || echo '{}'
}

function cmdEnforceInternal() {
	local now meta updated transfer_lines transfers disabled_report name reason removed_any
	importExistingPeers
	now="$(nowTs)"
	meta="$(metaRead)"
	if [[ -z "${meta}" ]]; then
		echo '{"success":false,"error":"clients.json unreadable"}'
		return 1
	fi
	transfer_lines="$(wg show "${SERVER_WG_NIC}" transfer 2>/dev/null || true)"
	transfers="$(transferLinesToJson "${transfer_lines}")"
	[[ -z "${transfers}" ]] && transfers='{}'

	# Single jq pass: accumulate usage for every client based on counter diffs.
	# Negative diff means WireGuard counters were reset (reboot / peer re-add):
	# in that case the whole current counter is new traffic.
	# On jq failure keep the previous meta instead of an empty string.
	updated="$(jq -c --argjson transfers "${transfers}" '
		.clients |= with_entries(
			.value as $c
			| ($transfers[$c.publicKey // ""] // null) as $t
			| if $t == null then .
			  else
				(($t.rx - ($c.lastSnapshotRx // 0)) | if . < 0 then $t.rx else . end) as $drx
				| (($t.tx - ($c.lastSnapshotTx // 0)) | if . < 0 then $t.tx else . end) as $dtx
				| .value.usedBytes = (($c.usedBytes // 0) + $drx + $dtx)
				| .value.lastSnapshotRx = $t.rx
				| .value.lastSnapshotTx = $t.tx
			  end
		)' <<<"${meta}")" && [[ -n "${updated}" ]] && meta="${updated}"

	# Single jq pass: find active clients that are over quota or expired.
	disabled_report="[]"
	removed_any=""
	while IFS='|' read -r name reason; do
		[[ -z "${name}" ]] && continue
		if peerInConf "${name}"; then
			sed -i "/^### Client ${name}$/,/^$/d" "/etc/wireguard/${SERVER_WG_NIC}.conf"
			removed_any="1"
		fi
		updated="$(jq -c --arg n "${name}" --arg reason "${reason}" \
			'.clients[$n].status = "disabled" | .clients[$n].disabledReason = $reason' <<<"${meta}")" \
			&& [[ -n "${updated}" ]] && meta="${updated}"
		disabled_report="$(jq -c --arg n "${name}" --arg r "${reason}" \
			'. + [{name:$n, reason:$r, action:"disabled"}]' <<<"${disabled_report}" || echo "${disabled_report}")"
	done < <(jq -r --argjson now "${now}" '
		.clients | to_entries[]
		| select(.value.status == "active")
		| (if ((.value.dataLimitBytes != null) and ((.value.usedBytes // 0) >= .value.dataLimitBytes)) then "quota_exceeded"
		   elif ((.value.expiresAt != null) and ($now >= .value.expiresAt)) then "expired"
		   else empty end) as $reason
		| .key + "|" + $reason' <<<"${meta}")

	if [[ -n "${removed_any}" ]]; then
		syncWireGuard
	fi

	metaWrite "${meta}"
	jq -n --argjson disabled "${disabled_report}" --argjson ts "${now}" '{success:true, checkedAt:$ts, disabled:$disabled}'
}

function cmdEnforce() {
	withLock nonblock cmdEnforceInternal
}

function initialCheck() {
	isRoot
	checkVirt
	checkOS
}

function installQuestions() {
	echo "Welcome to the WireGuard installer (IPv4 only)"
	echo ""

	SERVER_PUB_IP=$(ip -4 addr | sed -ne 's|^.* inet \([^/]*\)/.* scope global.*$|\1|p' | head -1)
	read -rp "IPv4 public address: " -e -i "${SERVER_PUB_IP}" SERVER_PUB_IP

	SERVER_NIC="$(ip -4 route ls | grep default | grep -Po '(?<=dev )(\S+)' | head -1)"
	until [[ ${SERVER_PUB_NIC} =~ ^[a-zA-Z0-9_]+$ ]]; do
		read -rp "Public interface: " -e -i "${SERVER_NIC}" SERVER_PUB_NIC
	done

	until [[ ${SERVER_WG_NIC} =~ ^[a-zA-Z0-9_]+$ && ${#SERVER_WG_NIC} -lt 16 ]]; do
		read -rp "WireGuard interface name: " -e -i wg0 SERVER_WG_NIC
	done

	until [[ ${SERVER_WG_IPV4} =~ ^([0-9]{1,3}\.){3} ]]; do
		read -rp "Server WireGuard IPv4: " -e -i 10.66.66.1 SERVER_WG_IPV4
	done

	RANDOM_PORT=$(shuf -i49152-65535 -n1)
	until [[ ${SERVER_PORT} =~ ^[0-9]+$ ]] && [ "${SERVER_PORT}" -ge 1 ] && [ "${SERVER_PORT}" -le 65535 ]; do
		read -rp "Server WireGuard port [1-65535]: " -e -i "${RANDOM_PORT}" SERVER_PORT
	done

	until [[ ${CLIENT_DNS_1} =~ ^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$ ]]; do
		read -rp "First DNS resolver for clients: " -e -i 1.1.1.1 CLIENT_DNS_1
	done
	until [[ ${CLIENT_DNS_2} =~ ^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$ ]]; do
		read -rp "Second DNS resolver (optional): " -e -i 1.0.0.1 CLIENT_DNS_2
		[[ -z ${CLIENT_DNS_2} ]] && CLIENT_DNS_2="${CLIENT_DNS_1}"
	done

	until [[ ${ALLOWED_IPS} =~ ^.+$ ]]; do
		echo -e "\nAllowed IPs determine what is routed through VPN."
		read -rp "Allowed IPs for clients: " -e -i '0.0.0.0/0' ALLOWED_IPS
		[[ -z ${ALLOWED_IPS} ]] && ALLOWED_IPS="0.0.0.0/0"
	done

	echo -e "\nDefault data limit for new users (expiry is managed by your site, not this server)."
	until [[ ${DEFAULT_DATA_LIMIT_GB} =~ ^[0-9]+([.][0-9]+)?$ ]] && awk -v gb="${DEFAULT_DATA_LIMIT_GB}" 'BEGIN { exit !(gb > 0) }'; do
		read -rp "Default data limit per user (GB): " -e -i "10" DEFAULT_DATA_LIMIT_GB
	done

	echo -e "\nReady to setup your WireGuard server."
	read -n1 -r -p "Press any key to continue..."
}

function installWireGuard() {
	installQuestions

	if [[ ${OS} == 'ubuntu' ]] || [[ ${OS} == 'debian' && ${VERSION_ID} -gt 10 ]]; then
		apt-get update
		apt-get install -y wireguard iptables resolvconf qrencode jq
	elif [[ ${OS} == 'debian' ]]; then
		if ! grep -rqs "^deb .* buster-backports" /etc/apt/; then
			echo "deb http://deb.debian.org/debian buster-backports main" >/etc/apt/sources.list.d/backports.list
			apt-get update
		fi
		apt-get install -y iptables resolvconf qrencode jq
		apt-get install -y -t buster-backports wireguard
	elif [[ ${OS} == 'fedora' ]]; then
		dnf install -y wireguard-tools iptables qrencode jq
	elif [[ ${OS} == 'centos' ]] || [[ ${OS} == 'almalinux' ]] || [[ ${OS} == 'rocky' ]]; then
		yum install -y wireguard-tools iptables qrencode jq
	elif [[ ${OS} == 'oracle' ]]; then
		dnf install -y wireguard-tools qrencode iptables jq
	elif [[ ${OS} == 'arch' ]]; then
		pacman -S --needed --noconfirm wireguard-tools qrencode jq
	fi

	mkdir -p /etc/wireguard
	chmod 600 -R /etc/wireguard/

	SERVER_PRIV_KEY=$(wg genkey)
	SERVER_PUB_KEY=$(echo "${SERVER_PRIV_KEY}" | wg pubkey)

	cat >/etc/wireguard/params <<EOF
SERVER_PUB_IP=${SERVER_PUB_IP}
SERVER_PUB_NIC=${SERVER_PUB_NIC}
SERVER_WG_NIC=${SERVER_WG_NIC}
SERVER_WG_IPV4=${SERVER_WG_IPV4}
SERVER_PORT=${SERVER_PORT}
SERVER_PRIV_KEY=${SERVER_PRIV_KEY}
SERVER_PUB_KEY=${SERVER_PUB_KEY}
CLIENT_DNS_1=${CLIENT_DNS_1}
CLIENT_DNS_2=${CLIENT_DNS_2}
CLIENT_ENDPOINT=
CLIENT_MTU=
ALLOWED_IPS=${ALLOWED_IPS}
DEFAULT_DATA_LIMIT_GB=${DEFAULT_DATA_LIMIT_GB}
EOF

	cat >"/etc/wireguard/${SERVER_WG_NIC}.conf" <<EOF
[Interface]
Address = ${SERVER_WG_IPV4}/24
ListenPort = ${SERVER_PORT}
PrivateKey = ${SERVER_PRIV_KEY}
PostUp   = sysctl -w net.ipv4.ip_forward=1
PostUp   = iptables -I INPUT -p udp --dport ${SERVER_PORT} -j ACCEPT
PostUp   = iptables -I FORWARD -i ${SERVER_PUB_NIC} -o ${SERVER_WG_NIC} -j ACCEPT
PostUp   = iptables -I FORWARD -i ${SERVER_WG_NIC} -j ACCEPT
PostUp   = iptables -t nat -A POSTROUTING -o ${SERVER_PUB_NIC} -j MASQUERADE
PostDown = iptables -D INPUT -p udp --dport ${SERVER_PORT} -j ACCEPT
PostDown = iptables -D FORWARD -i ${SERVER_PUB_NIC} -o ${SERVER_WG_NIC} -j ACCEPT
PostDown = iptables -D FORWARD -i ${SERVER_WG_NIC} -j ACCEPT
PostDown = iptables -t nat -D POSTROUTING -o ${SERVER_PUB_NIC} -j MASQUERADE
EOF

	enableIpForwardPersistent
	ensureWgPostUpIpForward

	systemctl start "wg-quick@${SERVER_WG_NIC}"
	systemctl enable "wg-quick@${SERVER_WG_NIC}"

	metaInit
	newClient
	echo -e "${GREEN}If you want to add more clients, run this script again!${NC}"

	if systemctl is-active --quiet "wg-quick@${SERVER_WG_NIC}"; then
		echo -e "\n${GREEN}WireGuard is running.${NC}"
	else
		echo -e "\n${RED}WARNING: WireGuard does not seem to be running.${NC}"
	fi
}

function newClient() {
	ENDPOINT="${SERVER_PUB_IP}:${SERVER_PORT}"

	echo -e "\nClient configuration\n"
	echo "Allowed characters for client name: a-z, A-Z, 0-9, _ or - (max 15 chars)."
	until [[ ${CLIENT_NAME} =~ ^[a-zA-Z0-9_-]+$ && ${CLIENT_EXISTS} == '0' ]]; do
		read -rp "Client name: " -e CLIENT_NAME
		CLIENT_EXISTS=$(grep -c -E "^### Client ${CLIENT_NAME}\$" "/etc/wireguard/${SERVER_WG_NIC}.conf")
		[[ ${CLIENT_EXISTS} != 0 ]] && echo -e "${ORANGE}A client with that name already exists, choose another.${NC}"
	done

	for DOT_IP in {2..254}; do
		[[ $(grep -c "${SERVER_WG_IPV4::-1}${DOT_IP}" "/etc/wireguard/${SERVER_WG_NIC}.conf") == 0 ]] && break
	done
	[[ ${DOT_IP} == 255 ]] && { echo "Subnet full (253 clients max)"; exit 1; }

	BASE_IP=$(echo "$SERVER_WG_IPV4" | awk -F '.' '{ print $1"."$2"."$3 }')
	until [[ ${IPV4_EXISTS} == '0' ]]; do
		read -rp "Client WireGuard IPv4: ${BASE_IP}." -e -i "${DOT_IP}" DOT_IP
		CLIENT_WG_IPV4="${BASE_IP}.${DOT_IP}"
		IPV4_EXISTS=$(grep -c "$CLIENT_WG_IPV4/32" "/etc/wireguard/${SERVER_WG_NIC}.conf")
		[[ ${IPV4_EXISTS} != 0 ]] && echo -e "${ORANGE}IPv4 already in use, choose another.${NC}"
	done

	CLIENT_PRIV_KEY=$(wg genkey)
	CLIENT_PUB_KEY=$(echo "${CLIENT_PRIV_KEY}" | wg pubkey)
	CLIENT_PRE_SHARED_KEY=$(wg genpsk)
	HOME_DIR=$(getHomeDirForClient "${CLIENT_NAME}")
	buildClientConf "${CLIENT_NAME}" "${CLIENT_PRIV_KEY}" "${CLIENT_WG_IPV4}"

	cat >>"/etc/wireguard/${SERVER_WG_NIC}.conf" <<EOF

### Client ${CLIENT_NAME}
[Peer]
PublicKey = ${CLIENT_PUB_KEY}
PresharedKey = ${CLIENT_PRE_SHARED_KEY}
AllowedIPs = ${CLIENT_WG_IPV4}/32
EOF
	wg syncconf "${SERVER_WG_NIC}" <(wg-quick strip "${SERVER_WG_NIC}")

	requireJq
	metaInit
	local now meta default_gb limit_bytes
	now="$(nowTs)"
	default_gb="$(getDefaultLimitGB)"
	limit_bytes="null"
	if [[ -n "${default_gb}" ]]; then
		limit_bytes="$(gbToBytes "${default_gb}")"
	fi
	meta="$(metaRead)"
	meta="$(jq -c \
		--arg n "${CLIENT_NAME}" \
		--arg pub "${CLIENT_PUB_KEY}" \
		--arg psk "${CLIENT_PRE_SHARED_KEY}" \
		--arg ip "${CLIENT_WG_IPV4}" \
		--argjson now "${now}" \
		--argjson limit "${limit_bytes}" \
		'.clients[$n] = {
			name: $n,
			publicKey: $pub,
			presharedKey: $psk,
			ipv4: $ip,
			createdAt: $now,
			expiresAt: null,
			dataLimitBytes: (if $limit == null then null else $limit end),
			usedBytes: 0,
			lastSnapshotRx: 0,
			lastSnapshotTx: 0,
			status: "active",
			disabledReason: null
		}' <<<"${meta}")"
	metaWrite "${meta}"

	if command -v qrencode &>/dev/null; then
		echo -e "${GREEN}\nQR Code for client configuration:\n${NC}"
		qrencode -t ansiutf8 -l L <"${HOME_DIR}/${SERVER_WG_NIC}-client-${CLIENT_NAME}.conf"
	fi
	echo -e "${GREEN}Client config saved to ${HOME_DIR}/${SERVER_WG_NIC}-client-${CLIENT_NAME}.conf${NC}"
}

function listClients() {
	NUMBER_OF_CLIENTS=$(grep -c -E "^### Client" "/etc/wireguard/${SERVER_WG_NIC}.conf")
	[[ ${NUMBER_OF_CLIENTS} -eq 0 ]] && { echo "No existing clients!"; exit 1; }
	grep -E "^### Client" "/etc/wireguard/${SERVER_WG_NIC}.conf" | cut -d ' ' -f 3 | nl -s ') '
}

function revokeClient() {
	NUMBER_OF_CLIENTS=$(grep -c -E "^### Client" "/etc/wireguard/${SERVER_WG_NIC}.conf")
	[[ ${NUMBER_OF_CLIENTS} -eq 0 ]] && { echo "No existing clients!"; exit 1; }
	echo -e "\nSelect the client to revoke:"
	grep -E "^### Client" "/etc/wireguard/${SERVER_WG_NIC}.conf" | cut -d ' ' -f 3 | nl -s ') '
	until [[ ${CLIENT_NUMBER} -ge 1 && ${CLIENT_NUMBER} -le ${NUMBER_OF_CLIENTS} ]]; do
		read -rp "Select [1-${NUMBER_OF_CLIENTS}]: " CLIENT_NUMBER
	done
	CLIENT_NAME=$(grep -E "^### Client" "/etc/wireguard/${SERVER_WG_NIC}.conf" | cut -d ' ' -f 3 | sed -n "${CLIENT_NUMBER}"p)
	requireJq
	withLock block cmdRemoveInternal "${CLIENT_NAME}" >/dev/null
	echo -e "${GREEN}Client ${CLIENT_NAME} revoked.${NC}"
}

function uninstallWg() {
	echo -e "\n${RED}WARNING: This will uninstall WireGuard and remove all configuration!${NC}"
	read -rp "Do you really want to remove WireGuard? [y/N]: " -e REMOVE
	REMOVE=${REMOVE:-n}
	if [[ $REMOVE == 'y' ]]; then
		checkOS
		systemctl stop "wg-quick@${SERVER_WG_NIC}"
		systemctl disable "wg-quick@${SERVER_WG_NIC}"
		if [[ ${OS} == 'ubuntu' || ${OS} == 'debian' ]]; then
			apt-get remove -y wireguard wireguard-tools qrencode
		elif [[ ${OS} == 'fedora' ]]; then
			dnf remove -y --noautoremove wireguard-tools qrencode
		elif [[ ${OS} == 'centos' ]] || [[ ${OS} == 'almalinux' ]] || [[ ${OS} == 'rocky' ]]; then
			yum remove -y --noautoremove wireguard-tools qrencode
		elif [[ ${OS} == 'oracle' ]]; then
			yum remove --noautoremove wireguard-tools qrencode
		elif [[ ${OS} == 'arch' ]]; then
			pacman -Rs --noconfirm wireguard-tools qrencode
		fi
		rm -rf /etc/wireguard
		rm -f /etc/sysctl.d/wg.conf "${IP_FORWARD_CONF}"
		sysctl --system
		echo "WireGuard uninstalled."
	else
		echo "Removal aborted!"
	fi
}

function manageMenu() {
	echo "WireGuard is already installed."
	echo "   1) Add a new user"
	echo "   2) List all users"
	echo "   3) Revoke existing user"
	echo "   4) Uninstall WireGuard"
	echo "   5) Exit"
	until [[ ${MENU_OPTION} =~ ^[1-5]$ ]]; do
		read -rp "Select an option [1-5]: " MENU_OPTION
	done
	case "${MENU_OPTION}" in
	1) newClient ;;
	2) listClients ;;
	3) revokeClient ;;
	4) uninstallWg ;;
	5) exit 0 ;;
	esac
}

function runCli() {
	local cmd="$1"
	shift
	requireJq
	loadServerParams
	metaInit
	case "${cmd}" in
	add) cmdAdd "$@" ;;
	update) cmdUpdate "$@" ;;
	disable) cmdDisable "$@" ;;
	enable) cmdEnable "$@" ;;
	remove) cmdRemove "$@" ;;
	info) cmdInfo "$@" ;;
	list) cmdList ;;
	enforce) cmdEnforce ;;
	refresh-conf) cmdRefreshConf "$@" ;;
	refresh-all-confs) cmdRefreshAllConfs ;;
	enable-ip-forward)
		loadServerParams
		enableIpForwardPersistent
		ensureWgPostUpIpForward
		jq -n '{success:true, message:"ip_forward enabled persistently"}'
		;;
	*)
		echo '{"success":false,"error":"Unknown command"}'
		exit 1
		;;
	esac
}

if [[ $# -gt 0 ]]; then
	initialCheck
	runCli "$@"
	exit 0
fi

initialCheck
if [[ -e /etc/wireguard/params ]]; then
	source /etc/wireguard/params
	manageMenu
else
	installWireGuard
fi
