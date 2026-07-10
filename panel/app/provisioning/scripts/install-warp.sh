#!/bin/bash
# Smite remote WARP installer (foreign servers only).
#
# Two modes (WARP_MODE):
#   warp  -> installs Cloudflare WARP (warp-cli, proxy mode on 127.0.0.1:40000)
#            and routes WireGuard client egress through WARP. No upstream proxy
#            details are needed from the user.
#   proxy -> routes WireGuard client egress through a user-supplied upstream
#            proxy (SOCKS5 / HTTP-CONNECT) via PROXY_* env vars.
#
# Both modes install plain WireGuard + wvpn (from the bundled wginstaller-proxy)
# and then set up the redsocks egress. Prints a single machine-readable result.
#
# Environment variables:
#   WARP_BUNDLE   tarball to extract (default: /root/smite-warp-bundle.tar.gz)
#   WARP_MODE     warp | proxy (default: proxy)
#   WVPN_PORT     management/panel port (default 4000)
#   PROXY_IP, PROXY_PORT, PROXY_TYPE, PROXY_USER, PROXY_PASS  (proxy mode only)
set -e

red='\033[0;31m'; green='\033[0;32m'; yellow='\033[0;33m'; plain='\033[0m'
[[ $EUID -ne 0 ]] && echo -e "${red}This installer must run as root${plain}" && exit 1

json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\n\r'
}

WARP_BUNDLE="${WARP_BUNDLE:-/root/smite-warp-bundle.tar.gz}"
WARP_DIR_SRC="/opt/wginstaller-proxy"
PROXY_ENV="/etc/wvpn-proxy.env"
WARP_MODE="${WARP_MODE:-proxy}"
WARP_PROXY_PORT="40000"

export WVPN_NONINTERACTIVE=1
export DEBIAN_FRONTEND=noninteractive

# --- Cloudflare WARP (proxy mode) --------------------------------------------
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
        apt-get install -y cloudflare-warp || {
            echo -e "${red}Failed to install cloudflare-warp package.${plain}"; return 1;
        }
    else
        echo "Cloudflare WARP already installed."
    fi
    # Register (idempotent). Newer CLI: 'registration new'; older: 'register'.
    if ! warp-cli --accept-tos registration show >/dev/null 2>&1 \
        && ! warp-cli --accept-tos account >/dev/null 2>&1; then
        warp-cli --accept-tos registration new >/dev/null 2>&1 \
            || warp-cli --accept-tos register >/dev/null 2>&1 || true
    fi
    # Proxy mode + fixed port + connect (try new then old CLI syntax).
    warp-cli --accept-tos mode proxy >/dev/null 2>&1 \
        || warp-cli --accept-tos set-mode proxy >/dev/null 2>&1 || true
    warp-cli --accept-tos proxy port "${WARP_PROXY_PORT}" >/dev/null 2>&1 \
        || warp-cli --accept-tos set-proxy-port "${WARP_PROXY_PORT}" >/dev/null 2>&1 || true
    warp-cli --accept-tos connect >/dev/null 2>&1 || true
    # Wait for the local SOCKS proxy to come up.
    local i
    for i in 1 2 3 4 5 6 7 8; do
        if ss -ltn 2>/dev/null | grep -q "127.0.0.1:${WARP_PROXY_PORT}"; then
            echo "Cloudflare WARP proxy is listening on 127.0.0.1:${WARP_PROXY_PORT}."
            return 0
        fi
        sleep 2
    done
    echo -e "${yellow}WARP proxy not confirmed listening on :${WARP_PROXY_PORT} yet (continuing).${plain}"
    return 0
}

if [[ ! -f "$WARP_BUNDLE" ]]; then
    echo -e "${red}WARP bundle not found at ${WARP_BUNDLE}${plain}"
    exit 1
fi

echo "Extracting WARP (wginstaller-proxy) installer bundle ..."
rm -rf "$WARP_DIR_SRC"
mkdir -p "$WARP_DIR_SRC"
tar -xzf "$WARP_BUNDLE" -C "$WARP_DIR_SRC"
cd "$WARP_DIR_SRC"
chmod +x install.sh wvpn/install.sh wvpn/proxy-egress.sh 2>/dev/null || true

# --- Egress config: decide the upstream proxy --------------------------------
PROXY_ENABLED="false"
EFF_PROXY_IP=""; EFF_PROXY_PORT=""; EFF_PROXY_TYPE="socks5"; EFF_PROXY_USER=""; EFF_PROXY_PASS=""

if [[ "$WARP_MODE" == "warp" ]]; then
    echo "WARP mode: installing Cloudflare WARP as the upstream egress ..."
    install_cloudflare_warp
    EFF_PROXY_IP="127.0.0.1"; EFF_PROXY_PORT="${WARP_PROXY_PORT}"; EFF_PROXY_TYPE="socks5"
    PROXY_ENABLED="true"
