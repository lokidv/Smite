#!/bin/bash
# Smite remote 3x-ui installer (fully non-interactive).
#
# Installs the MHSanaei/3x-ui panel at a fixed version and configures the login
# credentials / port / web base path via the `x-ui` CLI (instead of the upstream
# interactive `config_after_install`). Prints a single machine-readable result
# line so the panel can parse the final credentials.
#
# Environment variables:
#   XUI_VERSION   release tag to install, e.g. v2.9.4 (required)
#   XUI_TARBALL   optional path to a pre-staged x-ui-linux-<arch>.tar.gz. When set
#                 (Iran / no-GitHub targets) it is used instead of downloading.
#   XUI_USERNAME  panel username (random if empty)
#   XUI_PASSWORD  panel password (random if empty)
#   XUI_PORT      panel port (random 10000-60000 if empty)
#   XUI_WEBPATH   panel web base path (random if empty)
set -e

red='\033[0;31m'; green='\033[0;32m'; plain='\033[0m'
xui_folder="/usr/local/x-ui"
xui_service="/etc/systemd/system"

[[ $EUID -ne 0 ]] && echo -e "${red}This installer must run as root${plain}" && exit 1

XUI_VERSION="${XUI_VERSION:-v2.9.4}"

if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    release=$ID
else
    release="ubuntu"
fi

arch() {
    case "$(uname -m)" in
        x86_64 | x64 | amd64) echo 'amd64' ;;
        i*86 | x86) echo '386' ;;
        armv8* | armv8 | arm64 | aarch64) echo 'arm64' ;;
        armv7* | armv7 | arm) echo 'armv7' ;;
        armv6* | armv6) echo 'armv6' ;;
        armv5* | armv5) echo 'armv5' ;;
        s390x) echo 's390x' ;;
        *) echo 'amd64' ;;
    esac
}
ARCH="$(arch)"
echo "OS: $release | Arch: $ARCH | Version: $XUI_VERSION"

gen_random_string() {
    local length="$1"
    openssl rand -base64 $((length * 2)) | tr -dc 'a-zA-Z0-9' | head -c "$length"
}

json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\n\r'
}

install_base() {
    echo "Installing base packages..."
    case "${release}" in
        ubuntu | debian | armbian)
            apt-get update -q 2>/dev/null || true
            apt-get install -y -q cron curl tar tzdata socat ca-certificates openssl 2>/dev/null || true
            ;;
        fedora | amzn | virtuozzo | rhel | almalinux | rocky | ol)
            dnf install -y -q cronie curl tar tzdata socat ca-certificates openssl 2>/dev/null || true
            ;;
        centos)
            yum install -y cronie curl tar tzdata socat ca-certificates openssl 2>/dev/null || true
            ;;
        arch | manjaro | parch)
            pacman -Syu --noconfirm cronie curl tar tzdata socat ca-certificates openssl 2>/dev/null || true
            ;;
        alpine)
            apk add dcron curl tar tzdata socat ca-certificates openssl 2>/dev/null || true
            ;;
        *)
            apt-get update -q 2>/dev/null || true
            apt-get install -y -q cron curl tar tzdata socat ca-certificates openssl 2>/dev/null || true
            ;;
    esac
}

install_base

cd /usr/local/

# --- Obtain the x-ui tarball -------------------------------------------------
TARBALL_DEST="/usr/local/x-ui-linux-${ARCH}.tar.gz"
if [[ -n "${XUI_TARBALL}" && -f "${XUI_TARBALL}" ]]; then
    echo "Using pre-staged tarball: ${XUI_TARBALL}"
    cp -f "${XUI_TARBALL}" "${TARBALL_DEST}"
else
    URL="https://github.com/MHSanaei/3x-ui/releases/download/${XUI_VERSION}/x-ui-linux-${ARCH}.tar.gz"
    echo "Downloading ${URL}"
    curl -4fLRo "${TARBALL_DEST}" "${URL}" || {
        echo -e "${red}Failed to download x-ui ${XUI_VERSION} (no GitHub access? upload the tarball instead)${plain}"
        exit 1
    }
fi

# --- Stop any existing install and unpack ------------------------------------
if [[ -e ${xui_folder}/ ]]; then
    systemctl stop x-ui 2>/dev/null || true
    rm -rf ${xui_folder}/
fi

