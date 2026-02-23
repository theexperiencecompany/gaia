# syntax=docker/dockerfile:1
FROM node:24-alpine AS base
RUN npm install -g pnpm

# ===================================
# Stage 1: Builder
# Uses BuildKit cache mount for the pnpm store so packages
# are cached across builds even when source files change.
# Single pnpm install — no two-stage copy complexity.
# ===================================
FROM base AS builder
WORKDIR /app

ENV CI=true
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

# Copy all package manifests first for better cache signal.
# The RUN --mount cache below persists regardless, but putting
# manifests before source means the cache key changes only on
# lockfile/package.json changes.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json         ./apps/web/
COPY apps/desktop/package.json     ./apps/desktop/
COPY apps/mobile/package.json      ./apps/mobile/
COPY apps/bots/discord/package.json ./apps/bots/discord/
COPY apps/bots/slack/package.json  ./apps/bots/slack/
COPY apps/bots/telegram/package.json ./apps/bots/telegram/
COPY packages/cli/package.json     ./packages/cli/
COPY libs/shared/ts/package.json   ./libs/shared/ts/

# Copy source (.dockerignore excludes **/node_modules, **/.next, etc.)
COPY . .

# Install with a persistent pnpm store cache.
# On cache hit: pnpm reuses downloaded tarballs — install is ~10s.
# On cache miss: full download, same as before.
RUN --mount=type=cache,id=gaia-pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile --store-dir /pnpm/store

# Build argument for Next.js public env var (baked into static build)
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1/
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

WORKDIR /app/apps/web
RUN pnpm build

# ===================================
# Stage 2: Runner
# next.config.mjs has output: "standalone" which bundles all
# runtime deps into .next/standalone — no pnpm or node_modules
# needed in the final image.
# ===================================
FROM node:24-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000

RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/static     ./apps/web/.next/static
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/public            ./apps/web/public

USER nextjs

EXPOSE 3000

CMD ["node", "apps/web/server.js"]
