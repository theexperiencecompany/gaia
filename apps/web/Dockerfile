# syntax=docker/dockerfile:1
# Browser-facing API base baked into the bundle. Same-origin by default: the
# self-host proxy serves /api/v1 beside the app, so one image works on any
# hostname, IP or port with no runtime rewrite. Server-side code reaches the
# API through API_BASE_URL_INTERNAL instead.
ARG NEXT_PUBLIC_API_BASE_URL=/api/v1/

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

ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
# This image is the self-host package: the flag is inlined at build time so
# server and browser agree with no runtime probe (see src/lib/selfhost.ts).
ENV NEXT_PUBLIC_GAIA_SELFHOST=true

WORKDIR /app/apps/web
# Bound the Node heap for the production build. Next.js fans static rendering
# out across every core, and on a 6-8 GB self-host box the combined heaps OOM
# mid-compile (measured: SIGKILL building gaia-web on a 6 GB host). The cap
# only forces earlier GC — output is identical, and big CI builders can raise
# it per build. Workers inherit NODE_OPTIONS, so one variable covers all.
ARG NEXT_BUILD_MAX_OLD_SPACE_MB=3072
ENV NODE_OPTIONS=--max-old-space-size=${NEXT_BUILD_MAX_OLD_SPACE_MB}
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
# The standalone server binds to $HOSTNAME, which Docker sets to the container
# id — so localhost (the healthcheck) was refused. Listen on every interface.
ENV HOSTNAME=0.0.0.0
RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/.next/static     ./apps/web/.next/static
COPY --from=builder --chown=nextjs:nodejs /app/apps/web/public            ./apps/web/public

USER nextjs

EXPOSE 3000

CMD ["node", "apps/web/server.js"]
