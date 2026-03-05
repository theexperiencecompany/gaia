# syntax=docker/dockerfile:1
# Voice Agent Dockerfile - multi-stage to keep build tools out of runtime
# Build from repo root with: docker build -f apps/voice-agent/Dockerfile .

# ---- Builder: compile Python packages ----
FROM python:3.12-slim AS builder
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /uvx /bin/

# Build-time deps (not shipped to production)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    libglib2.0-0

# Create appuser so the venv it creates in /app is owned correctly
RUN adduser --disabled-password --gecos '' --uid 1000 appuser \
    && chown appuser:appuser /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY apps/voice-agent/pyproject.toml ./apps/voice-agent/

# setuptools needs write access to libs/ to create gaia_shared.egg-info during editable install
# Run as root here (before USER appuser) so chown succeeds on the root-owned copies
RUN chown -R appuser:appuser /app/libs

USER appuser

RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000 \
    uv sync --frozen --package gaia-voice-agent

# ---- Runtime: minimal production image ----
FROM python:3.12-slim AS runtime
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /uvx /bin/

# Runtime-only system libs — no build-essential or *-dev packages
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libpq5 \
    curl

# Create appuser with same UID so copied venv ownership is consistent
RUN adduser --disabled-password --gecos '' --uid 1000 appuser \
    && mkdir -p /home/appuser/.cache/huggingface \
    && chown -R appuser:appuser /home/appuser \
    && chown appuser:appuser /app

# Copy venv from builder (already owned by appuser — no chown layer needed)
COPY --from=builder /app/.venv /app/.venv

# Copy workspace files needed for uv run
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY apps/voice-agent/pyproject.toml ./apps/voice-agent/

# setuptools needs write access to libs/ to create gaia_shared.egg-info
RUN chown -R appuser:appuser /app/libs

USER appuser

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy app source (root-owned, readable by appuser)
COPY apps/voice-agent/src/ ./apps/voice-agent/src/

WORKDIR /app/apps/voice-agent

# Download model files (into /home/appuser/.cache/huggingface)
RUN uv run --frozen python -m src download-files

CMD ["uv", "run", "--frozen", "python", "-m", "src", "start"]
