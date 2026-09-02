# syntax=docker/dockerfile:1
FROM node:24-alpine AS base
# Pinned via corepack, same as apps/bots/Dockerfile. Unpinned `npm install -g
# pnpm` pulled pnpm 11 against this repo's pnpm@10 lockfile and the install
# died on native-binary identity verification (the never-run-unpinned lesson
# from .github/CLAUDE.md). Keep in sync with package.json `packageManager`.
RUN corepack enable && corepack prepare pnpm@10.17.1 --activate

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
# patches/ too: root package.json's pnpm.patchedDependencies references
# these files — install fails with ENOENT without them (proved in CI:
# "pnpm: ENOENT ... /app/patches/dmg-builder.patch").
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY patches ./patches/
COPY apps/web/package.json         ./apps/web/
COPY apps/desktop/package.json     ./apps/desktop/
COPY apps/mobile/package.json      ./apps/mobile/
COPY apps/bots/discord/package.json ./apps/bots/discord/
COPY apps/bots/slack/package.json  ./apps/bots/slack/
COPY apps/bots/telegram/package.json ./apps/bots/telegram/
COPY packages/cli/package.json     ./packages/cli/
COPY libs/shared/ts/package.json   ./libs/shared/ts/
COPY libs/wake-word/package.json   ./libs/wake-word/

# Install BEFORE copying source. Consider the two layouts on a fresh
# GitHub-hosted runner (BuildKit cache mounts start EMPTY every job):
#   old: COPY . . then install -> every commit re-ran the full install;
#   new: manifests then install -> the install RUN layer is served from the
#        registry layer cache (build-push-action cache-from type=registry,
#        ghcr gaia-web:buildcache) and only
#        re-runs when a manifest/lockfile changes.
RUN --mount=type=cache,id=gaia-pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile --store-dir /pnpm/store

# Copy source (.dockerignore excludes **/node_modules, **/.next, etc.)
COPY . .

# Build-time API URL baked into the JS bundle. At container startup,
# docker-entrypoint.sh replaces this placeholder with the real URL
# derived from NEXT_PUBLIC_APP_URL, so one image works on any port.
ARG NEXT_PUBLIC_API_BASE_URL=http://preview.placeholder.buildtime/api/v1/
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

COPY --chown=nextjs:nodejs apps/web/docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

USER nextjs

EXPOSE 3000

CMD ["sh", "./docker-entrypoint.sh"]
