#!/usr/bin/env bash
# install_wire.sh – Interactive one-command installer: WireGuard + Node.js 20 + wvpn API
# No Docker. Tested on Ubuntu 20.04+ / Debian 11+
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/lokidv/wvpn/main/install_wire.sh -o install_wire.sh \
#     && chmod +x install_wire.sh && sudo ./install_wire.sh

set -euo pipefail

LOG="/var/log/wvpn_install.log"
CREDENTIALS_FILE="/root/wvpn-install-info.txt"
WVPN_DIR="/home/wvpn"
WVPN_REPO="${WVPN_REPO:-https://github.com/lokidv/wvpn.git}"

# ── UI helpers ────────────────────────────────────────────────────────────────
green()  { echo -e "\e[32m$1\e[0m"; }
yellow() { echo -e "\e[33m$1\e[0m"; }
red()    { echo -e "\e[31m$1\e[0m"; }
bold()   { echo -e "\e[1m$1\e[0m"; }
step()   { printf "%s ... " "$1" | tee -a "$LOG"; }
ok()     { green "✅" | tee -a "$LOG"; }
fail()   { red "❌ $1" | tee -a "$LOG"; exit 1; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    red "این اسکریپت باید با root اجرا شود: sudo ./install_wire.sh"
    exit 1
  fi
}

check_os() {
  if [[ ! -f /etc/os-release ]]; then
    fail "سیستم‌عامل پشتیبانی نمی‌شود"
  fi
  # shellcheck source=/dev/null
  source /etc/os-release
  case "${ID}" in
    ubuntu|debian) ;;
    *)
      fail "فقط Ubuntu و Debian پشتیبانی می‌شوند (فعلی: ${ID})"
      ;;
  esac
}

REINSTALL_MODE=false
IP_FORWARD_CONF="/etc/sysctl.d/99-wvpn-ipforward.conf"

enable_ip_forward_persistent() {
  step "فعال‌سازی ip_forward (دائمی)"
  mkdir -p /etc/sysctl.d
  cat >"${IP_FORWARD_CONF}" <<'EOF'
# WVPN / WireGuard – IPv4 forwarding (persistent across reboots)
net.ipv4.ip_forward=1
EOF
  chmod 644 "${IP_FORWARD_CONF}"
  sysctl -w net.ipv4.ip_forward=1 >>"$LOG" 2>&1 || true
  sysctl --system >>"$LOG" 2>&1 && ok || fail "sysctl"
}

ensure_wg_postup_ip_forward() {
  local conf="/etc/wireguard/${SERVER_WG_NIC}.conf"
  [[ -f "${conf}" ]] || return 0
  if grep -q 'sysctl.*net\.ipv4\.ip_forward' "${conf}" 2>/dev/null; then
    return 0
  fi
  sed -i '/^PrivateKey = /a PostUp   = sysctl -w net.ipv4.ip_forward=1' "${conf}"
}

already_installed() {
  [[ -f /etc/wireguard/params && -f /etc/wvpn/wvpn.json && -d "${WVPN_DIR}" ]]
}

load_existing_params() {
  # shellcheck source=/dev/null
  source /etc/wireguard/params
  WVPN_PORT="${WVPN_PORT:-4000}"
  DEFAULT_DATA_LIMIT_GB="${DEFAULT_DATA_LIMIT_GB:-10}"
}

detect_public_ip() {
  ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1
}

detect_public_nic() {
  ip -4 route ls 2>/dev/null | awk '/default/ {print $5; exit}'
}

suggest_wireguard_port() {
  shuf -i1500-10000 -n1
}

