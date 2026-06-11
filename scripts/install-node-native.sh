#!/bin/bash
# Smite Node - Offline Native Installer (Docker-free: systemd + Python venv)
#
# Installs the Smite node agent and all tunnel cores (gost, rathole, chisel,
# frpc/frps, backhaul, udp2raw) without Docker, from a self-contained offline
# bundle. Suitable for Iran servers with no Docker/GitHub/international internet.
#
# Run this from inside the extracted bundle: sudo bash scripts/install-node-native.sh
#
# Non-interactive mode (for self-update / automation):
#   sudo bash scripts/install-node-native.sh --yes
#   (or SMITE_NONINTERACTIVE=1)
#   - if /etc/smite-node/.env already exists it is preserved as-is (reinstall/
#     update path: no prompts, no CA paste needed)
#   - on a fresh install, configuration is taken from environment variables:
#     PANEL_ADDRESS (required), PANEL_API_PORT, NODE_API_PORT, NODE_NAME,
#     NODE_ROLE (iran|foreign), and the CA from PANEL_CA or PANEL_CA_FILE.

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

echo "=== Smite Node Offline Native Installer (no Docker) ==="
echo ""

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="/opt/smite-node"
CONFIG_DIR="/etc/smite-node"
DATA_DIR="/var/lib/smite-node"

if [ ! -d "$BUNDLE_DIR/node" ] || [ ! -d "$BUNDLE_DIR/wheels/node" ]; then
    echo -e "${RED}Error: this script must be run from inside an offline bundle.${NC}"
    echo "Expected $BUNDLE_DIR/node and $BUNDLE_DIR/wheels/node to exist."
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

# --- Local prerequisites ---
need_pkgs=""
command -v python3 >/dev/null 2>&1 || need_pkgs="$need_pkgs python3"
python3 -m venv --help >/dev/null 2>&1 || need_pkgs="$need_pkgs python3-venv"
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
# An existing /etc/smite-node/.env means this is a reinstall/update: preserve
# the configuration (and CA) instead of prompting again.
KEEP_ENV=0
if [ -f "$CONFIG_DIR/.env" ]; then
    if [ "$NONINTERACTIVE" = "1" ]; then
        KEEP_ENV=1
    else
        echo "Existing configuration found at $CONFIG_DIR/.env"
        read -p "Keep existing configuration? [Y/n]: " KEEP_CHOICE
        KEEP_CHOICE=${KEEP_CHOICE:-Y}
        case "$KEEP_CHOICE" in
            [Nn]*) KEEP_ENV=0 ;;
            *) KEEP_ENV=1 ;;
        esac
    fi
fi

if [ "$KEEP_ENV" = "1" ]; then
    progress "Keeping existing configuration ($CONFIG_DIR/.env)"
    NODE_API_PORT="$(grep -E '^NODE_API_PORT=' "$CONFIG_DIR/.env" | head -n1 | cut -d= -f2)"
    NODE_API_PORT=${NODE_API_PORT:-8888}
    mkdir -p "$INSTALL_DIR" "$CONFIG_DIR/certs" "$DATA_DIR"
elif [ "$NONINTERACTIVE" = "1" ]; then
    # Fresh non-interactive install: everything comes from the environment.
    if [ -z "$PANEL_ADDRESS" ]; then
        echo -e "${RED}Error: PANEL_ADDRESS environment variable is required in non-interactive mode${NC}"
        exit 1
    fi
    PANEL_API_PORT=${PANEL_API_PORT:-8000}
    NODE_API_PORT=${NODE_API_PORT:-8888}
    NODE_NAME=${NODE_NAME:-node-1}
    NODE_ROLE=${NODE_ROLE:-iran}

    mkdir -p "$INSTALL_DIR" "$CONFIG_DIR/certs" "$DATA_DIR"

    if [ -n "$PANEL_CA_FILE" ] && [ -f "$PANEL_CA_FILE" ]; then
        cp "$PANEL_CA_FILE" "$CONFIG_DIR/certs/ca.crt"
    elif [ -n "$PANEL_CA" ]; then
        printf '%s\n' "$PANEL_CA" > "$CONFIG_DIR/certs/ca.crt"
    fi
    if [ ! -s "$CONFIG_DIR/certs/ca.crt" ]; then
        echo -e "${RED}Error: CA certificate is required (set PANEL_CA or PANEL_CA_FILE)${NC}"
        exit 1
    fi
    progress "Non-interactive configuration: panel=$PANEL_ADDRESS role=$NODE_ROLE"
