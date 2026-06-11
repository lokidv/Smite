#!/bin/bash
# Smite Panel - Offline Native Installer (Docker-free: systemd + Python venv)
#
# Designed for Iran servers with no access to Docker, GitHub, or international
# internet. Everything is installed from a self-contained offline bundle built
# by scripts/build-offline-bundle.sh on a machine that has internet access.
#
# Run this from inside the extracted bundle:  sudo bash scripts/install-native.sh
#
# Non-interactive mode (for self-update / automation):
#   sudo bash scripts/install-native.sh --yes
#   (or SMITE_NONINTERACTIVE=1) - keeps the existing /opt/smite/.env untouched
#   and uses PANEL_PORT from the environment (default 8000) on first install.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

progress() { echo -e "${GREEN}OK${NC} $1"; }
warn() { echo -e "${YELLOW}!${NC} $1"; }

NONINTERACTIVE="${SMITE_NONINTERACTIVE:-0}"
for arg in "$@"; do
    case "$arg" in
        --yes|-y|--non-interactive) NONINTERACTIVE=1 ;;
    esac
done

echo "=== Smite Panel Offline Native Installer (no Docker) ==="
echo ""

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

# Resolve bundle root (parent of the directory holding this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="/opt/smite"

if [ ! -d "$BUNDLE_DIR/panel" ] || [ ! -d "$BUNDLE_DIR/wheels/panel" ]; then
    echo -e "${RED}Error: this script must be run from inside an offline bundle.${NC}"
    echo "Expected $BUNDLE_DIR/panel and $BUNDLE_DIR/wheels/panel to exist."
    echo "Build a bundle with scripts/build-offline-bundle.sh first, then extract and run."
    exit 1
fi

# --- Architecture sanity check ---
ARCH_RAW="$(uname -m)"
case "$ARCH_RAW" in
    x86_64|amd64) ARCH="amd64" ;;
    aarch64|arm64) ARCH="arm64" ;;
    *) ARCH="amd64" ;;
esac
if [ -f "$BUNDLE_DIR/ARCH" ]; then
    BUNDLE_ARCH="$(cat "$BUNDLE_DIR/ARCH" | tr -d '[:space:]')"
    if [ -n "$BUNDLE_ARCH" ] && [ "$BUNDLE_ARCH" != "$ARCH" ]; then
        warn "Bundle architecture ($BUNDLE_ARCH) differs from this system ($ARCH). Binaries/wheels may not run."
    fi
fi

# --- Local prerequisites (no internet; uses local apt cache/mirror only if missing) ---
need_pkgs=""
command -v python3 >/dev/null 2>&1 || need_pkgs="$need_pkgs python3"
python3 -m venv --help >/dev/null 2>&1 || need_pkgs="$need_pkgs python3-venv"
command -v openssl >/dev/null 2>&1 || need_pkgs="$need_pkgs openssl"
if [ -n "$need_pkgs" ]; then
    warn "Missing prerequisites:$need_pkgs - attempting local install"
    apt-get install -y $need_pkgs 2>/dev/null || {
        echo -e "${RED}Could not install:$need_pkgs${NC}"
        echo "Install these from your local OS repository/mirror and re-run."
        exit 1
    }
fi
progress "Prerequisites present"

# --- Configuration ---
echo ""
if [ "$NONINTERACTIVE" = "1" ]; then
    PANEL_PORT=${PANEL_PORT:-8000}
    progress "Non-interactive mode: panel port $PANEL_PORT"
else
    echo "Configuration:"
    read -p "Panel port (default: 8000): " PANEL_PORT
    PANEL_PORT=${PANEL_PORT:-8000}
fi

# --- Copy application source ---
mkdir -p "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/panel.new"
cp -r "$BUNDLE_DIR/panel" "$INSTALL_DIR/panel.new"
# Preserve existing data/certs across reinstall
if [ -d "$INSTALL_DIR/panel/data" ]; then
    rm -rf "$INSTALL_DIR/panel.new/data"
    cp -r "$INSTALL_DIR/panel/data" "$INSTALL_DIR/panel.new/data"