apply_default_settings() {
  SERVER_PUB_IP="${SERVER_PUB_IP:-$(detect_public_ip)}"
  SERVER_PUB_NIC="${SERVER_PUB_NIC:-$(detect_public_nic)}"
  SERVER_WG_NIC="${SERVER_WG_NIC:-wg0}"
  SERVER_WG_IPV4="${SERVER_WG_IPV4:-10.66.66.1}"
  CLIENT_DNS_1="${CLIENT_DNS_1:-1.1.1.1}"
  CLIENT_DNS_2="${CLIENT_DNS_2:-1.0.0.1}"
  ALLOWED_IPS="${ALLOWED_IPS:-0.0.0.0/0}"
  DEFAULT_DATA_LIMIT_GB="${DEFAULT_DATA_LIMIT_GB:-10}"
  WVPN_PORT="${WVPN_PORT:-4000}"
  CREATE_TEST_CLIENT="${CREATE_TEST_CLIENT:-N}"
  TEST_CLIENT_NAME="${TEST_CLIENT_NAME:-test}"
  # پورت فقط در حالت غیرتعاملی یا بعد از پرسش از کاربر تنظیم می‌شود
  if [[ "${WVPN_NONINTERACTIVE:-}" == "1" ]]; then
    SERVER_PORT="${SERVER_PORT:-$(suggest_wireguard_port)}"
  fi
}

print_settings_summary() {
  yellow "خلاصه تنظیمات:"
  echo "  IP عمومی:        ${SERVER_PUB_IP}"
  echo "  اینترفیس:        ${SERVER_PUB_NIC}"
  echo "  WireGuard:       ${SERVER_WG_NIC} @ ${SERVER_WG_IPV4}"
  echo "  پورت UDP:        ${SERVER_PORT}"
  echo "  DNS:             ${CLIENT_DNS_1}, ${CLIENT_DNS_2}"
  echo "  AllowedIPs:      ${ALLOWED_IPS}"
  echo "  حجم پیش‌فرض:     ${DEFAULT_DATA_LIMIT_GB} GB"
  echo "  پورت پنل/API:    ${WVPN_PORT}"
  [[ "${CREATE_TEST_CLIENT}" =~ ^[Yy]$ ]] && echo "  کاربر تستی:      ${TEST_CLIENT_NAME}"
  echo ""
}

