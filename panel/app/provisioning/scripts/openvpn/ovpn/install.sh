#!/usr/bin/env bash
# =============================================================================
# install.sh — one-shot installer for the OpenVPN panel (auto, non-interactive)
# -----------------------------------------------------------------------------
# Installs every prerequisite (Node.js 20, openvpn, easy-rsa, qrencode, jq, socat),
# runs angristan/openvpn-install.sh headlessly, wires up the ovpn-manager hooks
# (client-connect deny + client-disconnect accounting), installs the Node panel
# as a systemd service, and prints/saves the admin credentials.
#
#   sudo ./install.sh                 # fully automatic (defaults)
#   sudo OVPN_NONINTERACTIVE=0 ./install.sh   # ask questions
#
# Env overrides:
#   OVPN_PORT (panel, default 4000)   OVPN_VPN_PORT (openvpn, default 1194)
#   OVPN_PROTOCOL (udp|tcp)           OVPN_DNS1 / OVPN_DNS2
#   OVPN_ENDPOINT (client remote, default = server public IP)
#   OVPN_DEFAULT_LIMIT_GB             OVPN_TEST_CLIENT (name, optional)
# =============================================================================
set -uo pipefail

export OVPN_NONINTERACTIVE="${OVPN_NONINTERACTIVE:-1}"
export DEBIAN_FRONTEND=noninteractive

OVPN_DIR="/home/ovpn"
CONFIG_DIR="/etc/ovpn"
MGR_DIR="/etc/openvpn/ovpn-manager"
SERVER_CONF="/etc/openvpn/server/server.conf"
TEMPLATE="/etc/openvpn/server/client-template.txt"
PARAMS="${MGR_DIR}/params"
INFO_FILE="/root/ovpn-install-info.txt"
BASE_NAME="openvpn-install.sh"

RED='\033[0;31m'; GREEN='\033[0;32m'; ORANGE='\033[0;33m'; CYAN='\033[0;36m'; NC='\033[0m'
say()  { printf "${CYAN}[*]${NC} %s\n" "$*"; }
okk()  { printf "${GREEN}[+]${NC} %s\n" "$*"; }
warn() { printf "${ORANGE}[!]${NC} %s\n" "$*"; }
err()  { printf "${RED}[x]${NC} %s\n" "$*" >&2; }

if [[ "${EUID}" -ne 0 ]]; then
    err "لطفاً با root اجرا کنید: sudo ./install.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. OS prerequisites ──────────────────────────────────────────────────────
install_prereqs() {
    say "به‌روزرسانی مخزن و نصب پیش‌نیازها ..."
    apt-get update -y
    apt-get install -y ca-certificates curl gnupg git cron nano jq socat \
                       qrencode iproute2 openssl procps iptables
    # Node.js 20 (NodeSource)
    if ! command -v node >/dev/null 2>&1 || [[ "$(node -v 2>/dev/null | cut -d. -f1 | tr -d v)" -lt 18 ]]; then
        say "نصب Node.js 20 ..."
        apt-get install -y ca-certificates curl gnupg
        mkdir -p /etc/apt/keyrings
        curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
            | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
        echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
            > /etc/apt/sources.list.d/nodesource.list
        apt-get update -y
        apt-get install -y nodejs
    fi
    okk "پیش‌نیازها نصب شدند."
}

# ── 2. deploy project files ──────────────────────────────────────────────────
deploy_files() {
    say "کپی فایل‌های پروژه به ${OVPN_DIR} ..."
    mkdir -p "${OVPN_DIR}"
    # copy everything except node_modules/.git/_ssh
    (cd "${SCRIPT_DIR}" && \
        tar --exclude='./node_modules' --exclude='./.git' --exclude='./_ssh' \
            --exclude='./ovpn.log' -cf - .) | (cd "${OVPN_DIR}" && tar -xf -)
    # the base installer lives next to this script under ../openvpn-install/
    if [[ -f "${SCRIPT_DIR}/../openvpn-install/${BASE_NAME}" ]]; then
        cp "${SCRIPT_DIR}/../openvpn-install/${BASE_NAME}" "${OVPN_DIR}/${BASE_NAME}"
    elif [[ -f "${OVPN_DIR}/${BASE_NAME}" ]]; then
        : # already present
    else
        warn "openvpn-install.sh پیدا نشد؛ از گیت‌هاب دانلود می‌شود."
        curl -fsSL "https://raw.githubusercontent.com/angristan/openvpn-install/master/openvpn-install.sh" \
            -o "${OVPN_DIR}/${BASE_NAME}" || { err "دانلود openvpn-install.sh ناموفق بود"; exit 1; }
    fi
    chmod +x "${OVPN_DIR}/${BASE_NAME}" "${OVPN_DIR}/ovpn-manager.sh" \
             "${OVPN_DIR}/ovpn-connect.sh" "${OVPN_DIR}/ovpn-disconnect.sh" 2>/dev/null || true
    okk "فایل‌ها استقرار یافتند."
}