else
    echo ""
    echo "Configuration:"
    read -p "Panel address (host or host:port, e.g. panel.example.com): " PANEL_ADDRESS
    if [ -z "$PANEL_ADDRESS" ]; then
        echo -e "${RED}Error: Panel address is required${NC}"
        exit 1
    fi

    read -p "Panel API port (must match panel PANEL_PORT, default: 8000): " PANEL_API_PORT
    PANEL_API_PORT=${PANEL_API_PORT:-8000}

    read -p "Node API port (default: 8888): " NODE_API_PORT
    NODE_API_PORT=${NODE_API_PORT:-8888}

    read -p "Node name (default: node-1): " NODE_NAME
    NODE_NAME=${NODE_NAME:-node-1}

    echo ""
    echo "=== Server Role ==="
    echo "1) Iran Server (runs tunnel servers, accepts connections from foreign side)"
    echo "2) Foreign Server (runs tunnel clients, connects out to Iran side)"
    read -p "Enter choice [1 or 2] (default: 1): " ROLE_CHOICE
    ROLE_CHOICE=${ROLE_CHOICE:-1}
    if [ "$ROLE_CHOICE" = "2" ]; then
        NODE_ROLE="foreign"
        CA_SOURCE="Servers > View CA Certificate"
        echo "Selected: Foreign Server"
    else
        NODE_ROLE="iran"
        CA_SOURCE="Nodes > View CA Certificate"
        echo "Selected: Iran Server"
    fi

    echo ""
    echo "=== CA Certificate ==="
    echo "Paste the CA certificate from the panel (copy from $CA_SOURCE)."
    echo "Press Enter on an empty line to finish:"
    echo ""
    PANEL_CA_CONTENT=""
    has_content=false
    while IFS= read -r line; do
        if [ -z "$line" ]; then
            if [ "$has_content" = true ]; then break; fi
            continue
        else
            has_content=true
            PANEL_CA_CONTENT="${PANEL_CA_CONTENT}${line}\n"
        fi
    done

    if [ -z "$PANEL_CA_CONTENT" ]; then
        echo -e "${RED}Error: CA certificate is required${NC}"
        exit 1
    fi

    # --- Directories ---
    mkdir -p "$INSTALL_DIR" "$CONFIG_DIR/certs" "$DATA_DIR"

    # --- Save CA certificate ---
    echo -e "$PANEL_CA_CONTENT" > "$CONFIG_DIR/certs/ca.crt"
    if [ ! -s "$CONFIG_DIR/certs/ca.crt" ]; then
        echo -e "${RED}Error: Failed to save CA certificate${NC}"
        exit 1
    fi
    progress "CA certificate saved to $CONFIG_DIR/certs/ca.crt"
fi

# --- Copy application source ---
rm -rf "$INSTALL_DIR/app" "$INSTALL_DIR/main.py" "$INSTALL_DIR/requirements.txt"
cp -r "$BUNDLE_DIR/node/app" "$INSTALL_DIR/app"
cp "$BUNDLE_DIR/node/main.py" "$INSTALL_DIR/main.py"
cp "$BUNDLE_DIR/node/requirements.txt" "$INSTALL_DIR/requirements.txt"
rm -rf "$INSTALL_DIR/cli"
cp -r "$BUNDLE_DIR/cli" "$INSTALL_DIR/cli"
# Version marker so the node reports the installed bundle version
if [ -f "$BUNDLE_DIR/VERSION" ]; then
    cp "$BUNDLE_DIR/VERSION" "$INSTALL_DIR/VERSION"
