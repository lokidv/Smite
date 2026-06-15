#!/bin/bash
# Smite remote WireGuard installer (foreign servers only).
#
# Clones lokidv/wginstaller and runs it fully non-interactively, then extracts
# the resulting WireGuard server parameters, the wvpn management API endpoint
# and the default client config. Prints a single machine-readable result line.
#
# Environment variables:
#   WG_REPO   git repo to clone (default: https://github.com/lokidv/wginstaller.git)
set -e

red='\033[0;31m'; green='\033[0;32m'; plain='\033[0m'
[[ $EUID -ne 0 ]] && echo -e "${red}This installer must run as root${plain}" && exit 1

json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\n\r'
}

WG_REPO="${WG_REPO:-https://github.com/lokidv/wginstaller.git}"
WG_DIR="/opt/wginstaller"

export WVPN_NONINTERACTIVE=1
export DEBIAN_FRONTEND=noninteractive

# Ensure git/curl are available (target is a foreign server with internet).
if ! command -v git >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -q 2>/dev/null || true
        apt-get install -y -q git curl ca-certificates 2>/dev/null || true
    fi
fi

echo "Cloning ${WG_REPO} ..."
rm -rf "$WG_DIR"
git clone --depth 1 "$WG_REPO" "$WG_DIR"
cd "$WG_DIR"
chmod +x install.sh wvpn/install.sh 2>/dev/null || true

echo "Running WireGuard installer (this can take a few minutes)..."
bash install.sh

# --- Extract installed parameters --------------------------------------------
WG_PORT=""; SERVER_PUB_KEY=""; SERVER_PUB_IP=""; WG_NIC="wg0"
PARAMS_FILE="/etc/wireguard/params"
if [[ -f "$PARAMS_FILE" ]]; then
    # The params file is a set of KEY=VALUE lines (wireguard-install format).
    # shellcheck disable=SC1090
    source "$PARAMS_FILE" 2>/dev/null || true
    WG_PORT="${SERVER_PORT:-}"
    SERVER_PUB_KEY="${SERVER_PUB_KEY:-}"
    SERVER_PUB_IP="${SERVER_PUB_IP:-}"
    WG_NIC="${SERVER_WG_NIC:-wg0}"
fi

# Default client config produced by the installer (client name: loki).
CLIENT_CONF=""
for f in "/home/loki/${WG_NIC}-client-loki.conf" "/root/${WG_NIC}-client-loki.conf" "/root/wg0-client-loki.conf"; do
    if [[ -f "$f" ]]; then
        CLIENT_CONF="$f"
        break
    fi
done
CLIENT_CONF_B64=""
if [[ -n "$CLIENT_CONF" ]]; then
    CLIENT_CONF_B64="$(base64 -w0 "$CLIENT_CONF" 2>/dev/null || base64 "$CLIENT_CONF" | tr -d '\n')"
fi

# wvpn management API listens on a fixed port (see wvpn/main.js).
API_PORT="4000"

# wvpn generates an API key at install time and stores it in its config file.
# Read it so the panel can show it to the user (it is required to call the API).
API_KEY=""
for WVPN_CONFIG in "/etc/wvpn/wvpn.json" "/opt/wginstaller/wvpn/wvpn.json"; do
    [[ -f "$WVPN_CONFIG" ]] || continue
    if command -v jq >/dev/null 2>&1; then
        API_KEY="$(jq -r '.apiKey // .api_key // .apikey // empty' "$WVPN_CONFIG" 2>/dev/null || true)"
    fi
    if [[ -z "$API_KEY" ]]; then
        API_KEY="$(grep -oE '"api[_]?[Kk]ey"[[:space:]]*:[[:space:]]*"[^"]*"' "$WVPN_CONFIG" 2>/dev/null | head -n1 | sed -E 's/.*:[[:space:]]*"([^"]*)".*/\1/' || true)"
    fi
    [[ -n "$API_KEY" ]] && break
done

echo ""
echo -e "${green}WireGuard + wvpn installation finished.${plain}"
printf '===SMITE_WG_RESULT=== {"wgPort":"%s","serverPublicKey":"%s","serverPublicIp":"%s","wgInterface":"%s","apiPort":"%s","apiKey":"%s","clientConfigB64":"%s"}\n' \
    "$(json_escape "${WG_PORT}")" "$(json_escape "${SERVER_PUB_KEY}")" "$(json_escape "${SERVER_PUB_IP}")" \
    "$(json_escape "${WG_NIC}")" "$(json_escape "${API_PORT}")" "$(json_escape "${API_KEY}")" "$(json_escape "${CLIENT_CONF_B64}")"