fi
if [ -d "$INSTALL_DIR/panel/certs" ]; then
    rm -rf "$INSTALL_DIR/panel.new/certs"
    cp -r "$INSTALL_DIR/panel/certs" "$INSTALL_DIR/panel.new/certs"
fi
rm -rf "$INSTALL_DIR/panel.bak"
[ -d "$INSTALL_DIR/panel" ] && mv "$INSTALL_DIR/panel" "$INSTALL_DIR/panel.bak"
mv "$INSTALL_DIR/panel.new" "$INSTALL_DIR/panel"
rm -rf "$INSTALL_DIR/panel.bak"
rm -rf "$INSTALL_DIR/cli"
cp -r "$BUNDLE_DIR/cli" "$INSTALL_DIR/cli"
mkdir -p "$INSTALL_DIR/panel/data" "$INSTALL_DIR/panel/certs"
# Version marker so the panel reports the installed bundle version
if [ -f "$BUNDLE_DIR/VERSION" ]; then
    cp "$BUNDLE_DIR/VERSION" "$INSTALL_DIR/panel/VERSION"
    cp "$BUNDLE_DIR/VERSION" "$INSTALL_DIR/VERSION"
fi
progress "Application files installed to $INSTALL_DIR"

# --- Prebuilt frontend (no npm needed) ---
if [ -d "$BUNDLE_DIR/frontend-dist" ] && [ -f "$BUNDLE_DIR/frontend-dist/index.html" ]; then
    rm -rf "$INSTALL_DIR/panel/static"
    cp -r "$BUNDLE_DIR/frontend-dist" "$INSTALL_DIR/panel/static"
    progress "Frontend (prebuilt) installed"
else
    warn "No prebuilt frontend in bundle; API will still work at /api and /docs"
fi

# --- Tunnel binaries to /usr/local/bin ---
if [ -d "$BUNDLE_DIR/bin" ]; then
    for b in "$BUNDLE_DIR/bin/"*; do
        [ -f "$b" ] || continue
        install -m 0755 "$b" "/usr/local/bin/$(basename "$b")"
    done
    progress "Tunnel binaries installed to /usr/local/bin (gost, rathole, chisel, frpc, frps, backhaul, udp2raw, nfqws, rstund, rstunc)"
else
    warn "No bin/ directory in bundle; panel-side cores (gost/frp) may be unavailable"
fi

# --- Python virtual environment (fully offline) ---
echo ""
echo "Creating Python virtual environment (offline)..."
python3 -m venv "$INSTALL_DIR/panel/.venv"
"$INSTALL_DIR/panel/.venv/bin/pip" install --no-index --upgrade pip 2>/dev/null || true
"$INSTALL_DIR/panel/.venv/bin/pip" install --no-index --find-links="$BUNDLE_DIR/wheels/panel" -r "$INSTALL_DIR/panel/requirements.txt"
progress "Python dependencies installed from offline wheels"

# --- .env ---
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cat > "$INSTALL_DIR/.env" << EOF
PANEL_HOST=0.0.0.0
PANEL_PORT=$PANEL_PORT
DOCS_ENABLED=true

DB_TYPE=sqlite
DB_PATH=./data/smite.db

SECRET_KEY=$(openssl rand -hex 32)
EOF
    progress "Configuration written to $INSTALL_DIR/.env"
else
    warn "$INSTALL_DIR/.env already exists, keeping it"
fi

# Refresh SMITE_VERSION in .env so the panel reports the installed version
if [ -f "$BUNDLE_DIR/VERSION" ]; then
    BUNDLE_VERSION="$(cat "$BUNDLE_DIR/VERSION" | tr -d '[:space:]')"
    if [ -n "$BUNDLE_VERSION" ] && [ "$BUNDLE_VERSION" != "offline" ]; then
        if grep -q "^SMITE_VERSION=" "$INSTALL_DIR/.env"; then
            sed -i "s|^SMITE_VERSION=.*|SMITE_VERSION=$BUNDLE_VERSION|" "$INSTALL_DIR/.env"
        else
            echo "SMITE_VERSION=$BUNDLE_VERSION" >> "$INSTALL_DIR/.env"
        fi
        progress "Version set to $BUNDLE_VERSION"
    fi
