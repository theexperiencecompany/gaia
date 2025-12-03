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

# ---- Extraction Stage: Extract heavy dependencies ----
FROM base AS extract
WORKDIR /app

# Install tomli for parsing
RUN pip install tomli

# Copy only pyproject.toml for extraction
COPY pyproject.toml ./
COPY scripts/extract_heavy_deps.py ./

# Run script to extract heavy dependencies
RUN python extract_heavy_deps.py && \
  rm -rf /root/.cache/pip

# ---- Heavy Dependencies Stage ----
FROM base AS heavy-dependencies
WORKDIR /app

# Copy only the extracted dependencies file, not pyproject.toml
COPY --from=extract /app/heavy-deps.txt ./

# Run script to extract and install heavy dependencies
RUN uv pip install --system --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
  uv pip install --system --no-cache-dir -r heavy-deps.txt && \
  rm -rf /root/.cache/pip

# ---- Default Dependencies Stage: Install default application dependencies ----
FROM heavy-dependencies AS default-dependencies
WORKDIR /app

# Copy only the pyproject.toml for default dependencies
COPY pyproject.toml ./

# Set environment variables
ENV ENV=production \
  UV_COMPILE_BYTECODE=1 \
  UV_LINK_MODE=copy \
  UV_SYSTEM_PYTHON=1 \
  UV_LOGGING=1

# Install default dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
  if [ "$ENV" = "production" ]; then \
  uv pip install --no-cache-dir .; \
  else \
  uv pip install --no-cache-dir --editable . ; \
  fi

# Setup crawl4ai browser dependencies
RUN crawl4ai-setup

# ---- Final Stage: Setup application for production ----
FROM default-dependencies AS final
WORKDIR /app

# Setup non-root user and permissions
RUN adduser --disabled-password --gecos '' appuser \
  && mkdir -p /home/appuser/.cache \
  && chown -R appuser:appuser /home/appuser \
  && mkdir -p /app/logs \
  && chown -R appuser:appuser /app/logs

# Copy application code with proper ownership
COPY --chown=appuser:appuser . .

USER appuser
EXPOSE 8000


CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000","--no-access-log"]