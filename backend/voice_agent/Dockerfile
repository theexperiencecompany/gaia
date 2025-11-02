# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.11
# Fast Python builds using uv on Debian bookworm-slim
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base

ARG UID=10001

# Ensures that logs are captured in realtime
ENV PYTHONUNBUFFERED=1
WORKDIR /app
ENV PYTHONPATH=/app

# create unprivileged user
RUN adduser \
  --disabled-password \
  --gecos "" \
  --home "/app" \
  --shell "/sbin/nologin" \
  --uid "${UID}" \
  appuser

# system deps for building wheels
RUN apt-get update && apt-get install -y \
  gcc \
  python3-dev \
  && rm -rf /var/lib/apt/lists/*

# 1) Install Python dependencies (copy lock/pyproject from repo root context)
COPY backend/voice_agent/pyproject.toml backend/voice_agent/uv.lock ./
RUN mkdir -p src
RUN uv sync --locked

# 2) Copy service code into image
COPY backend/voice_agent/. /app

# 3) Copy the parent backend app module so voice agent can import settings
#    This allows: from app.config.settings import settings
COPY backend/app /app/app

# 4) Ensure the top-level backend .env is available at build time so "download-files" can use it
#    (compose uses project root as context; backend/.env exists there)
COPY backend/.env /app/.env

# Set proper ownership and switch to non-root user
RUN chown -R appuser:appuser /app
USER appuser

# 5) Pre-download heavy models/assets at build time.
RUN uv run -m src.voice_agent download-files

# 6) Default command - run in dev mode by default (compose overrides command)
CMD ["uv", "run", "-m", "src.voice_agent", "dev"]
