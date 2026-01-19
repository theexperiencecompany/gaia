FROM node:20-alpine AS builder

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy workspace config
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./

# Copy packages
COPY libs/shared/ts ./libs/shared/ts
COPY apps/bots/slack ./apps/bots/slack

# Install dependencies
RUN pnpm install --frozen-lockfile

# Build shared lib and bot
RUN pnpm --filter @gaia/shared build
RUN pnpm --filter @gaia/bot-slack build

# Production image
FROM node:20-alpine AS runner

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy built artifacts and necessary files
COPY --from=builder /app/package.json /app/pnpm-lock.yaml /app/pnpm-workspace.yaml ./
COPY --from=builder /app/libs/shared/ts/package.json ./libs/shared/ts/package.json
COPY --from=builder /app/libs/shared/ts/dist ./libs/shared/ts/dist
COPY --from=builder /app/apps/bots/slack/package.json ./apps/bots/slack/package.json
COPY --from=builder /app/apps/bots/slack/dist ./apps/bots/slack/dist

# Install only prod deps
RUN pnpm install --prod --frozen-lockfile

ENV NODE_ENV=production

CMD ["node", "apps/bots/slack/dist/index.js"]
