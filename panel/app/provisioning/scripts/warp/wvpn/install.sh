#!/usr/bin/env bash
# Bootstrap: نصب کاملاً خودکار WVPN + WireGuard (بدون هیچ پرسشی)
#
# اگر کنار این فایل، فایل‌های پروژه (install_wire.sh و main.js) موجود باشند،
# از همان فایل‌های محلی نصب می‌شود (نیازی به اینترنت برای دانلود اسکریپت نیست).
# در غیر این صورت آخرین نسخه از گیت‌هاب دانلود می‌شود:
#
#   curl -fsSL https://raw.githubusercontent.com/lokidv/wvpn/main/install.sh | sudo bash

set -euo pipefail

# پیش‌فرض: نصب کاملاً خودکار و بدون پرسش (برای حالت تعاملی: WVPN_NONINTERACTIVE=0)
export WVPN_NONINTERACTIVE="${WVPN_NONINTERACTIVE:-1}"
export DEBIAN_FRONTEND=noninteractive

INSTALL_URL="${WVPN_INSTALL_URL:-https://raw.githubusercontent.com/lokidv/wvpn/main/install_wire.sh}"
TMP="/tmp/wvpn-install-wire.sh"
WVPN_DIR="/home/wvpn"

if [[ "${EUID}" -ne 0 ]]; then
  echo "لطفاً با root اجرا کنید: sudo ./install.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── حالت ۱: نصب از فایل‌های محلی (کلون شده از مخزن) ──────────────────────────
if [[ -f "${SCRIPT_DIR}/install_wire.sh" && -f "${SCRIPT_DIR}/main.js" ]]; then
  echo "نصب از فایل‌های محلی (${SCRIPT_DIR}) ..."
  if [[ "${SCRIPT_DIR}" != "${WVPN_DIR}" ]]; then
    mkdir -p "${WVPN_DIR}"
    # کپی فایل‌ها بدون node_modules و .git – نصب مجدد هم مشکلی ندارد
    (cd "${SCRIPT_DIR}" && tar --exclude='./node_modules' --exclude='./.git' -cf - .) \
      | (cd "${WVPN_DIR}" && tar -xf -)
  fi
  export WVPN_LOCAL_INSTALL=1
  exec bash "${WVPN_DIR}/install_wire.sh" "$@"
fi

# ── حالت ۲: دانلود از گیت‌هاب ────────────────────────────────────────────────
bootstrap_download_tools() {
  if command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1; then
    return 0
  fi
  echo "نصب curl برای دانلود اسکریپت ..."
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y ca-certificates curl gnupg
    return 0
  fi
  echo "curl/wget یا apt-get یافت نشد"
  exit 1
}

bootstrap_download_tools

echo "در حال دریافت install_wire.sh ..."
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$INSTALL_URL" -o "$TMP"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$TMP" "$INSTALL_URL"
else
  echo "curl یا wget نیاز است"
  exit 1
fi

exec bash "$TMP" "$@"
