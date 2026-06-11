ARG BACKHAUL_VERSION=v0.7.2
ARG BACKHAUL_SHA256_AMD64=57bf95c2eabeddb1152d2e94ac42f4310883ce0fb909ee2a57bd53503b2dabbc
ARG BACKHAUL_SHA256_ARM64=9a424c97ff16fc3f682e8314c418790d2b5bf3136e008edbb6cd402ea00999f6

# Stage 1: System dependencies
FROM python:3.11-slim AS base
RUN apt-get update && apt-get install -y \
    gcc \
    iptables \
    curl \
    unzip \
    gzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Stage 2: Install rathole (cached layer)
FROM base AS rathole-bin
RUN set -eux; \
    ARCH_RAW="$(uname -m)"; \
    case "$ARCH_RAW" in \
        x86_64) ARCH="amd64"; RATHOLE_ARCH="x86_64" ;; \
        aarch64) ARCH="arm64"; RATHOLE_ARCH="aarch64" ;; \
        *) ARCH="amd64"; RATHOLE_ARCH="x86_64" ;; \
    esac; \
    RATHOLE_URL="https://github.com/rapiz1/rathole/releases/download/v0.5.0/rathole-$RATHOLE_ARCH-unknown-linux-gnu.zip"; \
    TMP_DIR="$(mktemp -d)"; \
    curl -fsSL "$RATHOLE_URL" -o "$TMP_DIR/rathole.zip"; \
    unzip -q "$TMP_DIR/rathole.zip" -d "$TMP_DIR"; \
    RATHOLE_BIN="$(find "$TMP_DIR" -type f -name 'rathole' | head -n1)"; \
    install -Dm755 "$RATHOLE_BIN" /usr/local/bin/rathole; \
    rm -rf "$TMP_DIR"; \
    GOST_URL="https://github.com/ginuerzh/gost/releases/download/v2.12.0/gost_2.12.0_linux_${ARCH}.tar.gz"; \
    GOST_TMP="$(mktemp -d)"; \
    curl -fsSL "$GOST_URL" -o "$GOST_TMP/gost.tar.gz"; \
    tar -xzf "$GOST_TMP/gost.tar.gz" -C "$GOST_TMP"; \
    GOST_BIN="$(find "$GOST_TMP" -type f -name 'gost' | head -n1)"; \
    install -Dm755 "$GOST_BIN" /usr/local/bin/gost; \
    rm -rf "$GOST_TMP"; \
    echo "Fetching chisel release"; \
    CHISEL_URL="https://github.com/jpillora/chisel/releases/download/v1.11.3/chisel_1.11.3_linux_${ARCH}.gz"; \
    CHISEL_TMP="$(mktemp -d)"; \
    curl -fsSL "$CHISEL_URL" -o "$CHISEL_TMP/chisel.gz"; \
    gunzip "$CHISEL_TMP/chisel.gz"; \
    install -Dm755 "$CHISEL_TMP/chisel" /usr/local/bin/chisel; \
    rm -rf "$CHISEL_TMP"; \
    echo "Fetching FRP release"; \
    FRP_VERSION="v0.65.0"; \
    FRP_VERSION_NO_V="${FRP_VERSION#v}"; \
    FRP_URL="https://github.com/fatedier/frp/releases/download/${FRP_VERSION}/frp_${FRP_VERSION_NO_V}_linux_${ARCH}.tar.gz"; \
    FRP_TMP="$(mktemp -d)"; \
    curl -fsSL "$FRP_URL" -o "$FRP_TMP/frp.tar.gz"; \
    tar -xzf "$FRP_TMP/frp.tar.gz" -C "$FRP_TMP"; \
    FRPC_BIN="$(find "$FRP_TMP" -type f -name 'frpc' | head -n1)"; \
    if [ -n "$FRPC_BIN" ]; then \
        install -Dm755 "$FRPC_BIN" /usr/local/bin/frpc; \
    fi; \
    FRPS_BIN="$(find "$FRP_TMP" -type f -name 'frps' | head -n1)"; \
    if [ -n "$FRPS_BIN" ]; then \
        install -Dm755 "$FRPS_BIN" /usr/local/bin/frps; \
    fi; \
    rm -rf "$FRP_TMP"; \
    /usr/local/bin/rathole --version || true; \
    /usr/local/bin/gost -V || true; \
    /usr/local/bin/chisel --version || true; \
    /usr/local/bin/frpc --version || true; \
    /usr/local/bin/frps --version || true

# Stage 3: Install backhaul (cached layer)
FROM base AS backhaul-bin
ARG BACKHAUL_VERSION
ARG BACKHAUL_SHA256_AMD64
ARG BACKHAUL_SHA256_ARM64
RUN set -eux; \
    mkdir -p /opt/backhaul; \
    ARCH="$(uname -m)"; \
    case "$ARCH" in \
        x86_64|amd64) PLATFORM="amd64"; EXPECTED_SHA="$BACKHAUL_SHA256_AMD64" ;; \
        aarch64|arm64) PLATFORM="arm64"; EXPECTED_SHA="$BACKHAUL_SHA256_ARM64" ;; \
        *) echo "Unsupported architecture: $ARCH"; exit 1 ;; \
    esac; \
    ASSET_URL="https://github.com/Musixal/Backhaul/releases/download/${BACKHAUL_VERSION}/backhaul_linux_${PLATFORM}.tar.gz"; \
    TMP_DIR="$(mktemp -d)"; \
    curl -fsSL "$ASSET_URL" -o "$TMP_DIR/backhaul.tar.gz"; \
    echo "${EXPECTED_SHA}  $TMP_DIR/backhaul.tar.gz" | sha256sum -c -; \
    tar -xzf "$TMP_DIR/backhaul.tar.gz" -C "$TMP_DIR"; \
    BIN_PATH="$(find "$TMP_DIR" -type f -name 'backhaul' | head -n1)"; \
    if [ -z "$BIN_PATH" ]; then \
        echo "Backhaul binary not found in archive"; \
        ls -R "$TMP_DIR"; \
        exit 1; \
    fi; \
    install -Dm755 "$BIN_PATH" /opt/backhaul/backhaul; \
    rm -rf "$TMP_DIR"; \
    /opt/backhaul/backhaul --version || true