elif [[ -n "${PROXY_IP:-}" && -n "${PROXY_PORT:-}" ]]; then
    EFF_PROXY_IP="${PROXY_IP}"; EFF_PROXY_PORT="${PROXY_PORT}"
    EFF_PROXY_TYPE="${PROXY_TYPE:-socks5}"; EFF_PROXY_USER="${PROXY_USER:-}"; EFF_PROXY_PASS="${PROXY_PASS:-}"
    PROXY_ENABLED="true"
else
    echo -e "${yellow}No upstream proxy provided; installing plain WireGuard without egress proxy.${plain}"
fi

if [[ "$PROXY_ENABLED" == "true" ]]; then
    echo "Writing upstream-proxy config to ${PROXY_ENV} ..."
    umask 077
    {
        echo "PROXY_IP=${EFF_PROXY_IP}"
        echo "PROXY_PORT=${EFF_PROXY_PORT}"
        echo "PROXY_TYPE=${EFF_PROXY_TYPE}"
        echo "PROXY_USER=${EFF_PROXY_USER}"
        echo "PROXY_PASS=${EFF_PROXY_PASS}"
        echo "WG_NIC=wg0"
        echo "REDSOCKS_LOCAL_PORT=12345"
    } > "$PROXY_ENV"
    chmod 600 "$PROXY_ENV"
fi

echo "Running WARP installer (this can take a few minutes)..."
bash install.sh

# --- Extract installed parameters --------------------------------------------
WG_PORT=""; SERVER_PUB_KEY=""; SERVER_PUB_IP=""; WG_NIC="wg0"; API_PORT="4000"
PARAMS_FILE="/etc/wireguard/params"
if [[ -f "$PARAMS_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$PARAMS_FILE" 2>/dev/null || true
    WG_PORT="${SERVER_PORT:-}"
    SERVER_PUB_KEY="${SERVER_PUB_KEY:-}"
    SERVER_PUB_IP="${SERVER_PUB_IP:-}"
    WG_NIC="${SERVER_WG_NIC:-wg0}"
    API_PORT="${WVPN_PORT:-4000}"
fi

# wvpn management API key + admin path.
API_KEY=""; ADMIN_PATH=""
for WVPN_CONFIG in "/etc/wvpn/wvpn.json" "/home/wvpn/wvpn.json"; do
    [[ -f "$WVPN_CONFIG" ]] || continue
    if command -v jq >/dev/null 2>&1; then
        API_KEY="$(jq -r '.apiKey // empty' "$WVPN_CONFIG" 2>/dev/null || true)"
        ADMIN_PATH="$(jq -r '.adminPath // empty' "$WVPN_CONFIG" 2>/dev/null || true)"
    fi
    if [[ -z "$API_KEY" ]]; then
        API_KEY="$(grep -oE '"apiKey"[[:space:]]*:[[:space:]]*"[^"]*"' "$WVPN_CONFIG" 2>/dev/null | head -n1 | sed -E 's/.*:[[:space:]]*"([^"]*)".*/\1/' || true)"
    fi
    [[ -n "$API_KEY" ]] && break
done

# Proxy egress runtime status.
PROXY_STATUS="disabled"
if [[ "$PROXY_ENABLED" == "true" ]]; then
    if systemctl is-active --quiet wvpn-redsocks 2>/dev/null; then
        PROXY_STATUS="active"
    else
        PROXY_STATUS="inactive"
    fi
fi

echo ""
echo -e "${green}WARP (${WARP_MODE} mode) installation finished.${plain}"
printf '===SMITE_WARP_RESULT=== {"mode":"%s","wgPort":"%s","serverPublicKey":"%s","serverPublicIp":"%s","wgInterface":"%s","apiPort":"%s","apiKey":"%s","adminPath":"%s","proxyEnabled":"%s","proxyType":"%s","proxyEndpoint":"%s","proxyStatus":"%s"}\n' \
    "$(json_escape "${WARP_MODE}")" "$(json_escape "${WG_PORT}")" "$(json_escape "${SERVER_PUB_KEY}")" "$(json_escape "${SERVER_PUB_IP}")" \
    "$(json_escape "${WG_NIC}")" "$(json_escape "${API_PORT}")" "$(json_escape "${API_KEY}")" \
    "$(json_escape "${ADMIN_PATH}")" "$(json_escape "${PROXY_ENABLED}")" "$(json_escape "${EFF_PROXY_TYPE}")" \
    "$(json_escape "${EFF_PROXY_IP}:${EFF_PROXY_PORT}")" "$(json_escape "${PROXY_STATUS}")"
