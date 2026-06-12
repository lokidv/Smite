#!/bin/bash
# Smite Node Installer
#
# NOTE: This is a copy of scripts/smite-node.sh shipped inside the panel app so
# the remote-provisioning feature can push it via SFTP to a foreign target
# (the Docker image does not include the repo-level scripts/ directory). Keep it
# in sync with scripts/smite-node.sh.

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

if [ -d "$INSTALL_DIR" ] && [ -f "$INSTALL_DIR/docker-compose.yml" ]; then
    echo "Smite Node already installed in $INSTALL_DIR"
    cd "$INSTALL_DIR"
else
    echo "Setting up Smite Node..."
    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Prompt for configuration
echo ""
echo "Configuration:"

if [ "$NONINTERACTIVE" = "1" ]; then
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
    echo "CA certificate saved to certs/ca.crt"
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
    echo "1) Iran Server"
    echo "2) Foreign Server"
    read -p "Enter choice [1 or 2] (default: 1): " ROLE_CHOICE
    ROLE_CHOICE=${ROLE_CHOICE:-1}
    if [ "$ROLE_CHOICE" = "2" ]; then
        NODE_ROLE="foreign"
    else
        NODE_ROLE="iran"
    fi

    echo ""
    echo "=== CA Certificate ==="
    echo "Paste the CA certificate, then an empty line to finish:"
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
        echo "Error: CA certificate is required"
        exit 1
    fi
    mkdir -p certs
    echo -e "$PANEL_CA_CONTENT" > certs/ca.crt
    if [ ! -s "certs/ca.crt" ]; then
        echo "Error: Failed to save CA certificate"
        exit 1
    fi
    echo "CA certificate saved to certs/ca.crt"
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

# Clone node files from GitHub
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
    cp -r "$TEMP_DIR/node"/* .
    rm -rf "$TEMP_DIR"
else
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
CLI_BRANCH="main"
if [ "${SMITE_VERSION:-latest}" = "next" ]; then
    CLI_BRANCH="next"
fi
curl -L https://raw.githubusercontent.com/lokidv/Smite/${CLI_BRANCH}/cli/smite-node.py -o /usr/local/bin/smite-node 2>/dev/null && chmod +x /usr/local/bin/smite-node || true

mkdir -p config

# Pull or build Docker image
if [ -z "${SMITE_VERSION}" ]; then
    export SMITE_VERSION=latest
fi
if docker pull ghcr.io/zzedix/smite-node:${SMITE_VERSION} 2>/dev/null; then
    echo "Node image pulled from GHCR"
else
    echo "Prebuilt image not found, building locally..."
    docker compose build 2>&1 || true
fi

echo ""
echo "Starting Smite Node..."
docker compose up -d

echo "Waiting for services to start..."
sleep 5

if docker ps | grep -q smite-node; then
    echo ""
    echo "Smite Node installed successfully!"
    echo "Node API: http://localhost:$NODE_API_PORT"
else
    echo "Installation completed but node is not running"
    docker compose logs 2>&1 | tail -n 50 || true
    exit 1
fi
