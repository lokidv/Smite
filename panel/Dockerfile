FROM python:3.11-slim AS base
RUN apt-get update && apt-get install -y \
    gcc \
    ca-certificates \
    git \
    curl \
    unzip \
    gzip \
    && rm -rf /var/lib/apt/lists/*

# Stage: Install FRP binaries
FROM base AS frp-bin
RUN set -eux; \
    ARCH_RAW="$(uname -m)"; \
    case "$ARCH_RAW" in \
        x86_64) ARCH="amd64" ;; \
        aarch64) ARCH="arm64" ;; \
        *) ARCH="amd64" ;; \
    esac; \
    echo "Fetching FRP release"; \
    FRP_VERSION="v0.65.0"; \
    FRP_VERSION_NO_V="${FRP_VERSION#v}"; \
    FRP_URL="https://github.com/fatedier/frp/releases/download/${FRP_VERSION}/frp_${FRP_VERSION_NO_V}_linux_${ARCH}.tar.gz"; \
    FRP_TMP="$(mktemp -d)"; \
    curl -fsSL "$FRP_URL" -o "$FRP_TMP/frp.tar.gz"; \
    tar -xzf "$FRP_TMP/frp.tar.gz" -C "$FRP_TMP"; \
    FRPS_BIN="$(find "$FRP_TMP" -type f -name 'frps' | head -n1)"; \
    if [ -n "$FRPS_BIN" ]; then \
        install -Dm755 "$FRPS_BIN" /usr/local/bin/frps; \
    fi; \
    rm -rf "$FRP_TMP"; \
    /usr/local/bin/frps --version || true

FROM node:18-alpine AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    if [ -f package-lock.json ]; then \
        npm ci --prefer-offline --no-audit --no-fund; \
    else \
        npm install --prefer-offline --no-audit --no-fund; \
    fi
COPY frontend ./
RUN npm run build

FROM base AS deps
WORKDIR /app
COPY panel/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

FROM base
WORKDIR /app

ARG SMITE_VERSION=latest
LABEL org.opencontainers.image.version="${SMITE_VERSION}"
LABEL smite.version="${SMITE_VERSION}"
ENV SMITE_VERSION="${SMITE_VERSION}"

# Copy FRP binary from frp-bin stage
COPY --from=frp-bin /usr/local/bin/frps /usr/local/bin/frps

COPY --from=deps /usr/local /usr/local
COPY --from=frontend-build /app/dist ./static
COPY panel .

# MUST come after `COPY panel .`. panel/VERSION is a file install-native.sh
# writes at install time; when a stale copy of it was committed it landed in the
# image and silently overwrote the version written from the build arg, so every
# published image reported the previous release's version.
RUN echo "${SMITE_VERSION}" > /app/VERSION
# Note: .git is excluded in .dockerignore, so git tag extraction at runtime won't work in Docker
# Version is set via SMITE_VERSION build arg (extract with: git describe --tags --abbrev=0)

EXPOSE 8000 443/tcp 443/udp

RUN echo '#!/bin/sh' > /app/start.sh && \
    echo 'set -e' >> /app/start.sh && \
    echo 'exec uvicorn main:app --host "${PANEL_HOST:-0.0.0.0}" --port "${PANEL_PORT:-8000}"' >> /app/start.sh && \
    chmod +x /app/start.sh

CMD ["/bin/sh", "/app/start.sh"]