# Stage 3b: Install udp2raw (cached layer)
FROM base AS udp2raw-bin
ARG UDP2RAW_VERSION=20230206.0
RUN set -eux; \
    ARCH="$(uname -m)"; \
    case "$ARCH" in \
        x86_64|amd64) UDP2RAW_ASSET="udp2raw_amd64" ;; \
        aarch64|arm64) UDP2RAW_ASSET="udp2raw_arm" ;; \
        *) UDP2RAW_ASSET="udp2raw_amd64" ;; \
    esac; \
    TMP_DIR="$(mktemp -d)"; \
    curl -fsSL "https://github.com/wangyu-/udp2raw/releases/download/${UDP2RAW_VERSION}/udp2raw_binaries.tar.gz" -o "$TMP_DIR/udp2raw.tar.gz"; \
    tar -xzf "$TMP_DIR/udp2raw.tar.gz" -C "$TMP_DIR"; \
    BIN_PATH="$(find "$TMP_DIR" -type f -name "$UDP2RAW_ASSET" | head -n1)"; \
    if [ -z "$BIN_PATH" ]; then \
        echo "udp2raw binary $UDP2RAW_ASSET not found in archive"; \
        ls -R "$TMP_DIR"; \
        exit 1; \
    fi; \
    install -Dm755 "$BIN_PATH" /usr/local/bin/udp2raw; \
    rm -rf "$TMP_DIR"; \
    /usr/local/bin/udp2raw -h > /dev/null 2>&1 || true

# Stage 3c: Install zapret / nfqws (cached layer)
FROM base AS zapret-bin
ARG ZAPRET_VERSION=v72.12
RUN set -eux; \
    ARCH="$(uname -m)"; \
    case "$ARCH" in \
        x86_64|amd64) ZAPRET_ARCH="linux-x86_64" ;; \
        aarch64|arm64) ZAPRET_ARCH="linux-arm64" ;; \
        *) ZAPRET_ARCH="linux-x86_64" ;; \
    esac; \
    TMP_DIR="$(mktemp -d)"; \
    curl -fsSL "https://github.com/bol-van/zapret/releases/download/${ZAPRET_VERSION}/zapret-${ZAPRET_VERSION}.tar.gz" -o "$TMP_DIR/zapret.tar.gz"; \
    tar -xzf "$TMP_DIR/zapret.tar.gz" -C "$TMP_DIR"; \
    BIN_PATH="$(find "$TMP_DIR" -type f -path "*/binaries/${ZAPRET_ARCH}/nfqws" | head -n1)"; \
    if [ -z "$BIN_PATH" ]; then \
        echo "nfqws binary for ${ZAPRET_ARCH} not found in archive"; \
        find "$TMP_DIR" -type d -name binaries; \
        exit 1; \
    fi; \
    install -Dm755 "$BIN_PATH" /usr/local/bin/nfqws; \
    rm -rf "$TMP_DIR"; \
    /usr/local/bin/nfqws --help > /dev/null 2>&1 || true

# Stage 4: Python dependencies (cached layer)
FROM base AS deps
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# Stage 5: Final image
FROM base
WORKDIR /app

ARG SMITE_VERSION=latest
LABEL org.opencontainers.image.version="${SMITE_VERSION}"
LABEL smite.version="${SMITE_VERSION}"
ENV SMITE_VERSION="${SMITE_VERSION}"

# Copy binaries from binary stages
COPY --from=rathole-bin /usr/local/bin/rathole /usr/local/bin/rathole
COPY --from=rathole-bin /usr/local/bin/gost /usr/local/bin/gost
COPY --from=rathole-bin /usr/local/bin/chisel /usr/local/bin/chisel
COPY --from=rathole-bin /usr/local/bin/frpc /usr/local/bin/frpc
COPY --from=rathole-bin /usr/local/bin/frps /usr/local/bin/frps
COPY --from=backhaul-bin /opt/backhaul/backhaul /usr/local/bin/backhaul
COPY --from=udp2raw-bin /usr/local/bin/udp2raw /usr/local/bin/udp2raw
COPY --from=zapret-bin /usr/local/bin/nfqws /usr/local/bin/nfqws

# Copy Python dependencies from deps stage
COPY --from=deps /usr/local /usr/local

# Copy application code (changes most frequently)
COPY . .

EXPOSE 8888

RUN echo '#!/bin/sh' > /app/start.sh && \
    echo 'exec uvicorn main:app --host 0.0.0.0 --port "${NODE_API_PORT:-8888}" --log-level info --access-log' >> /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/bin/sh", "/app/start.sh"]