fi

# --- CA certificate placeholder ---
if [ ! -f "$INSTALL_DIR/panel/certs/ca.crt" ]; then
    touch "$INSTALL_DIR/panel/certs/ca.crt" "$INSTALL_DIR/panel/certs/ca.key"
fi

# --- Network optimizations for stable tunnels ---
echo ""
echo "Applying network optimizations..."
if [ -f "/etc/sysctl.conf" ]; then
    if [ ! -f "/etc/sysctl.conf.smite-backup" ]; then
        cp /etc/sysctl.conf /etc/sysctl.conf.smite-backup
    fi
    if ! grep -q "# Smite Network Optimizations" /etc/sysctl.conf; then
        cat >> /etc/sysctl.conf << 'EOF'

# Smite Network Optimizations
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.ip_local_port_range = 10000 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 60
net.ipv4.tcp_keepalive_probes = 3
net.ipv4.tcp_slow_start_after_idle = 0
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.udp_mem = 3145728 4194304 16777216
net.ipv4.ip_forward = 1
EOF
        sysctl -p > /dev/null 2>&1 || true
        progress "Network optimizations applied"
    else
        progress "Network optimizations already applied"
    fi
fi

if [ -f "/etc/security/limits.conf" ]; then
    if ! grep -q "# Smite File Descriptor Limits" /etc/security/limits.conf; then
        cat >> /etc/security/limits.conf << 'EOF'

# Smite File Descriptor Limits
* soft nofile 65535
* hard nofile 65535
root soft nofile 65535
root hard nofile 65535
EOF
        progress "File descriptor limits increased"
    fi
    ulimit -n 65535 2>/dev/null || true
fi

if modprobe -n tcp_bbr 2>/dev/null; then
    if ! grep -q "tcp_bbr" /etc/modules-load.d/*.conf 2>/dev/null && ! grep -q "tcp_bbr" /etc/modules 2>/dev/null; then
        echo "tcp_bbr" | tee -a /etc/modules-load.d/smite.conf > /dev/null 2>&1 || echo "tcp_bbr" >> /etc/modules 2>/dev/null || true
        modprobe tcp_bbr 2>/dev/null || true
        sysctl -w net.ipv4.tcp_congestion_control=bbr > /dev/null 2>&1 || true
        sysctl -w net.core.default_qdisc=fq > /dev/null 2>&1 || true
        progress "BBR congestion control enabled"
    fi
fi

# --- CLI ---
echo ""
echo "Installing CLI..."
cp "$INSTALL_DIR/cli/smite.py" /usr/local/bin/smite
chmod +x /usr/local/bin/smite
progress "CLI installed (smite)"

# --- systemd service ---
echo ""
echo "Installing systemd service..."
cp "$BUNDLE_DIR/deploy/systemd/smite-panel.service" /etc/systemd/system/smite-panel.service
systemctl daemon-reload
systemctl enable smite-panel >/dev/null 2>&1 || true
systemctl restart smite-panel
progress "smite-panel service enabled and started"

sleep 4

echo ""
if systemctl is-active --quiet smite-panel; then
    echo -e "${GREEN}Smite Panel installed successfully (native, no Docker)!${NC}"
    echo ""
    echo "Panel URL: http://localhost:$PANEL_PORT"
    echo "API Docs:  http://localhost:$PANEL_PORT/docs"
    echo ""
    echo "Next steps:"
    echo "  1. Create admin user: smite admin create"
    echo "  2. Open the web interface at http://<server-ip>:$PANEL_PORT"
    echo ""
    echo "Manage with: smite status | smite restart | smite logs"
else
    echo -e "${RED}Installation completed but the panel service is not active.${NC}"
    echo "Check logs with: journalctl -u smite-panel -n 100 --no-pager"
    exit 1
fi
