# Shared Dockerfile for all GAIA bots (Discord, Slack, Telegram)
# Usage: docker build --build-arg BOT_NAME=discord -f apps/bots/Dockerfile -t gaia-bot-discord .

ARG BOT_NAME
FROM node:20-alpine AS builder

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy workspace config
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./

# Copy packages
COPY libs/shared/ts ./libs/shared/ts
ARG BOT_NAME
COPY apps/bots/${BOT_NAME} ./apps/bots/${BOT_NAME}

# Install dependencies
RUN pnpm install --frozen-lockfile

# Build shared lib and bot
RUN pnpm --filter @gaia/shared build
ARG BOT_NAME
RUN pnpm --filter @gaia/bot-${BOT_NAME} build

# Production image
FROM node:20-alpine AS runner

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy built artifacts and necessary files
COPY --from=builder /app/package.json /app/pnpm-lock.yaml /app/pnpm-workspace.yaml ./
COPY --from=builder /app/libs/shared/ts/package.json ./libs/shared/ts/package.json
COPY --from=builder /app/libs/shared/ts/dist ./libs/shared/ts/dist
ARG BOT_NAME
COPY --from=builder /app/apps/bots/${BOT_NAME}/package.json ./apps/bots/${BOT_NAME}/package.json
COPY --from=builder /app/apps/bots/${BOT_NAME}/dist ./apps/bots/${BOT_NAME}/dist

# Install only prod deps
RUN pnpm install --prod --frozen-lockfile

ENV NODE_ENV=production
ARG BOT_NAME

CMD node apps/bots/${BOT_NAME}/dist/index.js
