# syntax=docker/dockerfile:1

# ---- Browsers: every browser crawl4ai needs, keyed ONLY on tool versions ----
# `crawl4ai-setup` is a thin wrapper (crawl4ai/install.py:post_install). Its
# browser half is exactly two commands:
#
#     python -m playwright  install --with-deps --force chromium
#     python -m patchright  install --with-deps --force chromium
#
# `--force` is why the old browsers stage never saved a byte: playwright
# re-downloads unconditionally, present revision or not (run1.log #19 —
# chromium-1223 + ffmpeg-1011 + chromium_headless_shell-1223 + patchright's
# chromium-1200 + chromium_headless_shell-1200, ~285 MiB, 226s, on top of an
# already-populated /opt/browsers). `--with-deps` is the other 67s: an apt
# install of the X11/mesa/font stack into the *builder* rootfs, which the
# runtime never copies — it installs its own set via `playwright
# install-deps chromium` further down.
#
# So we run the two installs here ourselves, without --force and without
# --with-deps. Two download sets are genuinely required: playwright 1.60.0
# validates chromium build v1223 and patchright 1.57.2 validates build v1200;
# each refuses the other's revision. But they are downloaded once and this
# stage is invalidated ONLY by the two ARGs below — never by uv.lock, libs/
# or app code.
#
# PLAYWRIGHT_VERSION / PATCHRIGHT_VERSION must equal the uv.lock entries: a
# drift means the runtime's crawl4ai looks for a revision that is not in
# /opt/browsers and Chromium fails to launch. scripts/ci/audit.sh playwright-pin
# enforces both in CI, and unlike before the pin is load-bearing — nothing
# downloads browsers at runtime to paper over a mismatch.
FROM python:3.12-slim AS browsers
ARG PLAYWRIGHT_VERSION=1.60.0
ARG PATCHRIGHT_VERSION=1.57.2
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --only-binary :all: "playwright==${PLAYWRIGHT_VERSION}" "patchright==${PATCHRIGHT_VERSION}" \
    && python -m playwright install chromium \
    && python -m patchright install chromium

# ---- Builder: install the Python dependency closure (no browsers here) ----
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
    UV_PROJECT_ENVIRONMENT=/usr/local

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

# NOTE: crawl4ai-setup deliberately does NOT run here. Its browser downloads
# live in the `browsers` stage (keyed on tool versions, not uv.lock) and its
# home-directory/db half runs in the runtime stage as the user that actually
# reads it. Running it here cost 244s per uv.lock change and shipped nothing:
# the state went to /root/.crawl4ai inside a discarded builder rootfs, and the
# `--mount=type=cache,target=/root/.cache/crawl4ai` guarding it pointed at a
# path crawl4ai never writes.

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

# Copy crawl4ai browser data (playwright chromium + patchright chromium)
COPY --from=browsers /opt/browsers /opt/browsers

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
# (see the chown note below), so the sources must ship. Narrowed to what the
# editable install actually exposes — libs/pyproject.toml declares
# `packages.find include = ["shared*"]`, and apps/api only ever imports
# `shared` / `shared.py.*`. This drops libs/shared/ts (1.2 MB of TypeScript)
# and libs/wake-word (880 KB), neither of which is a Python package.
COPY libs/pyproject.toml ./libs/
COPY libs/shared/__init__.py libs/shared/py.typed ./libs/shared/
COPY libs/shared/py ./libs/shared/py
COPY libs/shared/assets ./libs/shared/assets

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

# The non-browser half of crawl4ai-setup: the ~/.crawl4ai skeleton and its
# sqlite db. It must be created for `appuser`, not root — the old builder wrote
# it to /root/.crawl4ai and then threw the rootfs away, so the running
# container built it lazily on the first crawl. HOME is set explicitly because
# crawl4ai resolves the location through Path.home().
RUN HOME=/home/appuser python -c "from crawl4ai.install import setup_home_directory, run_migration; setup_home_directory(); run_migration()" \
    && chown -R appuser:appuser /home/appuser/.crawl4ai /home/appuser/global.yml

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
