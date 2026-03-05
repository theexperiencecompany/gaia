# syntax=docker/dockerfile:1
# Parameterized bot Dockerfile — build with: --build-arg BOT_NAME=discord|slack|telegram

ARG BOT_NAME

FROM node:20-alpine AS builder
ARG BOT_NAME
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.17.1 --activate

# Copy workspace config
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./

# Copy shared lib (bundled into output by tsup) and the target bot
COPY libs/shared/ts ./libs/shared/ts
COPY apps/bots/${BOT_NAME} ./apps/bots/${BOT_NAME}

# Install all dependencies for building
RUN --mount=type=cache,id=gaia-pnpm-bots,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# tsup bundles everything (including @gaia/shared and all npm deps) into a
# single self-contained output — no node_modules needed at runtime.
RUN pnpm --filter @gaia/bot-${BOT_NAME} build

# ---- Production image ----
FROM node:20-alpine AS runner
ARG BOT_NAME
WORKDIR /app

# Only the bundled dist is needed — no node_modules required
COPY --from=builder /app/apps/bots/${BOT_NAME}/dist ./dist
COPY --from=builder /app/apps/bots/${BOT_NAME}/package.json ./

ENV NODE_ENV=production \
    BOT_NAME=${BOT_NAME}

USER node

CMD ["node", "dist/index.js"]
