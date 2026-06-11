#!/bin/bash
# Smite - Offline Bundle Builder
#
# Run this on a machine WITH internet access (ideally same OS/arch as the target
# Iran server, or inside a manylinux/Ubuntu container). It produces a single
# self-contained tarball:  smite-offline-<arch>.tar.gz
#
# The tarball contains everything needed to install the panel or node WITHOUT
# Docker, GitHub, PyPI, npm, or any international internet access:
#   - panel/ and node/ source
#   - prebuilt frontend (frontend-dist/)
#   - pip wheels (wheels/panel, wheels/node)
#   - tunnel binaries (bin/): gost, rathole, chisel, frpc, frps, backhaul, udp2raw, nfqws (zapret)
#   - systemd units, CLIs, and the native installers
#
# Transfer the tarball to the offline server, extract it, then run:
#   sudo bash scripts/install-native.sh        # for the panel
#   sudo bash scripts/install-node-native.sh   # for a node
#
# Configuration via environment variables:
#   TARGET_ARCH       amd64 | arm64        (default: host arch)
#   TARGET_PY         e.g. 311, 312        (cross-download wheels for this CPython)
#   TARGET_PLATFORM   e.g. manylinux2014_x86_64 (enable cross-platform wheel download)
#   SKIP_FRONTEND     1 to skip npm build (reuse existing frontend/dist)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
progress() { echo -e "${GREEN}OK${NC} $1"; }
warn() { echo -e "${YELLOW}!${NC} $1"; }
fail() { echo -e "${RED}ERROR${NC} $1"; exit 1; }

# --- Pinned versions (kept in sync with panel/Dockerfile and node/Dockerfile) ---
FRP_VERSION="0.65.0"
RATHOLE_VERSION="0.5.0"
GOST_VERSION="2.12.0"
CHISEL_VERSION="1.11.3"
BACKHAUL_VERSION="0.7.2"
BACKHAUL_SHA256_AMD64="57bf95c2eabeddb1152d2e94ac42f4310883ce0fb909ee2a57bd53503b2dabbc"
BACKHAUL_SHA256_ARM64="9a424c97ff16fc3f682e8314c418790d2b5bf3136e008edbb6cd402ea00999f6"
UDP2RAW_VERSION="20230206.0"
ZAPRET_VERSION="v72.12"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- Resolve target arch ---
ARCH="${TARGET_ARCH:-}"
if [ -z "$ARCH" ]; then
    case "$(uname -m)" in
        x86_64|amd64) ARCH="amd64" ;;
        aarch64|arm64) ARCH="arm64" ;;
        *) ARCH="amd64" ;;
    esac
fi
case "$ARCH" in
    amd64) RATHOLE_ARCH="x86_64"; UDP2RAW_ASSET="udp2raw_amd64"; ZAPRET_ARCH="linux-x86_64" ;;
    arm64) RATHOLE_ARCH="aarch64"; UDP2RAW_ASSET="udp2raw_arm"; ZAPRET_ARCH="linux-arm64" ;;
    *) fail "Unsupported TARGET_ARCH: $ARCH (use amd64 or arm64)" ;;
esac
progress "Target architecture: $ARCH"

for tool in curl tar unzip gzip python3; do
    command -v "$tool" >/dev/null 2>&1 || fail "Required tool not found: $tool"
done

VERSION="$(git -C "$REPO_ROOT" describe --tags --abbrev=0 2>/dev/null || echo "offline")"

STAGE_NAME="smite-offline-${ARCH}"
STAGE="$(mktemp -d)/${STAGE_NAME}"
mkdir -p "$STAGE/bin" "$STAGE/wheels/panel" "$STAGE/wheels/node" "$STAGE/scripts" "$STAGE/deploy/systemd"
DL="$(mktemp -d)"

cleanup() { rm -rf "$DL"; }
trap cleanup EXIT

echo ""
echo "=== Building Smite offline bundle ($STAGE_NAME, version $VERSION) ==="

