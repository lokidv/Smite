#!/usr/bin/env bash
###############################################################################
# proxy-egress.sh — ترافیکِ کلاینت‌های WireGuard را از یک پروکسیِ بالادست
# (SOCKS5 یا HTTP-CONNECT، مثلاً یک residential proxy) خارج می‌کند تا IP خروجیِ
# کاربر = IP پروکسی شود (نه IP سرور).
#
# روش: روی همین سرورِ WireGuard یک redsocks (transparent redirector) بالا می‌آید.
# ترافیکِ TCP که از اینترفیس wg0 forward می‌شود، در جدولِ nat/PREROUTING به
# redsocks محلی REDIRECT می‌شود و redsocks آن را با احرازِ user/pass به پروکسیِ
# بالادست تحویل می‌دهد. UDP و DNS دست‌نخورده از NAT سرور عبور می‌کنند؛ برای اینکه
# مرورگرها QUIC (UDP/443) را دور نزنند و حتماً از مسیرِ TCP/پروکسی بروند، UDP/443
# مسدود می‌شود تا مرورگر به TCP برگردد.
#
# اجرا:
#   - در جریانِ نصبِ اصلی توسط install_wire.sh (اگر پروکسی پیکربندی شده باشد)، یا
#   - مستقل روی سروری که WireGuard از قبل نصب است:
#       sudo PROXY_IP=... PROXY_PORT=... PROXY_USER=... PROXY_PASS=... \
#            PROXY_TYPE=socks5 bash proxy-egress.sh
#   - یا با فایلِ /etc/wvpn-proxy.env (نمونه: proxy.env.example)
###############################################################################
set -euo pipefail

ENV_FILE="/etc/wvpn-proxy.env"
REDSOCKS_CONF="/etc/redsocks-wvpn.conf"
REDSOCKS_SERVICE="/etc/systemd/system/wvpn-redsocks.service"
RULES_SCRIPT="/usr/local/bin/wvpn-proxy-rules.sh"
REDSOCKS_LOCAL_PORT="${REDSOCKS_LOCAL_PORT:-12345}"

green() { printf '\e[32m%s\e[0m\n' "$1"; }
red()   { printf '\e[31m%s\e[0m\n' "$1"; }
info()  { printf '  %s\n' "$1"; }

[[ "${EUID}" -eq 0 ]] || { red "با root اجرا کنید (sudo)."; exit 1; }

# ── ۱) خواندن پارامترهای پروکسی (env قبلاً ست‌شده مقدم است، سپس فایل) ──────────
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  set -a; source "${ENV_FILE}"; set +a
fi

PROXY_IP="${PROXY_IP:-}"
PROXY_PORT="${PROXY_PORT:-}"
PROXY_USER="${PROXY_USER:-}"
PROXY_PASS="${PROXY_PASS:-}"
PROXY_TYPE="${PROXY_TYPE:-socks5}"          # socks5 | http-connect
WG_NIC="${WG_NIC:-${SERVER_WG_NIC:-wg0}}"

# نوعِ پروکسی را برای redsocks نرمال کن
case "${PROXY_TYPE,,}" in
  socks5|socks) PROXY_TYPE="socks5" ;;
  http|https|http-connect|connect) PROXY_TYPE="http-connect" ;;
  *) red "PROXY_TYPE نامعتبر: ${PROXY_TYPE} (باید socks5 یا http-connect باشد)"; exit 1 ;;
esac

if [[ -z "${PROXY_IP}" || -z "${PROXY_PORT}" ]]; then
  red "پارامترهای پروکسی ناقص است. PROXY_IP و PROXY_PORT الزامی‌اند."
  info "یا ${ENV_FILE} را بسازید یا متغیرها را در محیط ست کنید. نمونه: proxy.env.example"
  exit 2
fi

green "→ راه‌اندازیِ خروجیِ پروکسی: ${PROXY_TYPE} ${PROXY_IP}:${PROXY_PORT} روی اینترفیس ${WG_NIC}"

# ── ۲) نصب redsocks ─────────────────────────────────────────────────────────
if ! command -v redsocks >/dev/null 2>&1; then
  info "نصب redsocks ..."
  export DEBIAN_FRONTEND=noninteractive
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq || true
    apt-get install -y redsocks iptables
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y redsocks iptables || red "redsocks در مخزن نبود؛ دستی نصب کنید."
  elif command -v yum >/dev/null 2>&1; then
    yum install -y redsocks iptables || red "redsocks در مخزن نبود؛ دستی نصب کنید."
  else
    red "پکیج‌منیجرِ پشتیبانی‌شده یافت نشد."; exit 1
  fi
