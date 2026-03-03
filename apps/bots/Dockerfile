# syntax=docker/dockerfile:1
# Parameterized bot Dockerfile — build with: --build-arg BOT_NAME=discord|slack|telegram

ARG BOT_NAME

FROM node:20-alpine AS builder
ARG BOT_NAME
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.17.1 --activate

# Copy workspace config
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./

# Copy shared lib and the target bot
COPY libs/shared/ts ./libs/shared/ts
COPY apps/bots/${BOT_NAME} ./apps/bots/${BOT_NAME}

# Install all dependencies for building
RUN --mount=type=cache,id=gaia-pnpm-bots,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# Build shared lib and bot in one layer
RUN pnpm --filter @gaia/shared build && \
    pnpm --filter @gaia/bot-${BOT_NAME} build

# Deploy with production-only deps scoped to just this bot (eliminates workspace root deps)
# --legacy is required by pnpm v10 for non-injected workspace packages
RUN --mount=type=cache,id=gaia-pnpm-bots,target=/root/.local/share/pnpm/store \
    pnpm --filter @gaia/bot-${BOT_NAME} deploy --prod --legacy /deploy

# ---- Production image ----
FROM node:20-alpine AS runner
ARG BOT_NAME
WORKDIR /app

# The deploy directory contains package.json, dist/, and a scoped node_modules
COPY --from=builder /deploy ./

ENV NODE_ENV=production \
    BOT_NAME=${BOT_NAME}

USER node

CMD node dist/index.js