# --- 1. Copy application source (exclude caches / VCS / local state) ---
echo ""
echo "[1/6] Copying source..."
copy_src() {
    local src="$1" dst="$2"
    mkdir -p "$dst"
    tar -C "$src" \
        --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
        --exclude='.venv' --exclude='venv' --exclude='data' \
        --exclude='node_modules' \
        -cf - . | tar -C "$dst" -xf -
}
copy_src "$REPO_ROOT/panel" "$STAGE/panel"
copy_src "$REPO_ROOT/node" "$STAGE/node"
copy_src "$REPO_ROOT/cli" "$STAGE/cli"
cp "$REPO_ROOT/deploy/systemd/smite-panel.service" "$STAGE/deploy/systemd/"
cp "$REPO_ROOT/deploy/systemd/smite-node.service" "$STAGE/deploy/systemd/"
cp "$REPO_ROOT/scripts/install-native.sh" "$STAGE/scripts/"
cp "$REPO_ROOT/scripts/install-node-native.sh" "$STAGE/scripts/"
echo "$VERSION" > "$STAGE/VERSION"
echo "$ARCH" > "$STAGE/ARCH"
progress "Source copied"

# --- 2. Build frontend ---
echo ""
echo "[2/6] Building frontend..."
if [ "${SKIP_FRONTEND:-0}" = "1" ] && [ -d "$REPO_ROOT/frontend/dist" ]; then
    warn "SKIP_FRONTEND=1, reusing existing frontend/dist"
else
    command -v npm >/dev/null 2>&1 || fail "npm not found (needed to build frontend; set SKIP_FRONTEND=1 to reuse an existing build)"
    ( cd "$REPO_ROOT/frontend" && (npm ci --no-audit --no-fund || npm install --no-audit --no-fund) && npm run build )
fi
[ -f "$REPO_ROOT/frontend/dist/index.html" ] || fail "frontend/dist/index.html not found after build"
cp -r "$REPO_ROOT/frontend/dist" "$STAGE/frontend-dist"
progress "Frontend built and staged"

# --- 3. Download Python wheels ---
echo ""
echo "[3/6] Downloading Python wheels..."
PIP_XARGS=()
if [ -n "${TARGET_PLATFORM:-}" ]; then
    PIP_XARGS+=("--platform" "$TARGET_PLATFORM" "--only-binary=:all:")
    [ -n "${TARGET_PY:-}" ] && PIP_XARGS+=("--python-version" "$TARGET_PY")
    warn "Cross-downloading wheels for platform=$TARGET_PLATFORM py=${TARGET_PY:-host}"
else
    PIP_XARGS+=("--prefer-binary")
    warn "Downloading wheels for the host interpreter ($(python3 -V 2>&1)); run this on the same OS/arch/python as the target for best results"
fi
python3 -m pip download "${PIP_XARGS[@]}" -r "$REPO_ROOT/panel/requirements.txt" -d "$STAGE/wheels/panel"
python3 -m pip download "${PIP_XARGS[@]}" -r "$REPO_ROOT/node/requirements.txt" -d "$STAGE/wheels/node"
progress "Wheels downloaded"

# --- 4. Download tunnel binaries ---
echo ""
echo "[4/6] Downloading tunnel binaries for $ARCH..."

dl() { curl -fsSL "$1" -o "$2" || fail "Download failed: $1"; }

# frp (frpc + frps)
dl "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_${ARCH}.tar.gz" "$DL/frp.tar.gz"
tar -xzf "$DL/frp.tar.gz" -C "$DL"
install -m 0755 "$(find "$DL" -type f -name frpc | head -n1)" "$STAGE/bin/frpc"
install -m 0755 "$(find "$DL" -type f -name frps | head -n1)" "$STAGE/bin/frps"
progress "frp ${FRP_VERSION} (frpc, frps)"

# rathole
dl "https://github.com/rapiz1/rathole/releases/download/v${RATHOLE_VERSION}/rathole-${RATHOLE_ARCH}-unknown-linux-gnu.zip" "$DL/rathole.zip"
unzip -qo "$DL/rathole.zip" -d "$DL/rathole"
install -m 0755 "$(find "$DL/rathole" -type f -name rathole | head -n1)" "$STAGE/bin/rathole"
progress "rathole ${RATHOLE_VERSION}"