# ── 3. detect public IP ──────────────────────────────────────────────────────
detect_public_ip() {
    local ip=""
    ip="$(ip -4 addr | sed -ne 's|^.* inet \([^/]*\)/.* scope global.*$|\1|p' \
            | grep -vE '^(10\.|172\.1[6789]\.|172\.2[0-9]\.|172\.3[01]\.|192\.168\.|127\.|169\.254\.|docker)' | head -1)"
    if [[ -z "${ip}" ]]; then
        ip="$(curl -fsS4 --max-time 8 https://ifconfig.me 2>/dev/null || true)"
    fi
    if [[ -z "${ip}" ]]; then
        ip="$(ip -4 addr | sed -ne 's|^.* inet \([^/]*\)/.* scope global.*$|\1|p' | head -1)"
    fi
    echo "${ip}"
}

# ── 4. ask (interactive) or default ──────────────────────────────────────────
gather_options() {
    local PUB_IP; PUB_IP="$(detect_public_ip)"
    VPN_PORT="${OVPN_VPN_PORT:-1194}"
    PROTOCOL="${OVPN_PROTOCOL:-udp}"
    DNS1="${OVPN_DNS1:-1.1.1.1}"
    DNS2="${OVPN_DNS2:-1.0.0.1}"
    ENDPOINT="${OVPN_ENDPOINT:-${PUB_IP}}"
    DEFAULT_LIMIT_GB="${OVPN_DEFAULT_LIMIT_GB:-}"
    PANEL_PORT="${OVPN_PORT:-4000}"
    TEST_CLIENT="${OVPN_TEST_CLIENT:-}"

    if [[ "${OVPN_NONINTERACTIVE}" != "1" ]]; then
        read -rp "IPv4 عمومی سرور [${PUB_IP}]: " -e -i "${PUB_IP}" PUB_IP
        read -rp "پورت OpenVPN [${VPN_PORT}]: " -e -i "${VPN_PORT}" VPN_PORT
        read -rp "پروتکل (udp/tcp) [${PROTOCOL}]: " -e -i "${PROTOCOL}" PROTOCOL
        read -rp "DNS اول [${DNS1}]: " -e -i "${DNS1}" DNS1
        read -rp "DNS دوم [${DNS2}]: " -e -i "${DNS2}" DNS2
        read -rp "Endpoint کلاینت (خالی=${PUB_IP}): " -e -i "${ENDPOINT}" ENDPOINT
        read -rp "حجم پیش‌فرض کاربران به GB (خالی=نامحدود): " -e DEFAULT_LIMIT_GB
        read -rp "پورت پنل/API [${PANEL_PORT}]: " -e -i "${PANEL_PORT}" PANEL_PORT
        read -rp "نام کاربر تستی (اختیاری، خالی=بدون کاربر): " -e TEST_CLIENT
    fi
    # export for the node service / init-config
    export OVPN_PORT="${PANEL_PORT}"
    SERVER_PUB_IP="${PUB_IP}"
}

# ── 5. install OpenVPN via angristan base (headless) ─────────────────────────
install_openvpn() {
    if [[ -f "${SERVER_CONF}" ]]; then
        warn "OpenVPN از قبل نصب است؛ از نصب مجدد پایه صرف‌نظر می‌شود."
        return 0
    fi
    say "نصب OpenVPN (angristan/openvpn-install) به‌صورت خودکار ..."
    local args=(install --endpoint "${SERVER_PUB_IP}" --ip "${SERVER_PUB_IP}"
                     --port "${VPN_PORT}" --protocol "${PROTOCOL}"
                     --dns custom --dns-primary "${DNS1}" --dns-secondary "${DNS2}"
                     --no-client)
    bash "${OVPN_DIR}/${BASE_NAME}" "${args[@]}" || {
        err "نصب OpenVPN ناموفق بود."
        exit 1
    }
    okk "OpenVPN نصب و راه‌اندازی شد."
}