fi
progress "Application files installed to $INSTALL_DIR"

# --- Tunnel binaries ---
if [ -d "$BUNDLE_DIR/bin" ]; then
    for b in "$BUNDLE_DIR/bin/"*; do
        [ -f "$b" ] || continue
        install -m 0755 "$b" "/usr/local/bin/$(basename "$b")"
    done
    progress "Tunnel binaries installed to /usr/local/bin (gost, rathole, chisel, frpc, frps, backhaul, udp2raw, nfqws, rstund, rstunc, xray, hysteria, tuic-server, tuic-client, usque)"
else
    echo -e "${RED}No bin/ directory in bundle; node cannot run tunnels without binaries.${NC}"
    exit 1
fi

# --- Python virtual environment (offline) ---
echo ""
echo "Creating Python virtual environment (offline)..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --no-index --upgrade pip 2>/dev/null || true
"$INSTALL_DIR/.venv/bin/pip" install --no-index --find-links="$BUNDLE_DIR/wheels/node" -r "$INSTALL_DIR/requirements.txt"
progress "Python dependencies installed from offline wheels"

# --- .env ---
if [ "$KEEP_ENV" != "1" ]; then
    cat > "$CONFIG_DIR/.env" << EOF
NODE_API_PORT=$NODE_API_PORT
NODE_NAME=$NODE_NAME
NODE_ROLE=$NODE_ROLE

PANEL_CA_PATH=$CONFIG_DIR/certs/ca.crt
PANEL_ADDRESS=$PANEL_ADDRESS
PANEL_API_PORT=$PANEL_API_PORT
EOF
    progress "Configuration written to $CONFIG_DIR/.env"
fi

# Refresh SMITE_VERSION in .env so the node reports the installed version
if [ -f "$BUNDLE_DIR/VERSION" ]; then
    BUNDLE_VERSION="$(cat "$BUNDLE_DIR/VERSION" | tr -d '[:space:]')"
    if [ -n "$BUNDLE_VERSION" ] && [ "$BUNDLE_VERSION" != "offline" ]; then
        if grep -q "^SMITE_VERSION=" "$CONFIG_DIR/.env"; then
            sed -i "s|^SMITE_VERSION=.*|SMITE_VERSION=$BUNDLE_VERSION|" "$CONFIG_DIR/.env"
        else
            echo "SMITE_VERSION=$BUNDLE_VERSION" >> "$CONFIG_DIR/.env"
        fi
        progress "Version set to $BUNDLE_VERSION"
    fi
fi

# --- Network optimizations ---
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
net.ipv6.conf.all.forwarding = 1
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

# Ensure tun device is available for tun-based cores
if [ ! -e /dev/net/tun ]; then
    mkdir -p /dev/net
    mknod /dev/net/tun c 10 200 2>/dev/null || true
    chmod 600 /dev/net/tun 2>/dev/null || true
fi
modprobe tun 2>/dev/null || true

# --- CLI ---
echo ""
echo "Installing CLI..."
cp "$INSTALL_DIR/cli/smite-node.py" /usr/local/bin/smite-node
chmod +x /usr/local/bin/smite-node
progress "CLI installed (smite-node)"

# --- systemd service ---
echo ""
echo "Installing systemd service..."
cp "$BUNDLE_DIR/deploy/systemd/smite-node.service" /etc/systemd/system/smite-node.service
systemctl daemon-reload
systemctl enable smite-node >/dev/null 2>&1 || true
systemctl restart smite-node
progress "smite-node service enabled and started"

sleep 4

echo ""
if systemctl is-active --quiet smite-node; then
    echo -e "${GREEN}Smite Node installed successfully (native, no Docker)!${NC}"
    echo ""
    echo "Node API: http://localhost:$NODE_API_PORT"
    echo ""
    echo "Manage with: smite-node status | smite-node restart | smite-node logs"
else
    echo -e "${RED}Installation completed but the node service is not active.${NC}"
    echo "Check logs with: journalctl -u smite-node -n 100 --no-pager"
    exit 1
fi