fi
# پکیجِ دبیان یک سرویسِ پیش‌فرضِ redsocks دارد که با کانفیگِ خودش بالا می‌آید؛
# خاموشش می‌کنیم تا با سرویسِ اختصاصیِ ما تداخل نکند.
systemctl disable --now redsocks 2>/dev/null || true

# ── ۳) کانفیگِ redsocks ─────────────────────────────────────────────────────
umask 077
cat > "${REDSOCKS_CONF}" <<EOF
base {
    log_debug = off;
    log_info = on;
    log = "syslog:daemon";
    daemon = off;
    redirector = iptables;
}
redsocks {
    local_ip = 127.0.0.1;
    local_port = ${REDSOCKS_LOCAL_PORT};
    ip = ${PROXY_IP};
    port = ${PROXY_PORT};
    type = ${PROXY_TYPE};
    login = "${PROXY_USER}";
    password = "${PROXY_PASS}";
}
EOF
chmod 600 "${REDSOCKS_CONF}"

# ── ۴) سرویسِ systemd اختصاصیِ redsocks ──────────────────────────────────────
REDSOCKS_BIN="$(command -v redsocks)"
cat > "${REDSOCKS_SERVICE}" <<EOF
[Unit]
Description=WVPN redsocks (upstream proxy egress)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${REDSOCKS_BIN} -c ${REDSOCKS_CONF}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# ── ۵) اسکریپتِ قوانینِ iptables (up/down) — از wg0 PostUp/PostDown صدا زده می‌شود ─
cat > "${RULES_SCRIPT}" <<'RULES'
#!/usr/bin/env bash
# قوانینِ redirect ترافیکِ TCPِ کلاینت‌های WireGuard به redsocks.
set -euo pipefail
ACTION="${1:-up}"
ENV_FILE="/etc/wvpn-proxy.env"
[[ -f "${ENV_FILE}" ]] && { set -a; source "${ENV_FILE}"; set +a; }
WG_NIC="${WG_NIC:-${SERVER_WG_NIC:-wg0}}"
RPORT="${REDSOCKS_LOCAL_PORT:-12345}"
PROXY_IP="${PROXY_IP:-}"

del_rules() {
  # حذفِ ایمن (خطاها را نادیده بگیر)
  iptables -t nat -D PREROUTING -i "${WG_NIC}" -p tcp -j REDSOCKS 2>/dev/null || true
  iptables -D FORWARD -i "${WG_NIC}" -p udp --dport 443 -j REJECT --reject-with icmp-port-unreachable 2>/dev/null || true
  iptables -t nat -F REDSOCKS 2>/dev/null || true
  iptables -t nat -X REDSOCKS 2>/dev/null || true
}

add_rules() {
  # مهم: ترافیکِ forwardشده را با DNAT به 127.0.0.1 می‌فرستیم (نه REDIRECT). REDIRECT
  # برای ترافیکِ forwardشده مقصد را به IP اینترفیسِ ورودی می‌برد نه لوپ‌بک، و چون
  # redsocks روی 127.0.0.1 گوش می‌دهد اتصال RST می‌شد. DNAT به 127.0.0.1 + فعال‌کردن
  # route_localnet مسیرِ درست است و redsocks را هم فقط روی لوپ‌بک نگه می‌دارد.
  sysctl -qw "net.ipv4.conf.${WG_NIC}.route_localnet=1" 2>/dev/null || true
  sysctl -qw "net.ipv4.conf.all.route_localnet=1" 2>/dev/null || true

  # زنجیرهٔ REDSOCKS را از نو بساز
  iptables -t nat -nL REDSOCKS >/dev/null 2>&1 || iptables -t nat -N REDSOCKS
  iptables -t nat -F REDSOCKS
  # مقصدهایی که نباید از پروکسی بروند (شبکه‌های خصوصی/رزروشده و خودِ پروکسی)
  for net in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 \
             172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4; do
    iptables -t nat -A REDSOCKS -d "${net}" -j RETURN
  done
  [[ -n "${PROXY_IP}" ]] && iptables -t nat -A REDSOCKS -d "${PROXY_IP}/32" -j RETURN
  # بقیهٔ TCP → redsocks محلی (DNAT به لوپ‌بک)
  iptables -t nat -A REDSOCKS -p tcp -j DNAT --to-destination "127.0.0.1:${RPORT}"

  # فقط ترافیکِ واردشونده از wg0 (یعنی از کلاینت‌ها) را به REDSOCKS بفرست
  iptables -t nat -C PREROUTING -i "${WG_NIC}" -p tcp -j REDSOCKS 2>/dev/null \
    || iptables -t nat -A PREROUTING -i "${WG_NIC}" -p tcp -j REDSOCKS

  # QUIC/HTTP3 (UDP 443) را ببند تا مرورگر به TCP برگردد و از پروکسی عبور کند
  iptables -C FORWARD -i "${WG_NIC}" -p udp --dport 443 -j REJECT --reject-with icmp-port-unreachable 2>/dev/null \
    || iptables -I FORWARD -i "${WG_NIC}" -p udp --dport 443 -j REJECT --reject-with icmp-port-unreachable
}

