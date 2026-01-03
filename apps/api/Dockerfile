# ---- Base Stage: Contains system dependencies ----
FROM python:3.12-slim AS base
WORKDIR /app

# Copy uv installer
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install system dependencies
RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  build-essential \
  libnss3 libatk1.0-0 libx11-xcb1 libxcb-dri3-0 \
  libdrm2 libxcomposite1 libxdamage1 libxrandr2 \
  libgbm1 libasound2 curl unzip tesseract-ocr libpq-dev \
  libdbus-1-3 \
  pandoc \
  texlive-xetex \
  texlive-fonts-recommended \
  texlive-latex-recommended \
  texlive-latex-extra \
  lmodern \
  texlive-plain-generic && \
  rm -rf /var/lib/apt/lists/*

# ---- Dependencies Stage: Install application dependencies ----
FROM base AS dependencies
WORKDIR /app

# Copy workspace structure for uv to resolve dependencies
COPY pyproject.toml uv.lock ./
COPY libs ./libs
COPY apps/api/pyproject.toml ./apps/api/

# Set environment variables
ENV ENV=production \
  UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy \
  UV_SYSTEM_PYTHON=1 \
  UV_LOGGING=1 \
  PYTHONPATH=/app/apps/api

# Install crawl4ai browser dependencies
RUN pip install crawl4ai && crawl4ai-setup && rm -rf /root/.cache/pip

# Install torch from CPU index first, then backend dependencies via workspace sync
RUN --mount=type=cache,target=/root/.cache/uv \
  uv pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
  uv sync --frozen --package gaia --group backend

# ---- Final Stage: Setup application for production ----
FROM dependencies AS final
WORKDIR /app

# Setup non-root user and permissions
RUN adduser --disabled-password --gecos '' appuser \
  && mkdir -p /home/appuser/.cache \
  && chown -R appuser:appuser /home/appuser \
  && mkdir -p /app/apps/api/logs \
  && chown -R appuser:appuser /app

# Copy API application code with proper ownership
COPY --chown=appuser:appuser apps/api/app ./apps/api/app

WORKDIR /app/apps/api

USER appuser
EXPOSE 8000

CMD ["uv", "run", "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]