# syntax=docker/dockerfile:1

# ---- Browsers: Chromium for crawl4ai, cached independently of the app deps ----
# crawl4ai-setup downloads Chromium (~170 MB) into PLAYWRIGHT_BROWSERS_PATH. In
# the builder stage that RUN sits after `uv sync`, so every uv.lock change
# invalidated it and re-downloaded Chromium — measured as the difference
# between a 41s and a 458s image build on the home runner. This stage depends
# only on the Playwright version: the browser directory is pre-populated here
# and copied into the builder, where crawl4ai-setup finds the matching
# revision already present and skips the download. The final image is
# byte-identical to before (same /opt/browsers, produced by the same tool).
#
# PLAYWRIGHT_VERSION must match the `playwright` entry in uv.lock — a
# mismatch means a different browser revision and crawl4ai-setup downloads
# again. scripts/ci/check-playwright-pin.sh enforces it in CI.
FROM python:3.12-slim AS browsers
ARG PLAYWRIGHT_VERSION=1.60.0
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "playwright==${PLAYWRIGHT_VERSION}" \
    && playwright install chromium

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
COPY apps/api/pyproject.toml ./apps/api/
# Only libs' manifest is COPIED into the layer; the sources are bind-mounted
# into the uv sync step below. A COPY here made every edit under libs/shared
# invalidate the sync — and with it crawl4ai-setup and the runtime COPY
# --from layers, ~420s for a one-line library change (measured).
COPY libs/pyproject.toml ./libs/

# UV_PROJECT_ENVIRONMENT=/usr/local tells uv sync to use the system Python dir
# instead of creating a .venv — entry points (crawl4ai-setup etc.) land in /usr/local/bin
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=libs,target=/app/libs,rw \
    uv sync --frozen --package gaia --group backend

# crawl4ai post-install. The Chromium revision is already in place from the
# browsers stage, so this no longer downloads anything — it only runs
# crawl4ai's own setup against the present browser.
COPY --from=browsers /opt/browsers /opt/browsers
# crawl4ai-setup writes its post-install state under ~/.cache/crawl4ai; without
# a cache mount it redid that work on every deps change (measured 227s even
# with Chromium already present above).
RUN --mount=type=cache,target=/root/.cache/crawl4ai crawl4ai-setup

# ---- Runtime: minimal production image ----
FROM python:3.12-slim AS runtime
WORKDIR /app

# Install only runtime system libraries (no build-essential / *-dev)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
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

# Install the Chromium system-dependency set for the bundled Playwright browser.
# Using Playwright's own installer (not a hand-maintained apt list) keeps the
# deps correct across Debian releases — notably the trixie ``t64`` library
# renames (libatk-bridge-2.0-0t64, libcups2t64, libatspi2.0-0t64, …) that a
# static list misses. Their absence is what made crawl4ai's Chromium fail to
# launch ("libatk-bridge-2.0.so.0: cannot open shared object file"), silently
# degrading webpage fetch and deep research to the httpx fallback.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && playwright install-deps chromium

# Stamped onto every wide event as the `commit` field (see shared.py.wide_events
# env_context) so Loki queries can correlate errors with deploys.
ARG GIT_COMMIT_SHA=""

ENV ENV=production \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_SYSTEM_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    PYTHONPATH=/app/apps/api \
    PLAYWRIGHT_BROWSERS_PATH=/opt/browsers \
    GIT_COMMIT_SHA=${GIT_COMMIT_SHA}

# Copy workspace pyproject files (needed for uv run --group)
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml ./apps/api/
# The runtime needs the real sources: gaia-shared is an editable install here
# (see the chown note below), so this COPY stays — it is cheap (no sync
# depends on it in this stage).
COPY libs ./libs

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
    && chown -R appuser:appuser /etc/gaia /var/cache/juicefs /mnt/jfs \
    # Persistent fastembed model cache (MEMORY_MODEL_CACHE_DIR). Pre-created and
    # owned by appuser so a mounted named volume inherits writable ownership.
    && mkdir -p /models \
    && chown appuser:appuser /models

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