case "${ACTION}" in
  up)   del_rules; add_rules ;;
  down) del_rules ;;
  *) echo "usage: $0 up|down" >&2; exit 1 ;;
esac
RULES
chmod 755 "${RULES_SCRIPT}"

# ── ۶) راه‌اندازیِ سرویسِ redsocks ───────────────────────────────────────────
systemctl daemon-reload
systemctl enable --now wvpn-redsocks.service
sleep 1
if ! systemctl is-active --quiet wvpn-redsocks.service; then
  red "سرویسِ redsocks بالا نیامد. لاگ: journalctl -u wvpn-redsocks -n 50"
  exit 1
fi
green "✔ redsocks فعال شد (127.0.0.1:${REDSOCKS_LOCAL_PORT})"

# ── ۷) دائمی‌سازی روی wg0 (PostUp/PostDown) + اعمالِ زنده ─────────────────────
WG_CONF="/etc/wireguard/${WG_NIC}.conf"
if [[ -f "${WG_CONF}" ]]; then
  # PostUp: بعد از خطِ «-A POSTROUTING ... MASQUERADE» (تا بعد از ست‌شدنِ NAT اجرا شود)
  if ! grep -q "wvpn-proxy-rules.sh up" "${WG_CONF}"; then
    if grep -q -- '-A POSTROUTING .* MASQUERADE' "${WG_CONF}"; then
      sed -i "/-A POSTROUTING .* MASQUERADE/a PostUp   = ${RULES_SCRIPT} up" "${WG_CONF}"
    else
      sed -i "/^PrivateKey = /a PostUp   = ${RULES_SCRIPT} up" "${WG_CONF}"
    fi
  fi
  # PostDown: بعد از خطِ «-D POSTROUTING ... MASQUERADE» (انکرِ متفاوت از PostUp)
  if ! grep -q "wvpn-proxy-rules.sh down" "${WG_CONF}"; then
    if grep -q -- '-D POSTROUTING .* MASQUERADE' "${WG_CONF}"; then
      sed -i "/-D POSTROUTING .* MASQUERADE/a PostDown = ${RULES_SCRIPT} down" "${WG_CONF}"
    else
      printf 'PostDown = %s down\n' "${RULES_SCRIPT}" >> "${WG_CONF}"
    fi
  fi
  green "✔ قوانین پروکسی به ${WG_CONF} افزوده شد (پایدار پس از ریبوت)"
else
  red "هشدار: ${WG_CONF} یافت نشد؛ فقط قوانینِ زنده اعمال می‌شود (پس از ریبوت باید دوباره اجرا شود)."
fi

# اعمالِ زندهٔ قوانین همین حالا
"${RULES_SCRIPT}" up
green "✔ ترافیکِ TCPِ کلاینت‌های ${WG_NIC} اکنون از پروکسی ${PROXY_IP}:${PROXY_PORT} خارج می‌شود."

# ── ۸) تستِ خودکارِ IP خروجی از داخلِ redsocks (اختیاری) ─────────────────────
if command -v curl >/dev/null 2>&1; then
  info "تستِ IP خروجیِ پروکسی از روی سرور ..."
  case "${PROXY_TYPE}" in
    socks5)       CURL_PROXY="socks5h://${PROXY_USER}:${PROXY_PASS}@${PROXY_IP}:${PROXY_PORT}" ;;
    http-connect) CURL_PROXY="http://${PROXY_USER}:${PROXY_PASS}@${PROXY_IP}:${PROXY_PORT}" ;;
  esac
  OUT_IP="$(curl -fsS --max-time 20 -x "${CURL_PROXY}" https://api.ipify.org 2>/dev/null || echo '')"
  if [[ -n "${OUT_IP}" ]]; then
    green "✔ IP خروجیِ پروکسی: ${OUT_IP}"
  else
    red "هشدار: تستِ مستقیمِ پروکسی ناموفق بود (پورت/نوع/احراز را بررسی کنید). قوانین اعمال شد."
  fi
fi
