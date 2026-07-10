#!/usr/bin/env bash
# نصب‌کننده ریشه – همه‌چیز را خودکار و بدون پرسش نصب می‌کند
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/wvpn/install.sh" "$@"
