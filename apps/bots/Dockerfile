# syntax=docker/dockerfile:1
# Parameterized bot Dockerfile — build with: --build-arg BOT_NAME=discord|slack|telegram

ARG BOT_NAME

FROM node:20-alpine AS builder
ARG BOT_NAME
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.17.1 --activate

# Copy workspace config + pnpm patch files. The patch sources must travel
# with the patchedDependencies declared in package.json/pnpm-lock.yaml —
# pnpm hashes every patch during --frozen-lockfile, even for deps this bot
# doesn't use. Copying the whole dir auto-includes any future patch.
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./
COPY patches ./patches

# Copy shared lib (bundled into output by tsup) and the target bot
COPY libs/shared/ts ./libs/shared/ts
COPY apps/bots/${BOT_NAME} ./apps/bots/${BOT_NAME}

# Install all dependencies for building
RUN --mount=type=cache,id=gaia-pnpm-bots,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# tsup bundles everything (including @gaia/shared and all npm deps) into a
# single self-contained output — no node_modules needed at runtime.
RUN pnpm --filter @gaia/bot-${BOT_NAME} build

# Photon's iMessage gRPC transport calls import.meta.resolve() on its peer deps
# at runtime, so those packages must exist on disk even though tsup already
# bundled their code. Only the iMessage bot needs them; the directory is always
# created so the COPY below works for every bot.
RUN set -e; \
    mkdir -p /peers/node_modules; \
    if [ "${BOT_NAME}" = "imessage" ]; then \
      for p in nice-grpc nice-grpc-common @grpc/grpc-js; do \
        src=""; \
        for base in "apps/bots/${BOT_NAME}/node_modules" "node_modules"; do \
          if [ -e "$base/$p" ]; then src="$base/$p"; break; fi; \
        done; \
        if [ -z "$src" ]; then echo "required gRPC peer not installed: $p" >&2; exit 1; fi; \
        mkdir -p "/peers/node_modules/$(dirname "$p")"; \
        cp -RL "$src" "/peers/node_modules/$p"; \
      done; \
    fi

# ---- Production image ----
FROM node:20-alpine AS runner
ARG BOT_NAME
WORKDIR /app

# Only the bundled dist is needed — no node_modules required
COPY --from=builder /app/apps/bots/${BOT_NAME}/dist ./dist
COPY --from=builder /app/apps/bots/${BOT_NAME}/package.json ./
COPY --from=builder /peers/ ./

# Entrypoint: reads Docker Swarm secrets into env vars before exec-ing the process
COPY scripts/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ENV is the Infisical environment slug the bots loader reads. Pin it here so a
# deployed container never falls back to the loader's development default;
# docker-compose.prod.yml sets it again per service, this covers everything else.
ENV NODE_ENV=production \
    ENV=production \
    BOT_NAME=${BOT_NAME}

USER node

ENTRYPOINT ["/entrypoint.sh"]
CMD ["node", "dist/index.js"]
