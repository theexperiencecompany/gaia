# Voice Agent Dockerfile
# Build from repo root with: docker build -f apps/voice-agent/Dockerfile .

FROM python:3.12-slim AS base
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies
RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  build-essential \
  curl \
  libpq-dev \
  libglib2.0-0 && \
  rm -rf /var/lib/apt/lists/*

# Environment variables
ENV PYTHONUNBUFFERED=1 \
  UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy \
  UV_SYSTEM_PYTHON=1

# Copy workspace structure for uv to resolve dependencies
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY apps/voice-agent/pyproject.toml ./apps/voice-agent/

# Install dependencies from pyproject.toml using workspace sync
RUN --mount=type=cache,target=/root/.cache/uv \
  uv sync --frozen --package gaia-voice-agent

# Copy app source
COPY apps/voice-agent/src/ ./apps/voice-agent/src/

WORKDIR /app/apps/voice-agent

# Setup non-root user
RUN adduser --disabled-password --gecos '' appuser \
  && mkdir -p /home/appuser/.cache/huggingface \
  && chown -R appuser:appuser /home/appuser \
  && chown -R appuser:appuser /app

USER appuser

# Download model files
RUN uv run python -m src download-files

CMD ["uv", "run", "python", "-m", "src", "start"]
