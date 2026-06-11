# Smite - Tunneling Control Panel

<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/SmiteD.png"/>
    <source media="(prefers-color-scheme: light)" srcset="assets/SmiteL.png"/>
    <img src="assets/SmiteL.png" alt="Smite Logo" width="200"/>
  </picture>
  
  **Modern tunnel management built on GOST, Backhaul, Rathole, Chisel, FRP, and udp2raw, featuring dual-node architecture, intuitive WebUI, real-time status tracking, and open-source freedom.**
  
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
  [![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
  [![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688.svg)](https://fastapi.tiangolo.com/)
  [![React](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://reactjs.org/)
  [![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6.svg)](https://www.typescriptlang.org/)
  [![Docker](https://img.shields.io/badge/Docker-24.0+-2496ED.svg)](https://www.docker.com/)
  [![Nginx](https://img.shields.io/badge/Nginx-1.25+-009639.svg)](https://www.nginx.com/)
  [![SQLite](https://img.shields.io/badge/SQLite-3.42+-003B57.svg)](https://www.sqlite.org/)
</div>

---

## 🚀 Features

- **Multiple Tunnel Types**: Support for TCP, UDP, WebSocket, gRPC, TCPMux via GOST, Backhaul, Rathole, Chisel, FRP, and udp2raw (FakeTCP / ICMP / UDP)
- **DPI Bypass (zapret)**: Single-node `nfqws` DPI desync / SNI spoofing to keep TLS on :443 alive where SNI is filtered (see [docs/ZAPRET.md](docs/ZAPRET.md))
- **Unified Node Management**: Iran and Foreign nodes are manageable from a single panel for reverse tunnels
- **Web UI**: Modern, intuitive web interface with real-time connection status tracking
- **CLI Tools**: Powerful command-line tools for management
- **Telegram Bot**: Panel statistics and automatic backups via Telegram
- **GOST Forwarding**: Forward traffic from Iran nodes to Foreign servers with support for TCP, UDP, WebSocket, gRPC, and TCPMux
- **Offline Native Install**: Install the panel and nodes without Docker, GitHub, or international internet access using a pre-built offline bundle (systemd + Python venv)

---

## 📋 Prerequisites

- Docker and Docker Compose installed (for the Docker-based install)
- For Iran servers, install Docker first:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/manageitir/docker/main/install-ubuntu.sh | sh
  ```
- **No Docker / no internet?** Use the [Offline Native Install](#-offline-native-install-no-docker) instead — it only needs `python3` and `openssl` on the target server.

---

## 🔧 Panel Installation

### Quick Install

```bash
sudo bash -c "$(curl -sL https://raw.githubusercontent.com/zZedix/Smite/main/scripts/install.sh)"
```

<details>
<summary><strong>Manual Install</strong></summary>

1. Clone the repository:
```bash
git clone https://github.com/zZedix/Smite.git
cd Smite
```

2. Copy environment file and configure:
```bash
cp .env.example .env
# Edit .env with your settings
```

3. Install CLI tools:
```bash
sudo bash cli/install_cli.sh
```

4. Start services:
```bash
docker compose up -d
```

5. Create admin user:
```bash
smite admin create
```

6. Access the web interface at `http://localhost:8000`

</details>

---

## 🖥️ Node Installation

### Architecture

- **Iran Nodes**: Handle reverse tunnels (Rathole, Backhaul, Chisel, FRP, udp2raw) and run GOST forwarders
- **Foreign Nodes**: Participate in reverse tunnels and receive forwarded traffic from Iran nodes

### Quick Install

```bash
sudo bash -c "$(curl -sL https://raw.githubusercontent.com/zZedix/Smite/main/scripts/smite-node.sh)"
```

<details>
<summary><strong>Manual Install</strong></summary>

1. Navigate to node directory:
```bash
cd node
```

2. Copy Panel CA certificate:
```bash
mkdir -p certs
# For Iran nodes, use ca.crt
cp /path/to/panel/ca.crt certs/ca.crt
# For Foreign servers, use ca-server.crt
# cp /path/to/panel/ca-server.crt certs/ca.crt
```

3. Create `.env` file:
```bash
cat > .env << EOF
NODE_API_PORT=8888
NODE_NAME=node-1
PANEL_CA_PATH=/etc/smite-node/certs/ca.crt
PANEL_ADDRESS=panel.example.com:443
EOF
```

> **Note**: The panel validates node roles during registration. Each node must have a consistent role (iran or foreign) to prevent conflicts.

4. Start node:
```bash
docker compose up -d
```

</details>

---

## 📦 Offline Native Install (No Docker)

For servers with **no access to Docker, GitHub, PyPI, npm, or international internet** (e.g. Iran servers under heavy restrictions), Smite can be installed natively with `systemd` + Python `venv` from a single pre-built tarball. The only prerequisites on the target server are `python3` (with `venv`) and `openssl` — both ship with Ubuntu by default.

### Step 1 — Build the offline bundle (on a machine WITH internet)

```bash
git clone https://github.com/zZedix/Smite.git
cd Smite
bash scripts/build-offline-bundle.sh
```

This produces `smite-offline-<arch>.tar.gz` containing the panel/node source, the pre-built frontend, all pip wheels, all tunnel binaries (`gost`, `rathole`, `chisel`, `frpc`, `frps`, `backhaul`, `udp2raw`, `nfqws`/zapret), systemd units, CLIs, and the native installers.

Options (environment variables):

```bash
TARGET_ARCH=arm64 bash scripts/build-offline-bundle.sh          # build for arm64 servers
TARGET_PY=311 TARGET_PLATFORM=manylinux2014_x86_64 \
  bash scripts/build-offline-bundle.sh                          # cross-download wheels for another Python/OS
SKIP_FRONTEND=1 bash scripts/build-offline-bundle.sh            # reuse an existing frontend/dist
```

> **Tip**: Build on the same OS/Python version as the target server (e.g. Ubuntu 22.04 → Python 3.10) or set `TARGET_PY`/`TARGET_PLATFORM` so the wheels match.

### Step 2 — Transfer the bundle to the offline server

```bash
scp smite-offline-amd64.tar.gz root@your-server:/root/
```

### Step 3 — Install the panel (offline server)

```bash
tar -xzf smite-offline-amd64.tar.gz
cd smite-offline-amd64
sudo bash scripts/install-native.sh
```

The installer sets up `/opt/smite` with a Python venv (wheels installed offline with `pip --no-index`), copies all tunnel binaries to `/usr/local/bin`, installs the pre-built frontend, applies network optimizations (BBR, sysctl, limits), configures `.env` interactively, and starts the `smite-panel` systemd service. Then create the admin user:

```bash
smite admin create
```

### Step 4 — Install nodes (offline servers)

On each node server (Iran or Foreign), extract the same bundle and run:

```bash
tar -xzf smite-offline-amd64.tar.gz
cd smite-offline-amd64
sudo bash scripts/install-node-native.sh
```

The installer asks for the node name, role (`iran`/`foreign`), panel address, and CA certificate, then starts the `smite-node` systemd service with the capabilities tunnels need (`NET_ADMIN`, `NET_RAW`, `/dev/net/tun` — required for udp2raw raw sockets).

### Managing native installs

The `smite` and `smite-node` CLIs automatically detect native (systemd) installs and map commands accordingly:

```bash
smite status / restart / logs / edit-env      # uses systemctl + journalctl
smite-node status / restart / logs / edit-env
```

Services can also be managed directly:

```bash
systemctl status smite-panel    # or smite-node
journalctl -u smite-panel -f
```

### Updating an offline install

Build a fresh bundle on the internet-connected machine, transfer it, extract it over the previous directory, and re-run the same installer — data (`/opt/smite/panel/data`, certs, `.env`) is preserved.

---

## 🛠️ CLI Tools

### Panel CLI (`smite`)

**Admin Management:**
```bash
smite admin create      # Create admin user
smite admin update      # Update admin password
```

**Panel Management:**
```bash
smite status            # Show system status
smite update            # Update panel (pull images and recreate)
smite restart           # Restart panel (recreate to pick up .env changes)
smite logs              # View panel logs
```

**Configuration:**
```bash
smite edit              # Edit docker-compose.yml
smite edit-env          # Edit .env file
```

### Node CLI (`smite-node`)

**Node Management:**
```bash
smite-node status       # Show node status
smite-node update       # Update node (pull images and recreate)
smite-node restart      # Restart node (recreate to pick up .env changes)
smite-node logs         # View node logs
```

**Configuration:**
```bash
smite-node edit         # Edit docker-compose.yml
smite-node edit-env     # Edit .env file
```

---

## 📖 Tunnel Types

### GOST Tunnels (Iran Node Forwarding)
- **TCP**: Simple TCP forwarding
- **UDP**: UDP packet forwarding
- **WebSocket (WS)**: WebSocket protocol forwarding
- **gRPC**: gRPC protocol forwarding
- **TCPMux**: TCP multiplexing for multiple connections

GOST tunnels run on Iran nodes and forward traffic to Foreign servers. When creating a GOST tunnel, specify both an Iran node and a Foreign server. The Iran node will listen on the specified port and forward all traffic to the Foreign server's IP address and port.

### Backhaul Tunnels (Reverse Tunnel)
- **TCP / UDP**: Low-latency reverse tunnels with optional UDP-over-TCP
- **WS / WSMux**: WebSocket transports for CDN-friendly deployments
- **TCPMux**: TCP multiplexing support
- **Advanced Controls**: Configure multiplexing, keepalive, sniffer, and custom port maps per tunnel

The panel automatically configures both Iran and Foreign nodes when creating a tunnel.

### Rathole Tunnels (Reverse Tunnel)
- **TCP**: Standard TCP reverse tunnel
- **WebSocket (WS)**: WebSocket transport support

Rathole tunnels allow you to expose services running on the Foreign node's network through the Iran node.

### Chisel Tunnels (Reverse Tunnel)
Chisel tunnels provide fast TCP reverse tunnel functionality, enabling you to expose services running on the Foreign node's network through the Iran node with high performance.

### FRP Tunnels (Reverse Tunnel)
FRP (Fast Reverse Proxy) tunnels provide reliable TCP/UDP reverse tunnel functionality. FRP supports both TCP and UDP protocols, with optional IPv6 support for tunneling IPv6 traffic over IPv4 networks.

### udp2raw Tunnels (Dual-Node UDP Obfuscation)
- **FakeTCP**: Wraps UDP traffic in raw packets that look like TCP — bypasses UDP blocking/QoS on most ISPs
- **ICMP**: Wraps UDP traffic in ICMP (ping) packets
- **UDP**: Plain UDP mode with udp2raw's encryption and anti-replay

udp2raw tunnels run on both nodes: the **Iran node** runs the udp2raw client and exposes a public UDP port (users connect here), and the **Foreign node** runs the udp2raw server, which unwraps the traffic and forwards it to the target UDP service (e.g. WireGuard, Hysteria, OpenVPN). Traffic between the two nodes is encrypted (AES-128-CBC by default) and authenticated. The shared key, the raw port, and iptables rules are managed automatically by the panel.

> **Note**: udp2raw uses raw sockets, so both nodes need `NET_RAW`/`NET_ADMIN` capabilities — these are pre-configured in both the Docker and native (systemd) installs.

### Zapret (Single-Node DPI Bypass / SNI Spoofing)
Unlike the tunnel cores above, **zapret is not a tunnel** — it does not carry traffic between two nodes. It runs the `nfqws` packet processor on a **single node** and desynchronizes the TLS handshake (SNI spoofing, fake ClientHello, etc.) so that DPI systems which block by SNI cannot match your real `443` traffic.

Use it on the server that **opens the outbound TLS connection** — typically a foreign / relay server hosting an Xray VLESS proxy whose outbound is a TLS+WebSocket domain-fronting connection on port `443`. Smite manages the `nfqws` process and the per-tunnel NFQUEUE `iptables` rules for you (no global flush, so it coexists safely with udp2raw and other cores).

- **Desync modes**: `fake`, `fakedsplit`, `multisplit`, `multidisorder`, `disorder2`, `split2`, `syndata`
- **Configurable**: filter ports (default `443`), L7 filter (`tls`), fake SNI (e.g. `hcaptcha.com`), fooling (`badseq,ts`), direction, queue number
- **Requires**: `NET_ADMIN` + `NET_RAW` and the `nfqws` binary (bundled in the Docker image and the offline bundle)

See the full walkthrough — including the companion `xray` / `config.json` setup and when to use which desync strategy — in **[docs/ZAPRET.md](docs/ZAPRET.md)**.

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 💰 Donations

If you find Smite useful and want to support its development, consider making a donation:

### Cryptocurrency Donations

- **Bitcoin (BTC)**: `bc1q637gahjssmv9g3903j88tn6uyy0w2pwuvsp5k0`
- **Ethereum (ETH)**: `0x5B2eE8970E3B233F79D8c765E75f0705278098a0`
- **Tron (TRX)**: `TSAsosG9oHMAjAr3JxPQStj32uAgAUmMp3`
- **USDT (BEP20)**: `0x5B2eE8970E3B233F79D8c765E75f0705278098a0`
- **TON**: `UQA-95WAUn_8pig7rsA9mqnuM5juEswKONSlu-jkbUBUhku6`

### Other Ways to Support

- ⭐ Star the repository if you find it useful
- 🐛 Report bugs and suggest improvements
- 📖 Improve documentation and translations
- 🔗 Share with others who might benefit

---

<div align="center">
  
  **Made with ❤️ by [zZedix](https://github.com/zZedix)**
  
  *Securing the digital world, one line of code at a time!*
  
</div>