tar zxf "${TARBALL_DEST}" -C /usr/local/
rm -f "${TARBALL_DEST}"

cd ${xui_folder}
chmod +x x-ui
[[ -f x-ui.sh ]] && chmod +x x-ui.sh
chmod +x bin/* 2>/dev/null || true

# Normalise the arm binary name if needed
if [[ "${ARCH}" == "armv5" || "${ARCH}" == "armv6" || "${ARCH}" == "armv7" ]]; then
    if [[ -f bin/xray-linux-${ARCH} ]]; then
        mv -f bin/xray-linux-${ARCH} bin/xray-linux-arm
        chmod +x bin/xray-linux-arm
    fi
fi

# --- CLI ---------------------------------------------------------------------
if [[ -f x-ui.sh ]]; then
    cp -f x-ui.sh /usr/bin/x-ui
    chmod +x /usr/bin/x-ui
fi
mkdir -p /var/log/x-ui

# --- systemd service ---------------------------------------------------------
service_installed=false
if [[ -f x-ui.service ]]; then
    cp -f x-ui.service ${xui_service}/x-ui.service && service_installed=true
fi
if [[ "$service_installed" = false ]]; then
    case "${release}" in
        ubuntu | debian | armbian) [[ -f x-ui.service.debian ]] && cp -f x-ui.service.debian ${xui_service}/x-ui.service && service_installed=true ;;
        arch | manjaro | parch) [[ -f x-ui.service.arch ]] && cp -f x-ui.service.arch ${xui_service}/x-ui.service && service_installed=true ;;
        *) [[ -f x-ui.service.rhel ]] && cp -f x-ui.service.rhel ${xui_service}/x-ui.service && service_installed=true ;;
    esac
fi
if [[ "$service_installed" = false ]]; then
    echo -e "${red}Could not find a bundled x-ui.service unit file${plain}"
    exit 1
fi
chown root:root ${xui_service}/x-ui.service 2>/dev/null || true
chmod 644 ${xui_service}/x-ui.service 2>/dev/null || true
systemctl daemon-reload
systemctl enable x-ui >/dev/null 2>&1 || true
systemctl start x-ui

# --- Configure credentials (non-interactive) ---------------------------------
CFG_USER="${XUI_USERNAME:-$(gen_random_string 10)}"
CFG_PASS="${XUI_PASSWORD:-$(gen_random_string 12)}"
CFG_PATH="${XUI_WEBPATH:-$(gen_random_string 12)}"
CFG_PORT="${XUI_PORT:-$(shuf -i 10000-60000 -n 1)}"

${xui_folder}/x-ui setting -username "${CFG_USER}" -password "${CFG_PASS}" -port "${CFG_PORT}" -webBasePath "${CFG_PATH}" >/dev/null 2>&1 || \
    ${xui_folder}/x-ui setting -username "${CFG_USER}" -password "${CFG_PASS}" -port "${CFG_PORT}" >/dev/null 2>&1 || true

${xui_folder}/x-ui migrate >/dev/null 2>&1 || true

API_TOKEN="$(${xui_folder}/x-ui setting -getApiToken true 2>/dev/null | grep -Eo 'apiToken: .+' | awk '{print $2}')" || true

systemctl restart x-ui 2>/dev/null || true

# Best-effort public IP detection (the panel also knows the SSH host).
SERVER_IP=""
for u in "https://api4.ipify.org" "https://ipv4.icanhazip.com" "https://4.ident.me"; do
    SERVER_IP="$(curl -s --max-time 3 "$u" 2>/dev/null | tr -d '[:space:]')"
    [[ "$SERVER_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && break
    SERVER_IP=""
done

echo ""
echo -e "${green}3x-ui ${XUI_VERSION} installation finished.${plain}"
# Machine-readable result line for the panel to parse.
printf '===SMITE_XUI_RESULT=== {"version":"%s","username":"%s","password":"%s","port":"%s","webBasePath":"%s","apiToken":"%s","serverIp":"%s"}\n' \
    "$(json_escape "${XUI_VERSION}")" "$(json_escape "${CFG_USER}")" "$(json_escape "${CFG_PASS}")" \
    "$(json_escape "${CFG_PORT}")" "$(json_escape "${CFG_PATH}")" "$(json_escape "${API_TOKEN}")" \
    "$(json_escape "${SERVER_IP}")"
