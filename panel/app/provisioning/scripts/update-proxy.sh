#!/bin/bash
# Smite — change the WireGuard egress proxy on an already-installed WARP/proxy
# server (used when the upstream proxy dies or the admin switches proxy/WARP).
#
# Rewrites /etc/wvpn-proxy.env, regenerates the redsocks config + iptables rules
# via the on-server proxy-egress.sh, and RESTARTS wvpn-redsocks so the new
# upstream takes effect immediately (the old one is dropped). Prints a result.
#
# Environment variables:
#   WARP_MODE   warp | proxy (default: proxy)
#   PROXY_IP, PROXY_PORT, PROXY_TYPE, PROXY_USER, PROXY_PASS   (proxy mode)
set -e

red='\033[0;31m'; green='\033[0;32m'; yellow='\033[0;33m'; plain='\033[0m'
[[ $EUID -ne 0 ]] && echo -e "${red}This must run as root${plain}" && exit 1

json_escape() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\n\r'; }

PROXY_ENV="/etc/wvpn-proxy.env"
WARP_MODE="${WARP_MODE:-proxy}"
WARP_PROXY_PORT="40000"
export DEBIAN_FRONTEND=noninteractive

EGRESS=""
for c in /home/wvpn/proxy-egress.sh /opt/wginstaller-proxy/wvpn/proxy-egress.sh; do
    [[ -f "$c" ]] && { EGRESS="$c"; break; }
done
if [[ -z "$EGRESS" ]]; then
    echo -e "${red}proxy-egress.sh not found on this server; is WARP/proxy installed?${plain}"
    exit 1
fi

install_cloudflare_warp() {
    if ! command -v warp-cli >/dev/null 2>&1; then
        echo "Installing Cloudflare WARP ..."
        mkdir -p /usr/share/keyrings
        curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg \
            | gpg --yes --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
        . /etc/os-release
        local codename="${VERSION_CODENAME:-}"
        [[ -z "$codename" ]] && codename="$(lsb_release -cs 2>/dev/null || echo jammy)"
        echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ ${codename} main" \
            > /etc/apt/sources.list.d/cloudflare-client.list
        apt-get update -y || true
        apt-get install -y cloudflare-warp || { echo -e "${red}cloudflare-warp install failed${plain}"; return 1; }
    fi
    if ! warp-cli --accept-tos registration show >/dev/null 2>&1 \
        && ! warp-cli --accept-tos account >/dev/null 2>&1; then
        warp-cli --accept-tos registration new >/dev/null 2>&1 \
            || warp-cli --accept-tos register >/dev/null 2>&1 || true
    fi
    warp-cli --accept-tos mode proxy >/dev/null 2>&1 || warp-cli --accept-tos set-mode proxy >/dev/null 2>&1 || true
    warp-cli --accept-tos proxy port "${WARP_PROXY_PORT}" >/dev/null 2>&1 || warp-cli --accept-tos set-proxy-port "${WARP_PROXY_PORT}" >/dev/null 2>&1 || true
    warp-cli --accept-tos connect >/dev/null 2>&1 || true
    local i
    for i in 1 2 3 4 5 6 7 8; do
        ss -ltn 2>/dev/null | grep -q "127.0.0.1:${WARP_PROXY_PORT}" && return 0
        sleep 2
    done
    return 0
}

EFF_IP=""; EFF_PORT=""; EFF_TYPE="socks5"; EFF_USER=""; EFF_PASS=""
if [[ "$WARP_MODE" == "warp" ]]; then
    install_cloudflare_warp
    EFF_IP="127.0.0.1"; EFF_PORT="${WARP_PROXY_PORT}"; EFF_TYPE="socks5"
elif [[ -n "${PROXY_IP:-}" && -n "${PROXY_PORT:-}" ]]; then
    EFF_IP="${PROXY_IP}"; EFF_PORT="${PROXY_PORT}"; EFF_TYPE="${PROXY_TYPE:-socks5}"
    EFF_USER="${PROXY_USER:-}"; EFF_PASS="${PROXY_PASS:-}"
else
    echo -e "${red}proxy mode requires PROXY_IP and PROXY_PORT${plain}"; exit 2
fi

echo "Writing new upstream-proxy config to ${PROXY_ENV} ..."
umask 077
{
    echo "PROXY_IP=${EFF_IP}"
    echo "PROXY_PORT=${EFF_PORT}"
    echo "PROXY_TYPE=${EFF_TYPE}"
    echo "PROXY_USER=${EFF_USER}"
    echo "PROXY_PASS=${EFF_PASS}"
    echo "WG_NIC=wg0"
    echo "REDSOCKS_LOCAL_PORT=12345"
} > "$PROXY_ENV"
chmod 600 "$PROXY_ENV"

echo "Re-applying egress (regenerate redsocks config + iptables) ..."
bash "$EGRESS"

echo "Restarting redsocks so the new upstream takes effect ..."
systemctl restart wvpn-redsocks 2>/dev/null || true
sleep 1

PROXY_STATUS="inactive"
systemctl is-active --quiet wvpn-redsocks 2>/dev/null && PROXY_STATUS="active"

echo ""
echo -e "${green}Egress proxy updated (${WARP_MODE} mode).${plain}"
printf '===SMITE_PROXY_UPDATE_RESULT=== {"mode":"%s","proxyType":"%s","proxyEndpoint":"%s","proxyStatus":"%s"}\n' \
    "$(json_escape "${WARP_MODE}")" "$(json_escape "${EFF_TYPE}")" \
    "$(json_escape "${EFF_IP}:${EFF_PORT}")" "$(json_escape "${PROXY_STATUS}")"
