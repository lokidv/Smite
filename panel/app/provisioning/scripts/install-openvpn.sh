#!/bin/bash
# Smite remote OpenVPN installer (foreign servers only).
#
# The panel ships the whole ovpn-installer tree as a tarball (uploaded to
# $OVPN_BUNDLE) because it is not published on GitHub like wginstaller is.
# This wrapper extracts the bundle, runs its fully non-interactive installer,
# then extracts the resulting OpenVPN parameters, the panel/API endpoint and
# the admin credentials. Prints a single machine-readable result line.
#
# Environment variables (all optional, forwarded to the installer):
#   OVPN_BUNDLE          tarball to extract (default: /root/smite-openvpn-bundle.tar.gz)
#   OVPN_VPN_PORT        OpenVPN UDP/TCP port (default 1194)
#   OVPN_PROTOCOL        udp | tcp (default udp)
#   OVPN_PORT            panel/API port (default 4000)
#   OVPN_DEFAULT_LIMIT_GB  default per-user data cap in GB (default unlimited)
set -e

red='\033[0;31m'; green='\033[0;32m'; plain='\033[0m'
[[ $EUID -ne 0 ]] && echo -e "${red}This installer must run as root${plain}" && exit 1

json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\n\r'
}

OVPN_BUNDLE="${OVPN_BUNDLE:-/root/smite-openvpn-bundle.tar.gz}"
OVPN_DIR_SRC="/opt/ovpn-installer"

export OVPN_NONINTERACTIVE=1
export DEBIAN_FRONTEND=noninteractive

if [[ ! -f "$OVPN_BUNDLE" ]]; then
    echo -e "${red}OpenVPN bundle not found at ${OVPN_BUNDLE}${plain}"
    exit 1
fi

echo "Extracting OpenVPN installer bundle ..."
rm -rf "$OVPN_DIR_SRC"
mkdir -p "$OVPN_DIR_SRC"
tar -xzf "$OVPN_BUNDLE" -C "$OVPN_DIR_SRC"
cd "$OVPN_DIR_SRC"
chmod +x install.sh ovpn/install.sh openvpn-install/openvpn-install.sh 2>/dev/null || true

echo "Running OpenVPN installer (this can take a few minutes)..."
bash install.sh

# --- Extract installed parameters --------------------------------------------
SERVER_IP=""; VPN_PORT=""; VPN_PROTO=""
PARAMS_FILE="/etc/openvpn/ovpn-manager/params"
if [[ -f "$PARAMS_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$PARAMS_FILE" 2>/dev/null || true
    SERVER_IP="${SERVER_PUB_IP:-}"
    VPN_PORT="${SERVER_PORT:-}"
    VPN_PROTO="${SERVER_PROTOCOL:-}"
fi

# Panel / API config (apiKey + adminPath) lives in /etc/ovpn/ovpn.json.
API_KEY=""; ADMIN_PATH=""; PANEL_PORT="${OVPN_PORT:-4000}"
OVPN_CONFIG="/etc/ovpn/ovpn.json"
if [[ -f "$OVPN_CONFIG" ]]; then
    if command -v jq >/dev/null 2>&1; then
        API_KEY="$(jq -r '.apiKey // empty' "$OVPN_CONFIG" 2>/dev/null || true)"
        ADMIN_PATH="$(jq -r '.adminPath // empty' "$OVPN_CONFIG" 2>/dev/null || true)"
    fi
    if [[ -z "$API_KEY" ]]; then
        API_KEY="$(grep -oE '"apiKey"[[:space:]]*:[[:space:]]*"[^"]*"' "$OVPN_CONFIG" 2>/dev/null | head -n1 | sed -E 's/.*:[[:space:]]*"([^"]*)".*/\1/' || true)"
    fi
    if [[ -z "$ADMIN_PATH" ]]; then
        ADMIN_PATH="$(grep -oE '"adminPath"[[:space:]]*:[[:space:]]*"[^"]*"' "$OVPN_CONFIG" 2>/dev/null | head -n1 | sed -E 's/.*:[[:space:]]*"([^"]*)".*/\1/' || true)"
    fi
fi

# The plaintext admin password only exists in the install info file (the config
# stores a bcrypt hash). Read it back from there.
ADMIN_PASS=""
INFO_FILE="/root/ovpn-install-info.txt"
if [[ -f "$INFO_FILE" ]]; then
    ADMIN_PASS="$(awk -F': *' '/^Admin Pass/{print $2; exit}' "$INFO_FILE" 2>/dev/null || true)"
    [[ -z "$PANEL_PORT" ]] && PANEL_PORT="$(awk -F': *' '/^Panel Port/{print $2; exit}' "$INFO_FILE" 2>/dev/null || true)"
    [[ -z "$SERVER_IP" ]] && SERVER_IP="$(awk -F': *' '/^Server IP/{print $2; exit}' "$INFO_FILE" 2>/dev/null || true)"
fi

PANEL_URL=""
if [[ -n "$SERVER_IP" && -n "$PANEL_PORT" && -n "$ADMIN_PATH" ]]; then
    PANEL_URL="http://${SERVER_IP}:${PANEL_PORT}/${ADMIN_PATH}/"
fi

echo ""
echo -e "${green}OpenVPN + panel installation finished.${plain}"
printf '===SMITE_OVPN_RESULT=== {"serverIp":"%s","vpnProto":"%s","vpnPort":"%s","panelPort":"%s","panelUrl":"%s","adminPath":"%s","adminPassword":"%s","apiKey":"%s"}\n' \
    "$(json_escape "${SERVER_IP}")" "$(json_escape "${VPN_PROTO}")" "$(json_escape "${VPN_PORT}")" \
    "$(json_escape "${PANEL_PORT}")" "$(json_escape "${PANEL_URL}")" "$(json_escape "${ADMIN_PATH}")" \
    "$(json_escape "${ADMIN_PASS}")" "$(json_escape "${API_KEY}")"
