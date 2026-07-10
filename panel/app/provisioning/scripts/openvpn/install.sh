#!/usr/bin/env bash
# =============================================================================
# Root installer — fully automatic OpenVPN panel setup (no questions asked).
# Mirrors the wginstaller root installer. Run as root:
#
#   sudo ./install.sh
#
# Behaviour:
#  - if the project files live next to this script, they are installed locally
#    (no internet needed for the panel itself; only apt/openvpn/node downloads).
#  - everything is non-interactive by default. To answer questions interactively:
#       sudo OVPN_NONINTERACTIVE=0 ./install.sh
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/ovpn/install.sh" "$@"