# gost
dl "https://github.com/ginuerzh/gost/releases/download/v${GOST_VERSION}/gost_${GOST_VERSION}_linux_${ARCH}.tar.gz" "$DL/gost.tar.gz"
tar -xzf "$DL/gost.tar.gz" -C "$DL"
install -m 0755 "$(find "$DL" -type f -name gost | head -n1)" "$STAGE/bin/gost"
progress "gost ${GOST_VERSION}"

# chisel
dl "https://github.com/jpillora/chisel/releases/download/v${CHISEL_VERSION}/chisel_${CHISEL_VERSION}_linux_${ARCH}.gz" "$DL/chisel.gz"
gunzip -c "$DL/chisel.gz" > "$DL/chisel"
install -m 0755 "$DL/chisel" "$STAGE/bin/chisel"
progress "chisel ${CHISEL_VERSION}"

# backhaul (with SHA256 verification)
dl "https://github.com/Musixal/Backhaul/releases/download/v${BACKHAUL_VERSION}/backhaul_linux_${ARCH}.tar.gz" "$DL/backhaul.tar.gz"
if [ "$ARCH" = "amd64" ]; then EXPECTED_SHA="$BACKHAUL_SHA256_AMD64"; else EXPECTED_SHA="$BACKHAUL_SHA256_ARM64"; fi
echo "${EXPECTED_SHA}  $DL/backhaul.tar.gz" | sha256sum -c - || fail "backhaul checksum mismatch"
tar -xzf "$DL/backhaul.tar.gz" -C "$DL"
install -m 0755 "$(find "$DL" -type f -name backhaul | head -n1)" "$STAGE/bin/backhaul"
progress "backhaul ${BACKHAUL_VERSION} (sha256 verified)"

# udp2raw
dl "https://github.com/wangyu-/udp2raw/releases/download/${UDP2RAW_VERSION}/udp2raw_binaries.tar.gz" "$DL/udp2raw.tar.gz"
mkdir -p "$DL/udp2raw"
tar -xzf "$DL/udp2raw.tar.gz" -C "$DL/udp2raw"
UDP2RAW_BIN="$(find "$DL/udp2raw" -type f -name "$UDP2RAW_ASSET" | head -n1)"
[ -n "$UDP2RAW_BIN" ] || fail "udp2raw asset $UDP2RAW_ASSET not found in release archive"
install -m 0755 "$UDP2RAW_BIN" "$STAGE/bin/udp2raw"
[ "$ARCH" = "arm64" ] && warn "udp2raw arm64 uses the 32-bit ARM build; ensure armhf/multiarch libs exist or rebuild from source"
progress "udp2raw ${UDP2RAW_VERSION}"

# zapret / nfqws (DPI desync, single-node SNI bypass)
dl "https://github.com/bol-van/zapret/releases/download/${ZAPRET_VERSION}/zapret-${ZAPRET_VERSION}.tar.gz" "$DL/zapret.tar.gz"
mkdir -p "$DL/zapret"
tar -xzf "$DL/zapret.tar.gz" -C "$DL/zapret"
NFQWS_BIN="$(find "$DL/zapret" -type f -path "*/binaries/${ZAPRET_ARCH}/nfqws" | head -n1)"
[ -n "$NFQWS_BIN" ] || fail "nfqws asset for ${ZAPRET_ARCH} not found in zapret release archive"
install -m 0755 "$NFQWS_BIN" "$STAGE/bin/nfqws"
progress "zapret/nfqws ${ZAPRET_VERSION}"

# --- 5. Make scripts executable ---
chmod +x "$STAGE/scripts/"*.sh

# --- 6. Package ---
echo ""
echo "[5/6] Packaging..."
OUT="$REPO_ROOT/${STAGE_NAME}.tar.gz"
tar -C "$(dirname "$STAGE")" -czf "$OUT" "$STAGE_NAME"
progress "Bundle created: $OUT"

echo ""
echo "[6/6] Done."
echo ""
echo "Transfer ${STAGE_NAME}.tar.gz to the offline server, then:"
echo "  tar -xzf ${STAGE_NAME}.tar.gz && cd ${STAGE_NAME}"
echo "  sudo bash scripts/install-native.sh        # panel"
echo "  sudo bash scripts/install-node-native.sh   # node"
echo ""
echo "Bundle size: $(du -h "$OUT" | cut -f1)"
