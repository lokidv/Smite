#!/bin/bash
# Smite Node Installer

set -e

echo "=== Smite Node Installer ==="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

# Non-interactive mode (for remote provisioning / automation).
#   sudo SMITE_NONINTERACTIVE=1 PANEL_ADDRESS=... bash smite-node.sh
#   (or pass --yes / -y)
# Fresh-install configuration is taken from environment variables:
#   PANEL_ADDRESS (required), PANEL_API_PORT, NODE_API_PORT, NODE_NAME,
#   NODE_ROLE (iran|foreign), and the CA from PANEL_CA or PANEL_CA_FILE.
NONINTERACTIVE="${SMITE_NONINTERACTIVE:-0}"
for arg in "$@"; do
    case "$arg" in
        --yes|-y|--non-interactive) NONINTERACTIVE=1 ;;
    esac
done

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
fi

# Get installation directory
INSTALL_DIR="/opt/smite-node"
echo "Installing to: $INSTALL_DIR"

# Clone from GitHub if needed
if [ -d "$INSTALL_DIR" ] && [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
    echo "Smite Node already installed in $INSTALL_DIR"
    cd "$INSTALL_DIR"
else
    echo "Setting up Smite Node..."
    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    
    # Clone just the node files or create minimal structure
    # For now, we'll create the necessary files
fi

# Prompt for configuration
echo ""
echo "Configuration:"

if [ "$NONINTERACTIVE" = "1" ]; then
    # --- Non-interactive: take everything from environment variables ---
    if [ -z "$PANEL_ADDRESS" ]; then
        echo "Error: PANEL_ADDRESS environment variable is required in non-interactive mode"
        exit 1
    fi
    PANEL_API_PORT=${PANEL_API_PORT:-8000}
    NODE_API_PORT=${NODE_API_PORT:-8888}
    NODE_NAME=${NODE_NAME:-node-1}
    NODE_ROLE=${NODE_ROLE:-iran}
    if [ "$NODE_ROLE" != "iran" ] && [ "$NODE_ROLE" != "foreign" ]; then
        echo "Error: NODE_ROLE must be 'iran' or 'foreign' (got '$NODE_ROLE')"
        exit 1
    fi
    echo "Non-interactive configuration: panel=$PANEL_ADDRESS role=$NODE_ROLE name=$NODE_NAME"

    mkdir -p certs
    if [ -n "$PANEL_CA_FILE" ] && [ -f "$PANEL_CA_FILE" ]; then
        cp "$PANEL_CA_FILE" certs/ca.crt
    elif [ -n "$PANEL_CA" ]; then
        printf '%s\n' "$PANEL_CA" > certs/ca.crt
    fi
    if [ ! -s "certs/ca.crt" ]; then
        echo "Error: CA certificate is required (set PANEL_CA or PANEL_CA_FILE)"
        exit 1
    fi
    echo "✅ CA certificate saved to certs/ca.crt"
else
    read -p "Panel address (host:port, e.g., panel.example.com:443): " PANEL_ADDRESS
    if [ -z "$PANEL_ADDRESS" ]; then
        echo "Error: Panel address is required"
        exit 1
    fi

    read -p "Panel port (should match the panel's port from panel installation, default: 8000): " PANEL_API_PORT
    PANEL_API_PORT=${PANEL_API_PORT:-8000}

    read -p "Node API port (default: 8888): " NODE_API_PORT
    NODE_API_PORT=${NODE_API_PORT:-8888}

    read -p "Node name (default: node-1): " NODE_NAME
    NODE_NAME=${NODE_NAME:-node-1}

    echo ""
    echo "=== Server Role ==="
    echo "Select server role:"
    echo "1) Iran Server (runs tunnel clients, connects to foreign servers)"
    echo "2) Foreign Server (runs tunnel servers, accepts connections from Iran servers)"
    read -p "Enter choice [1 or 2] (default: 1): " ROLE_CHOICE
    ROLE_CHOICE=${ROLE_CHOICE:-1}

    if [ "$ROLE_CHOICE" = "2" ]; then
        NODE_ROLE="foreign"
        echo "✅ Selected: Foreign Server"
        CA_SOURCE="Servers > View CA Certificate"
    else
        NODE_ROLE="iran"
        echo "✅ Selected: Iran Server"
        CA_SOURCE="Nodes > View CA Certificate"
    fi

    echo ""
    echo "=== CA Certificate ==="
    echo "Please paste the CA certificate from the panel (copy from $CA_SOURCE):"
    echo "Press Enter after pasting, then press Enter again on an empty line to finish"
    echo ""
    PANEL_CA_CONTENT=""
    has_content=false
    while IFS= read -r line; do
        if [ -z "$line" ]; then
            # If we have content and hit an empty line, we're done
            if [ "$has_content" = true ]; then
                break
            fi
            # Otherwise, ignore leading empty lines
            continue
        else
            has_content=true
            PANEL_CA_CONTENT="${PANEL_CA_CONTENT}${line}\n"
        fi
    done

    if [ -z "$PANEL_CA_CONTENT" ]; then
        echo "Error: CA certificate is required"
        exit 1
    fi

    # Save CA certificate
    mkdir -p certs
    echo -e "$PANEL_CA_CONTENT" > certs/ca.crt
    if [ ! -f "certs/ca.crt" ] || [ ! -s "certs/ca.crt" ]; then
        echo "Error: Failed to save CA certificate"
        exit 1
    fi
    echo "✅ CA certificate saved to certs/ca.crt"
fi

# Create .env file
cat > .env << EOF
NODE_API_PORT=$NODE_API_PORT
NODE_NAME=$NODE_NAME
NODE_ROLE=$NODE_ROLE
SMITE_VERSION=${SMITE_VERSION:-latest}

PANEL_CA_PATH=/etc/smite-node/certs/ca.crt
PANEL_ADDRESS=$PANEL_ADDRESS
PANEL_API_PORT=$PANEL_API_PORT
EOF

# Clone/update node files from GitHub
GIT_BRANCH=""
if [ "${SMITE_VERSION:-latest}" = "next" ]; then
    GIT_BRANCH="-b next"
fi

if [ ! -f "Dockerfile" ]; then
    echo "Cloning node files from GitHub..."
    TEMP_DIR=$(mktemp -d)
    git clone --depth 1 $GIT_BRANCH https://github.com/lokidv/Smite.git "$TEMP_DIR" || {
        echo "Error: Failed to clone repository"
        exit 1
    }
    
    # Copy node files
    cp -r "$TEMP_DIR/node"/* .
    rm -rf "$TEMP_DIR"
else
    # Update docker-compose.yml and Dockerfile if they exist
    echo "Updating node files from GitHub..."
    TEMP_DIR=$(mktemp -d)
    git clone --depth 1 $GIT_BRANCH https://github.com/lokidv/Smite.git "$TEMP_DIR" || {
        echo "Warning: Failed to clone repository for updates"
        rm -rf "$TEMP_DIR"
    } || true
    if [ -d "$TEMP_DIR/node" ]; then
        cp -f "$TEMP_DIR/node/docker-compose.yml" docker-compose.yml 2>/dev/null || true
        cp -f "$TEMP_DIR/node/Dockerfile" Dockerfile 2>/dev/null || true
        rm -rf "$TEMP_DIR"
    fi
fi

# Install CLI
if [ -f "/opt/smite/cli/smite-node.py" ]; then
    sudo cp /opt/smite/cli/smite-node.py /usr/local/bin/smite-node
    sudo chmod +x /usr/local/bin/smite-node
elif [ -f "$INSTALL_DIR/../Smite/cli/smite-node.py" ]; then
    sudo cp "$INSTALL_DIR/../Smite/cli/smite-node.py" /usr/local/bin/smite-node
    sudo chmod +x /usr/local/bin/smite-node
else
    # Download CLI directly
    echo "Downloading CLI tool..."
    CLI_BRANCH="main"
    if [ "${SMITE_VERSION:-latest}" = "next" ]; then
        CLI_BRANCH="next"
    fi
    sudo curl -L https://raw.githubusercontent.com/lokidv/Smite/${CLI_BRANCH}/cli/smite-node.py -o /usr/local/bin/smite-node
    sudo chmod +x /usr/local/bin/smite-node
fi

# Create config directory
mkdir -p config

# Apply network optimizations for stable tunnels
echo ""
echo "Applying network optimizations..."
if [ -f "/etc/sysctl.conf" ]; then
    # Backup original sysctl.conf
    if [ ! -f "/etc/sysctl.conf.smite-backup" ]; then
        cp /etc/sysctl.conf /etc/sysctl.conf.smite-backup
    fi
    
    # Add network optimizations if not already present
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
        # Apply optimizations
        sysctl -p > /dev/null 2>&1 || true
        echo "✅ Network optimizations applied"
    else
        echo "✅ Network optimizations already applied"
    fi
fi

# Increase file descriptor limits
if [ -f "/etc/security/limits.conf" ]; then
    if ! grep -q "# Smite File Descriptor Limits" /etc/security/limits.conf; then
        cat >> /etc/security/limits.conf << 'EOF'

# Smite File Descriptor Limits
* soft nofile 65535
* hard nofile 65535
root soft nofile 65535
root hard nofile 65535
EOF
        echo "✅ File descriptor limits increased"
    fi
    # Apply for current session
    ulimit -n 65535 2>/dev/null || true
fi

# Enable BBR congestion control (if available)
if modprobe -n tcp_bbr 2>/dev/null; then
    if ! grep -q "tcp_bbr" /etc/modules-load.d/*.conf 2>/dev/null && ! grep -q "tcp_bbr" /etc/modules 2>/dev/null; then
        echo "tcp_bbr" | tee -a /etc/modules-load.d/smite.conf > /dev/null 2>&1 || echo "tcp_bbr" >> /etc/modules 2>/dev/null || true
        modprobe tcp_bbr 2>/dev/null || true
        sysctl -w net.ipv4.tcp_congestion_control=bbr > /dev/null 2>&1 || true
        sysctl -w net.core.default_qdisc=fq > /dev/null 2>&1 || true
        echo "✅ BBR congestion control enabled"
    else
        echo "✅ BBR congestion control already enabled"
    fi
fi

# Pull or build Docker image
echo ""
echo "Pulling Docker image from GitHub Container Registry..."
if [ -z "${SMITE_VERSION}" ]; then
    export SMITE_VERSION=latest
fi

if docker pull ghcr.io/lokidv/smite-node:${SMITE_VERSION} 2>/dev/null; then
    echo "✅ Node image pulled from GHCR"
else
    echo "⚠️  Prebuilt image not found, will build locally..."
    docker compose build 2>&1 || true
fi

# Start services
echo ""
echo "Starting Smite Node..."
docker compose up -d

# Wait for services
echo "Waiting for services to start..."
sleep 5

# Check status
if docker ps | grep -q smite-node; then
    echo ""
    echo "✅ Smite Node installed successfully!"
    echo ""
    echo "Node API: http://localhost:$NODE_API_PORT"
    echo ""
    echo "Check status with: smite-node status"
    echo ""
else
    echo "❌ Installation completed but node is not running"
    echo "Check logs with: docker compose logs"
    exit 1
fi

