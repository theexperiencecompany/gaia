# syntax=docker/dockerfile:1

# ---- Builder: compile dependencies and download browser ----
FROM python:3.12-slim AS builder
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /uvx /bin/

# Install build-time only system deps (not shipped to production)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_SYSTEM_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    PLAYWRIGHT_BROWSERS_PATH=/opt/browsers

# Copy workspace structure for uv to resolve dependencies
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY apps/api/pyproject.toml ./apps/api/

# UV_PROJECT_ENVIRONMENT=/usr/local tells uv sync to use the system Python dir
# instead of creating a .venv — entry points (crawl4ai-setup etc.) land in /usr/local/bin
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package gaia --group backend

# Download crawl4ai browser (Chromium via Playwright)
RUN crawl4ai-setup

# ---- Runtime: minimal production image ----
FROM python:3.12-slim AS runtime
WORKDIR /app

# Install only runtime system libraries (no build-essential / *-dev)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libnss3 libatk1.0-0 libx11-xcb1 libxcb-dri3-0 \
    libdrm2 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libasound2 libdbus-1-3 \
    tesseract-ocr \
    fuse3 \
    postgresql-client \
    curl

# JuiceFS client — needed by the host-side sidecar mount that the API writes
# skills + migration data through. Sandboxes have their own copy baked into
# the E2B template.
# Arch-aware: TARGETARCH is auto-populated by BuildKit (amd64/arm64). Using a
# native binary matters — the amd64 build crashes (Go runtime abort in the PG
# meta client) under Rosetta/QEMU emulation on arm64 hosts (Apple Silicon
# dev, Graviton prod).
ARG JUICEFS_VERSION=1.3.0
ARG TARGETARCH
RUN curl -fsSL "https://github.com/juicedata/juicefs/releases/download/v${JUICEFS_VERSION}/juicefs-${JUICEFS_VERSION}-linux-${TARGETARCH:-amd64}.tar.gz" \
    | tar -xz -C /tmp \
    && install -m 0755 /tmp/juicefs /usr/local/bin/juicefs \
    && rm -rf /tmp/juicefs /tmp/LICENSE /tmp/README.md

# Copy uv binary (pinned version)
COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /uvx /bin/

# Copy Python packages and entry points from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy crawl4ai browser data from builder
COPY --from=builder /opt/browsers /opt/browsers

ENV ENV=production \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_SYSTEM_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    PYTHONPATH=/app/apps/api \
    PLAYWRIGHT_BROWSERS_PATH=/opt/browsers

# Copy workspace pyproject files (needed for uv run --group)
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY apps/api/pyproject.toml ./apps/api/

# Setup non-root user and permissions
# - libs needs to be writable so setuptools can create gaia_shared.egg-info during editable install
# - /app/uv.lock and /app/pyproject.toml need to be writable because `uv run` may touch the
#   lockfile even when nothing changed (e.g. metadata refresh). Failing back to read-only
#   produces "Permission denied" on every invocation in the running container.
RUN adduser --disabled-password --gecos '' appuser \
    && mkdir -p /home/appuser/.cache \
    && chown -R appuser:appuser /home/appuser \
    && mkdir -p /app/apps/api/logs \
    && chown appuser:appuser /app/apps/api/logs \
    && chown -R appuser:appuser /app/libs \
    && chown appuser:appuser /app/uv.lock /app/pyproject.toml \
    && mkdir -p /etc/gaia /var/cache/juicefs /mnt/jfs \
    && chown -R appuser:appuser /etc/gaia /var/cache/juicefs /mnt/jfs

# Copy API application code (root-owned, readable by appuser)
COPY apps/api/app ./apps/api/app
COPY apps/api/scripts ./apps/api/scripts

# Entrypoint: reads Docker Swarm secrets into env vars before exec-ing the process
COPY scripts/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /app/apps/api

USER appuser
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
