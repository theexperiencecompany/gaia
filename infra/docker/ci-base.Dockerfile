# Node version is declared once in .node-version. Docker cannot read a file in a
# FROM line, so this default mirrors it and tools/lints/check_tool_pins.py fails
# if the two disagree. Build scripts may override with --build-arg NODE_VERSION.
ARG NODE_VERSION=24.22.1
FROM node:${NODE_VERSION}-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 python3-pip python3-venv python3-dev \
       git curl build-essential libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@10.17.1 --activate

RUN pip install --break-system-packages uv