ask_questions() {
  bold "── مرحله ۲: تنظیمات ──"
  echo ""
  bold "════════════════════════════════════════════════════════"
  bold "  WireGuard + پنل مدیریت WVPN"
  bold "════════════════════════════════════════════════════════"
  echo ""

  apply_default_settings

  if [[ "${WVPN_NONINTERACTIVE:-}" == "1" ]]; then
    echo "حالت نصب خودکار (بدون پرسش)"
    print_settings_summary
    return 0
  fi

  echo "تنظیمات را وارد کنید (Enter = مقدار پیش‌فرض)"
  echo ""

  local detected_ip detected_nic suggested_port port_input
  detected_ip="${SERVER_PUB_IP}"
  detected_nic="${SERVER_PUB_NIC}"

  until [[ "${SERVER_PUB_IP}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; do
    read -rp "آدرس IPv4 عمومی سرور [${detected_ip}]: " SERVER_PUB_IP
    SERVER_PUB_IP="${SERVER_PUB_IP:-$detected_ip}"
  done

  until [[ "${SERVER_PUB_NIC}" =~ ^[a-zA-Z0-9_.-]+$ ]]; do
    read -rp "اینترفیس شبکه عمومی [${detected_nic}]: " SERVER_PUB_NIC
    SERVER_PUB_NIC="${SERVER_PUB_NIC:-$detected_nic}"
  done

  until [[ "${SERVER_WG_NIC}" =~ ^[a-zA-Z0-9_]+$ && ${#SERVER_WG_NIC} -lt 16 ]]; do
    read -rp "نام اینترفیس WireGuard [wg0]: " SERVER_WG_NIC
    SERVER_WG_NIC="${SERVER_WG_NIC:-wg0}"
  done

  until [[ "${SERVER_WG_IPV4}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; do
    read -rp "IP داخلی WireGuard سرور [10.66.66.1]: " SERVER_WG_IPV4
    SERVER_WG_IPV4="${SERVER_WG_IPV4:-10.66.66.1}"
  done

  if [[ -n "${SERVER_PORT:-}" ]]; then
    suggested_port="${SERVER_PORT}"
    echo "پورت UDP WireGuard (پورت فعلی پیشنهاد شده – Enter برای نگه‌داشتن یا عدد جدید وارد کنید)"
  else
    suggested_port="$(suggest_wireguard_port)"
    echo "پورت UDP WireGuard (پیشنهاد تصادفی – Enter برای قبول یا عدد دلخواه وارد کنید)"
  fi
  SERVER_PORT=""
  until [[ "${SERVER_PORT}" =~ ^[0-9]+$ ]] && (( SERVER_PORT >= 1 && SERVER_PORT <= 65535 )); do
    read -rp "پورت UDP WireGuard [${suggested_port}]: " port_input
    SERVER_PORT="${port_input:-$suggested_port}"
    if [[ ! "${SERVER_PORT}" =~ ^[0-9]+$ ]] || (( SERVER_PORT < 1 || SERVER_PORT > 65535 )); then
      red "پورت نامعتبر است. عددی بین 1 تا 65535 وارد کنید."
      SERVER_PORT=""
      suggested_port="$(suggest_wireguard_port)"
    fi
  done

  until [[ "${CLIENT_DNS_1}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; do
    read -rp "DNS اول کلاینت‌ها [1.1.1.1]: " CLIENT_DNS_1
    CLIENT_DNS_1="${CLIENT_DNS_1:-1.1.1.1}"
  done

  until [[ "${CLIENT_DNS_2}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; do
    read -rp "DNS دوم کلاینت‌ها [1.0.0.1]: " CLIENT_DNS_2
    CLIENT_DNS_2="${CLIENT_DNS_2:-1.0.0.1}"
  done

  read -rp "AllowedIPs کلاینت‌ها [0.0.0.0/0]: " ALLOWED_IPS
  ALLOWED_IPS="${ALLOWED_IPS:-0.0.0.0/0}"

  until [[ "${DEFAULT_DATA_LIMIT_GB}" =~ ^[0-9]+([.][0-9]+)?$ ]] && awk -v gb="${DEFAULT_DATA_LIMIT_GB}" 'BEGIN { exit !(gb > 0) }'; do
    read -rp "حجم پیش‌فرض هر کاربر (GB) [10]: " DEFAULT_DATA_LIMIT_GB
    DEFAULT_DATA_LIMIT_GB="${DEFAULT_DATA_LIMIT_GB:-10}"
  done

  until [[ "${WVPN_PORT}" =~ ^[0-9]+$ ]] && (( WVPN_PORT >= 1 && WVPN_PORT <= 65535 )); do
    read -rp "پورت پنل/API مدیریت [4000]: " WVPN_PORT
    WVPN_PORT="${WVPN_PORT:-4000}"
  done

  read -rp "ساخت کاربر تستی؟ (y/N): " CREATE_TEST_CLIENT
  CREATE_TEST_CLIENT="${CREATE_TEST_CLIENT:-N}"
  if [[ "${CREATE_TEST_CLIENT}" =~ ^[Yy]$ ]]; then
    read -rp "نام کاربر تستی [test]: " TEST_CLIENT_NAME
    TEST_CLIENT_NAME="${TEST_CLIENT_NAME:-test}"
  fi

  echo ""
  print_settings_summary
  read -rp "ادامه نصب؟ (Y/n): " CONFIRM
  CONFIRM="${CONFIRM:-Y}"
  [[ "${CONFIRM}" =~ ^[Nn]$ ]] && { yellow "نصب لغو شد."; exit 0; }
  echo ""
}

capture_init_config() {
  local output line
  output="$(WVPN_PORT="${WVPN_PORT}" node "${WVPN_DIR}/scripts/init-config.js" 2>&1 | tee -a "$LOG")"
  API_KEY="$(echo "$output" | awk -F= '/^API_KEY=/{print $2}')"
  ADMIN_PASSWORD="$(echo "$output" | awk -F= '/^ADMIN_PASSWORD=/{print $2}')"
  ADMIN_PATH="$(echo "$output" | awk -F= '/^ADMIN_PATH=/{print $2}')"
  if [[ -z "${API_KEY}" && -f /etc/wvpn/wvpn.json ]]; then
    API_KEY="$(node -e "const c=require('/etc/wvpn/wvpn.json'); console.log(c.apiKey||'')")"
  fi
  if [[ -z "${ADMIN_PATH}" && -f /etc/wvpn/wvpn.json ]]; then
    ADMIN_PATH="$(node -e "const c=require('/etc/wvpn/wvpn.json'); console.log(c.adminPath||'')")"
  fi
  if [[ -z "${ADMIN_PASSWORD}" && -f "${CREDENTIALS_FILE}" ]]; then
    ADMIN_PASSWORD="$(awk -F': *' '/^رمز عبور:/{print $2}' "${CREDENTIALS_FILE}" | head -1)"
  fi
  if [[ -z "${ADMIN_PASSWORD}" ]]; then
    ADMIN_PASSWORD="(رمز قبلی – فایل ${CREDENTIALS_FILE} را ببینید)"
  fi
  if [[ -z "${ADMIN_PATH}" ]]; then
    ADMIN_PATH="(مسیر پنل در /etc/wvpn/wvpn.json)"
  fi
}

install_prerequisites() {
  bold "── مرحله ۱: نصب پیش‌نیازها ──"
  echo ""

  step "apt-get update"
  apt-get update >>"$LOG" 2>&1 && ok || fail "apt-get update"

  step "نصب ابزارهای پایه (ca-certificates curl gnupg git ...)"
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    ca-certificates curl gnupg git cron nano jq iproute2 \
    build-essential python3 \
    >>"$LOG" 2>&1 && ok || fail "نصب ابزارهای پایه"

  if command -v node >/dev/null 2>&1 && node -v | grep -qE 'v(18|20|22)\.'; then
    step "Node.js $(node -v) از قبل نصب است"
    ok
  else
    step "افزودن کلید NodeSource"
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
      | gpg --dearmor --yes --batch -o /etc/apt/keyrings/nodesource.gpg >>"$LOG" 2>&1 && ok || fail "NodeSource GPG key"

    step "افزودن مخزن Node.js 20"
    NODE_MAJOR=20
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
      > /etc/apt/sources.list.d/nodesource.list
    ok

    step "apt-get update (NodeSource)"
    apt-get update >>"$LOG" 2>&1 && ok || fail "apt-get update"

    step "نصب Node.js ${NODE_MAJOR}"
    DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs >>"$LOG" 2>&1 && ok || fail "نصب nodejs"
  fi

  step "نصب WireGuard و وابستگی‌ها"
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    wireguard wireguard-tools iptables qrencode \
    >>"$LOG" 2>&1 && ok || fail "نصب wireguard"

  # resolvconf اختیاری – روی بعضی سیستم‌ها وجود ندارد
  step "نصب resolvconf (در صورت موجود بودن)"
  if apt-cache show resolvconf >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y resolvconf >>"$LOG" 2>&1 && ok || yellow "⚠️  resolvconf نصب نشد – ادامه"
  else
    yellow "رد شد (در این سیستم موجود نیست)"
  fi

  step "بررسی نسخه‌ها"
  echo "  node: $(node -v 2>/dev/null || echo '?')" | tee -a "$LOG"
  echo "  npm:  $(npm -v 2>/dev/null || echo '?')" | tee -a "$LOG"
  echo "  wg:   $(wg --version 2>/dev/null | head -1 || echo '?')" | tee -a "$LOG"
  ok
  echo ""
}

install_wvpn_app() {
  bold "── مرحله ۳: نصب wvpn ──"
  echo ""

  step "دریافت wvpn"
  if [[ "${WVPN_LOCAL_INSTALL:-}" == "1" ]]; then
    [[ -f "${WVPN_DIR}/main.js" ]] || fail "فایل‌های محلی در ${WVPN_DIR} یافت نشد"
    ok
  elif [[ -d "${WVPN_DIR}/.git" ]]; then
    git -C "${WVPN_DIR}" pull --ff-only >>"$LOG" 2>&1 && ok || fail "git pull"
  else
    rm -rf "${WVPN_DIR}"
    git clone "${WVPN_REPO}" "${WVPN_DIR}" >>"$LOG" 2>&1 && ok || fail "git clone"
  fi

  step "npm install"
  cd "${WVPN_DIR}"
  npm install --omit=dev >>"$LOG" 2>&1 && ok || fail "npm install"

  step "آماده‌سازی wireguard-install.sh"
  chmod +x "${WVPN_DIR}/wireguard-install.sh" && ok

  step "ساخت کلیدهای امنیتی"
  capture_init_config
  chmod 700 /etc/wvpn 2>/dev/null || true
  chmod 600 /etc/wvpn/wvpn.json 2>/dev/null || true
  ok
}

install_wireguard() {
  bold "── مرحله ۴: پیکربندی WireGuard ──"
  echo ""

  mkdir -p /etc/wireguard
  enable_ip_forward_persistent

  if [[ "${REINSTALL_MODE}" == true && -f /etc/wireguard/params ]]; then
    step "بروزرسانی تنظیمات WireGuard"
    load_existing_params
    tee /etc/wireguard/params >/dev/null <<EOF
SERVER_PUB_IP=${SERVER_PUB_IP}
SERVER_PUB_NIC=${SERVER_PUB_NIC}
SERVER_WG_NIC=${SERVER_WG_NIC}
SERVER_WG_IPV4=${SERVER_WG_IPV4}
SERVER_PORT=${SERVER_PORT}
SERVER_PRIV_KEY=${SERVER_PRIV_KEY}
SERVER_PUB_KEY=${SERVER_PUB_KEY}
CLIENT_DNS_1=${CLIENT_DNS_1}
CLIENT_DNS_2=${CLIENT_DNS_2}
CLIENT_ENDPOINT=${CLIENT_ENDPOINT:-}
CLIENT_MTU=${CLIENT_MTU:-}
ALLOWED_IPS=${ALLOWED_IPS}
DEFAULT_DATA_LIMIT_GB=${DEFAULT_DATA_LIMIT_GB}
WVPN_PORT=${WVPN_PORT}
EOF
    chmod 600 /etc/wireguard/params
    [[ -f /etc/wireguard/clients.json ]] || echo '{"version":1,"clients":{}}' > /etc/wireguard/clients.json
    chmod 600 /etc/wireguard/clients.json
    ok
    ensure_wg_postup_ip_forward
    step "راه‌اندازی WireGuard"
    systemctl enable "wg-quick@${SERVER_WG_NIC}" >>"$LOG" 2>&1 || true
    systemctl restart "wg-quick@${SERVER_WG_NIC}" >>"$LOG" 2>&1 && ok || fail "wg-quick"
    return
  fi

  step "تولید کلید سرور"
  SERVER_PRIV_KEY="$(wg genkey)"
  SERVER_PUB_KEY="$(echo "$SERVER_PRIV_KEY" | wg pubkey)"
  ok

  step "ذخیره تنظیمات WireGuard"
  tee /etc/wireguard/params >/dev/null <<EOF
SERVER_PUB_IP=${SERVER_PUB_IP}
SERVER_PUB_NIC=${SERVER_PUB_NIC}
SERVER_WG_NIC=${SERVER_WG_NIC}
SERVER_WG_IPV4=${SERVER_WG_IPV4}
SERVER_PORT=${SERVER_PORT}
SERVER_PRIV_KEY=${SERVER_PRIV_KEY}
SERVER_PUB_KEY=${SERVER_PUB_KEY}
CLIENT_DNS_1=${CLIENT_DNS_1}
CLIENT_DNS_2=${CLIENT_DNS_2}
CLIENT_ENDPOINT=${CLIENT_ENDPOINT:-}
CLIENT_MTU=${CLIENT_MTU:-}
ALLOWED_IPS=${ALLOWED_IPS}
DEFAULT_DATA_LIMIT_GB=${DEFAULT_DATA_LIMIT_GB}
WVPN_PORT=${WVPN_PORT}
EOF
  chmod 600 /etc/wireguard/params
  ok

  step "ایجاد clients.json"
  echo '{"version":1,"clients":{}}' > /etc/wireguard/clients.json
  chmod 600 /etc/wireguard/clients.json
  ok

  step "ایجاد کانفیگ سرور"
  tee "/etc/wireguard/${SERVER_WG_NIC}.conf" >/dev/null <<EOF
[Interface]
Address    = ${SERVER_WG_IPV4}/24
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
  chmod 600 "/etc/wireguard/${SERVER_WG_NIC}.conf"
  ok

  ensure_wg_postup_ip_forward
  step "راه‌اندازی WireGuard"
  systemctl enable "wg-quick@${SERVER_WG_NIC}" >>"$LOG" 2>&1 || true
  systemctl restart "wg-quick@${SERVER_WG_NIC}" >>"$LOG" 2>&1 && ok || fail "wg-quick"
}

create_test_client() {
  [[ ! "${CREATE_TEST_CLIENT}" =~ ^[Yy]$ ]] && return 0

  step "ساخت کاربر تستی ${TEST_CLIENT_NAME}"
  local result conf_path
  result="$("${WVPN_DIR}/wireguard-install.sh" add "${TEST_CLIENT_NAME}" 2>>"$LOG")"
  if echo "$result" | jq -e '.success == true' >/dev/null 2>&1; then
    conf_path="$(echo "$result" | jq -r '.confPath // empty')"
    TEST_CLIENT_CONF="${conf_path}"
    ok
  else
    yellow "⚠️  ساخت کاربر تستی ناموفق بود (ادامه می‌دهیم)"
    echo "$result" >>"$LOG"
  fi
}

install_services() {
  step "سرویس wvpn"
  tee /etc/systemd/system/wvpn.service >/dev/null <<UNIT
[Unit]
Description=WVPN WireGuard Management API
After=network.target wg-quick@${SERVER_WG_NIC}.service
Wants=wg-quick@${SERVER_WG_NIC}.service

[Service]
Type=simple
User=root
Environment=WVPN_PORT=${WVPN_PORT}
Environment=WVPN_SCRIPT=${WVPN_DIR}/wireguard-install.sh
WorkingDirectory=${WVPN_DIR}
ExecStart=/usr/bin/node ${WVPN_DIR}/main.js
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable wvpn.service >>"$LOG" 2>&1 || true
  systemctl restart wvpn.service >>"$LOG" 2>&1 && ok || fail "wvpn.service"

  step "کرون enforce حجم"
  tee /etc/cron.d/wvpn-enforce >/dev/null <<CRON
* * * * * root ${WVPN_DIR}/wireguard-install.sh enforce >/dev/null 2>&1
CRON
  chmod 644 /etc/cron.d/wvpn-enforce
  systemctl enable --now cron >>"$LOG" 2>&1 || true
  ok

  step "logrotate برای vpn.log"
  tee /etc/logrotate.d/wvpn >/dev/null <<LR
${WVPN_DIR}/vpn.log {
    size 20M
    rotate 3
    missingok
    notifempty
    copytruncate
    compress
}
LR
  chmod 644 /etc/logrotate.d/wvpn
  ok
}

verify_installation() {
  step "بررسی WireGuard"
  systemctl is-active --quiet "wg-quick@${SERVER_WG_NIC}" && ok || fail "WireGuard فعال نیست"

  step "بررسی API"
  sleep 2
  if [[ -z "${ADMIN_PATH:-}" ]]; then
    ADMIN_PATH="$(node -e "const c=require('/etc/wvpn/wvpn.json'); console.log(c.adminPath||'')")"
  fi
  if curl -fsS -o /dev/null "http://127.0.0.1:${WVPN_PORT}/${ADMIN_PATH}/" 2>>"$LOG"; then
    ok
  else
    yellow "⚠️  پنل هنوز پاسخ نمی‌دهد – چند ثانیه بعد دوباره امتحان کنید"
  fi
  step "بررسی مسیر /admin (باید 404 باشد)"
  local admin_code
  admin_code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${WVPN_PORT}/admin/" 2>>"$LOG" || echo 000)"
  if [[ "${admin_code}" == "404" ]]; then
    ok
  else
    yellow "⚠️  /admin هنوز در دسترس است (کد ${admin_code})"
  fi
}

save_and_print_summary() {
  local panel_url api_base wg_status test_line
  panel_url="http://${SERVER_PUB_IP}:${WVPN_PORT}/${ADMIN_PATH}/"
  api_base="http://${SERVER_PUB_IP}:${WVPN_PORT}/"
  wg_status="$(systemctl is-active "wg-quick@${SERVER_WG_NIC}" 2>/dev/null || echo unknown)"
  test_line=""
  [[ -n "${TEST_CLIENT_CONF:-}" ]] && test_line="فایل کانفیگ تست: ${TEST_CLIENT_CONF}"

  tee "$CREDENTIALS_FILE" >/dev/null <<EOF
WVPN / WireGuard – اطلاعات نصب
تاریخ: $(date -Iseconds)

── WireGuard ──
IP عمومی:       ${SERVER_PUB_IP}
پورت UDP:       ${SERVER_PORT}
اینترفیس:       ${SERVER_WG_NIC}
شبکه داخلی:     ${SERVER_WG_IPV4}/24
وضعیت:          ${wg_status}
حجم پیش‌فرض:    ${DEFAULT_DATA_LIMIT_GB} GB

── پنل مدیریت (مسیر مخفی) ──
آدرس:           ${panel_url}
مسیر مخفی:      ${ADMIN_PATH}
رمز عبور:       ${ADMIN_PASSWORD}

── API (اتصال سایت) ──
Base URL:       ${api_base}
API Key:        ${API_KEY}

── نمونه درخواست‌ها ──
ساخت کاربر:     GET ${api_base}create?publicKey=USERNAME&apiKey=${API_KEY}&dataLimitGB=20
تمدید حجم:      GET ${api_base}update?publicKey=USERNAME&apiKey=${API_KEY}&dataLimitGB=15
(setDataLimitGB فقط برای تنظیم مطلق سقف است، نه خرید تمدید)
لیست کاربران:   GET ${api_base}list?apiKey=${API_KEY}
فیلتر لیست:     GET ${api_base}list?apiKey=${API_KEY}&status=active&q=alice&expiry=expiring&sort=usedBytes&order=desc
غیرفعال:        GET ${api_base}disable?publicKey=USERNAME&apiKey=${API_KEY}
فعال:           GET ${api_base}enable?publicKey=USERNAME&apiKey=${API_KEY}
حذف:            GET ${api_base}remove?publicKey=USERNAME&apiKey=${API_KEY}

${test_line}

لاگ نصب:        ${LOG}
EOF
  chmod 600 "$CREDENTIALS_FILE"

  echo ""
  green "════════════════════════════════════════════════════════"
  green "  ✅ نصب با موفقیت انجام شد"
  green "════════════════════════════════════════════════════════"
  echo ""
  bold "WireGuard"
  echo "  IP عمومی:     ${SERVER_PUB_IP}"
  echo "  پورت UDP:     ${SERVER_PORT}"
  echo "  وضعیت:        ${wg_status}"
  echo "  حجم پیش‌فرض:  ${DEFAULT_DATA_LIMIT_GB} GB"
  echo ""
  bold "پنل مدیریت (مسیر مخفی – /admin غیرفعال است)"
  echo "  آدرس:         ${panel_url}"
  echo "  مسیر مخفی:    ${ADMIN_PATH}"
  echo "  رمز عبور:     ${ADMIN_PASSWORD}"
  echo ""
  bold "API (برای اتصال citynew / سایت)"
  echo "  Base URL:     ${api_base}"
  echo "  API Key:      ${API_KEY}"
  echo ""
  yellow "⚠️  این اطلاعات را امن نگه دارید!"
  echo "  ذخیره شده در: ${CREDENTIALS_FILE}"
  echo "  لاگ نصب:      ${LOG}"
  echo ""
  yellow "پورت ${SERVER_PORT}/udp و ${WVPN_PORT}/tcp را در فایروال باز کنید."
  echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
require_root
touch "$LOG"

if already_installed; then
  if [[ "${WVPN_FORCE_REINSTALL:-}" == "1" ]]; then
    yellow "حذف نصب قبلی (WVPN_FORCE_REINSTALL=1)"
    systemctl stop wvpn.service 2>/dev/null || true
    systemctl stop "wg-quick@${SERVER_WG_NIC:-wg0}" 2>/dev/null || true
    rm -rf /etc/wireguard /etc/wvpn /etc/cron.d/wvpn-enforce
    rm -f /etc/systemd/system/wvpn.service
    systemctl daemon-reload 2>/dev/null || true
  elif [[ "${WVPN_NONINTERACTIVE:-}" == "1" ]]; then
    REINSTALL_MODE=true
    load_existing_params
    yellow "نصب قبلی یافت شد – بروزرسانی خودکار"
  else
    yellow "نصب قبلی یافت شد (/etc/wireguard/params + /etc/wvpn/wvpn.json)"
    read -rp "ادامه و بروزرسانی؟ (y/N): " REINSTALL
    [[ ! "${REINSTALL}" =~ ^[Yy]$ ]] && { echo "خروج."; exit 0; }
    REINSTALL_MODE=true
    load_existing_params
    yellow "تنظیمات فعلی بارگذاری شد. فقط مقادیر قابل تغییر پرسیده می‌شوند."
  fi
fi

# ── خروجیِ پروکسی (نسخه‌ی proxy): اگر پیکربندی شده باشد، ترافیکِ کلاینت‌ها را از
# یک پروکسیِ بالادست (SOCKS5/HTTP) خارج می‌کند تا IP خروجی = IP پروکسی شود.
# فعال‌سازی: وجودِ /etc/wvpn-proxy.env یا ست‌بودنِ PROXY_IP و PROXY_PORT در محیط.
setup_proxy_egress() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local egress="${script_dir}/proxy-egress.sh"

  if [[ ! -f "/etc/wvpn-proxy.env" && ( -z "${PROXY_IP:-}" || -z "${PROXY_PORT:-}" ) ]]; then
    return 0   # پروکسی پیکربندی نشده → رد شو (نصبِ عادی)
  fi
  if [[ ! -f "${egress}" ]]; then
    yellow "proxy-egress.sh یافت نشد (${egress})؛ مرحلهٔ پروکسی رد شد."
    return 0
  fi

  bold "── مرحله: خروجیِ ترافیک از پروکسیِ بالادست ──"
  # SERVER_WG_NIC را برای اسکریپت هم صادر کن (اگر ست باشد)
  WG_NIC="${SERVER_WG_NIC:-wg0}" bash "${egress}" || yellow "راه‌اندازیِ پروکسی با خطا مواجه شد (بررسی کنید)."
}

check_os
install_prerequisites
ask_questions

install_wvpn_app
install_wireguard
create_test_client
setup_proxy_egress
install_services
verify_installation
save_and_print_summary