# ── 6. wire up manager hooks in server.conf ──────────────────────────────────
patch_server_conf() {
    [[ -f "${SERVER_CONF}" ]] || { err "server.conf پیدا نشد"; exit 1; }
    say "اضافه‌کردن hook های ovpn-manager به server.conf ..."
    # script-security + connect/disconnect hooks (idempotent)
    if ! grep -q '^client-connect' "${SERVER_CONF}"; then
        {
            echo ""
            echo "# ── ovpn-manager hooks ──"
            echo "script-security 2"
            echo "client-connect ${MGR_DIR}/ovpn-connect.sh"
            echo "client-disconnect ${MGR_DIR}/ovpn-disconnect.sh"
        } >> "${SERVER_CONF}"
    fi
    # ensure status + management are present (angristan adds them, but be safe).
    # status interval is lowered so live traffic accounting is near real-time.
    local status_interval="${OVPN_STATUS_INTERVAL:-10}"
    if grep -q '^status ' "${SERVER_CONF}"; then
        sed -i -E "s|^status .*|status /var/log/openvpn/status.log ${status_interval}|" "${SERVER_CONF}"
    else
        echo "status /var/log/openvpn/status.log ${status_interval}" >> "${SERVER_CONF}"
    fi
    grep -q '^management '    "${SERVER_CONF}" || echo "management /var/run/openvpn-server/server.sock unix" >> "${SERVER_CONF}"
    mkdir -p /var/log/openvpn /var/run/openvpn-server
    okk "hook ها متصل شدند."
}

# ── 7. manager dir + state + perms ───────────────────────────────────────────
setup_manager() {
    say "راه‌اندازی دایرکتوری ovpn-manager ..."
    mkdir -p "${MGR_DIR}/clients" /etc/openvpn/server/ccd
    cp "${OVPN_DIR}/ovpn-connect.sh" "${OVPN_DIR}/ovpn-disconnect.sh" "${MGR_DIR}/" 2>/dev/null || true
    chmod 0755 "${MGR_DIR}/ovpn-connect.sh" "${MGR_DIR}/ovpn-disconnect.sh" 2>/dev/null || true

    [[ -f "${MGR_DIR}/state.json" ]] || printf '{"clients":{}}' > "${MGR_DIR}/state.json"
    chmod 0644 "${MGR_DIR}/state.json"          # readable by openvpn runtime user (connect hook)
    : > "${MGR_DIR}/usage-events.log"; chmod 0666 "${MGR_DIR}/usage-events.log"  # append by nobody
    : > "${MGR_DIR}/denied.log";        chmod 0666 "${MGR_DIR}/denied.log"

    # params: prefer reading values back from the generated client-template (truth)
    local r_ip="${SERVER_PUB_IP}" r_port="${VPN_PORT}" r_proto="${PROTOCOL}"
    local r_cipher="AES-128-GCM" r_hmac="SHA256" r_srv="server"
    if [[ -f "${TEMPLATE}" ]]; then
        local line
        line="$(grep -m1 '^remote ' "${TEMPLATE}" || true)"; [[ -n "${line}" ]] && { r_ip="$(awk '{print $2}' <<<"$line")"; r_port="$(awk '{print $3}' <<<"$line")"; }
        line="$(grep -m1 '^proto ' "${TEMPLATE}" || true)";  [[ -n "${line}" ]] && r_proto="$(awk '{print $2}' <<<"$line")"
        [[ "${r_proto}" == tcp-client ]] && r_proto="tcp"
        line="$(grep -m1 '^cipher ' "${TEMPLATE}" || true)"; [[ -n "${line}" ]] && r_cipher="$(awk '{print $2}' <<<"$line")"
        line="$(grep -m1 '^auth ' "${TEMPLATE}" || true)";    [[ -n "${line}" ]] && r_hmac="$(awk '{print $2}' <<<"$line")"
        line="$(grep -m1 '^verify-x509-name ' "${TEMPLATE}" || true)"; [[ -n "${line}" ]] && r_srv="$(awk '{print $2}' <<<"$line")"
    fi
    : > "${PARAMS}"
    {
        echo "SERVER_PUB_IP=${r_ip}"
        echo "SERVER_PORT=${r_port}"
        echo "SERVER_PROTOCOL=${r_proto}"
        echo "SERVER_NAME=${r_srv}"
        echo "CLIENT_DNS_1=${DNS1}"
        echo "CLIENT_DNS_2=${DNS2}"
        echo "CLIENT_ENDPOINT="
        echo "CLIENT_MTU="
        echo "CLIENT_CIPHER=${r_cipher}"
        echo "CLIENT_HMAC=${r_hmac}"
        echo "DEFAULT_DATA_LIMIT_GB=${DEFAULT_LIMIT_GB}"
    } > "${PARAMS}"
    chmod 0600 "${PARAMS}"
    okk "ovpn-manager آماده شد."
}

# ── 8. npm install + init panel config ───────────────────────────────────────
setup_panel() {
    say "نصب وابستگی‌های Node ..."
    (cd "${OVPN_DIR}" && npm install --omit=dev --no-audit --no-fund >/dev/null 2>&1) || {
        err "npm install ناموفق بود"
        exit 1
    }
    say "ایجاد پیکربندی امنیتی پنل ..."
    mkdir -p "${CONFIG_DIR}"; chmod 0700 "${CONFIG_DIR}"
    (cd "${OVPN_DIR}" && OVPN_CONFIG_DIR="${CONFIG_DIR}" OVPN_PORT="${OVPN_PORT}" node scripts/init-config.js) \
        | tee /tmp/ovpn-init-config.out
    okk "پیکربندی پنل ایجاد شد."
}

# ── 9. cron backup for enforce (runs even if the panel is down) ───────────────
setup_cron() {
    say "نصب کرون enforce (پشتیبان) ..."
    tee /etc/cron.d/ovpn-enforce >/dev/null <<CRON
* * * * * root ${OVPN_DIR}/ovpn-manager.sh enforce >/dev/null 2>&1
CRON
    chmod 644 /etc/cron.d/ovpn-enforce
    systemctl enable --now cron >/dev/null 2>&1 || true
    okk "کرون enforce نصب شد."
}

# ── 10. systemd service for the panel ────────────────────────────────────────
setup_systemd() {
    say "نصب سرویس systemd ovpn.service ..."
    cat > /etc/systemd/system/ovpn.service <<EOF
[Unit]
Description=OpenVPN Panel + API (ovpn)
After=network.target openvpn-server@server.service
Wants=openvpn-server@server.service

[Service]
Type=simple
User=root
WorkingDirectory=${OVPN_DIR}
Environment=OVPN_PORT=${OVPN_PORT}
Environment=OVPN_CONFIG_DIR=${CONFIG_DIR}
Environment=OVPN_SCRIPT=${OVPN_DIR}/ovpn-manager.sh
Environment=OVPN_PARAMS=${MGR_DIR}/params
Environment=OVPN_CLIENTS_DIR=${MGR_DIR}/clients
ExecStart=$(command -v node) ${OVPN_DIR}/main.js
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable ovpn.service >/dev/null 2>&1
    okk "سرویس ovpn نصب شد."
}

# ── 11. (re)start everything + optional test client ──────────────────────────
finalize() {
    say "ری‌استارت OpenVPN برای اعمال hook ها ..."
    systemctl restart openvpn-server@server 2>/dev/null || true
    sleep 2
    say "شروع سرویس پنل ..."
    systemctl restart ovpn.service
    sleep 2

    if [[ -n "${TEST_CLIENT}" ]]; then
        say "ساخت کاربر تستی «${TEST_CLIENT}» ..."
        bash "${OVPN_DIR}/ovpn-manager.sh" add "${TEST_CLIENT}" >/dev/null 2>&1 || \
            warn "ساخت کاربر تستی ناموفق بود (ممکن است وجود داشته باشد)."
    fi

    # pull generated credentials
    local api_key admin_pass admin_path
    api_key="$(awk -F= '/^API_KEY=/{print $2}'     /tmp/ovpn-init-config.out | tail -1)"
    admin_pass="$(awk -F= '/^ADMIN_PASSWORD=/{print $2}' /tmp/ovpn-init-config.out | tail -1)"
    admin_path="$(awk -F= '/^ADMIN_PATH=/{print $2}'     /tmp/ovpn-init-config.out | tail -1)"

    echo ""
    okk "================ نصب کامل شد ================"
    echo ""
    printf "  آی‌پی سرور        : %s\n" "${SERVER_PUB_IP}"
    printf "  OpenVPN           : %s://%s:%s (UDP/TCP حسب پروتکل)\n" "${PROTOCOL}" "${SERVER_PUB_IP}" "${VPN_PORT}"
    printf "  پنل ادمین         : http://%s:%s/%s/\n" "${SERVER_PUB_IP}" "${OVPN_PORT}" "${admin_path}"
    printf "  رمز ادمین         : %s\n" "${admin_pass}"
    printf "  API Key           : %s\n" "${api_key}"
    echo ""
    warn "این اطلاعات را در جای امن ذخیره کنید."

    {
        echo "OVPN install info — $(date)"
        echo "----------------------------------"
        echo "Server IP    : ${SERVER_PUB_IP}"
        echo "OpenVPN      : ${PROTOCOL} ${SERVER_PUB_IP}:${VPN_PORT}"
        echo "Panel URL    : http://${SERVER_PUB_IP}:${OVPN_PORT}/${admin_path}/"
        echo "Admin Pass   : ${admin_pass}"
        echo "API Key      : ${api_key}"
        echo "Panel Port   : ${OVPN_PORT}"
        echo "Config Dir   : ${CONFIG_DIR}/ovpn.json"
        echo "Manager Dir  : ${MGR_DIR}"
    } > "${INFO_FILE}"
    okk "اطلاعات در ${INFO_FILE} ذخیره شد."
}

# ── run ──────────────────────────────────────────────────────────────────────
install_prereqs
deploy_files
gather_options
install_openvpn
patch_server_conf
setup_manager
setup_panel
setup_cron
setup_systemd
finalize
