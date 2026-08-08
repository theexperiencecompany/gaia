#!/usr/bin/env bash
#
# Environment for booting apps/api against scripts/dev/sandbox-services.sh.
#
#   source scripts/dev/sandbox-env.sh
#   cd apps/api && uv run uvicorn app.main:app --port 8000
#
# There is no apps/api/.env in a fresh sandbox, and settings validation fails
# closed, so the app will not start without these. Every value here is a
# throwaway for local use — never reuse any of them anywhere real.
#
# LOG_FORMAT selects which of the two logging shapes you get, and they are
# genuinely different code paths — test both:
#
#   LOG_FORMAT=json   stdout NDJSON, no files. What containers run and what
#                     Promtail ships to Loki. configure_file_logging() no-ops.
#   (unset)           human console + rotating files under apps/api/logs/,
#                     including structured-<date>.json. What a dev reads locally.

export ENV=development

# Deliberately NOT setting GAIA_SERVICE_NAME. Each service names itself via
# os.environ.setdefault at its own entrypoint (apps/api/app/workers/lifecycle/
# startup.py -> arq_worker, apps/voice-agent/src/agent.py -> voice-agent-worker);
# the API falls back to gaia-backend. Exporting it here would win over every one
# of those defaults and silently relabel the worker and the voice agent as
# gaia-backend — which is exactly what happened, and what production does not do,
# since no compose file sets it either.

# Dev auth bypass. The target email must resolve to a real Mongo user or every
# request 401s ("Dev bypass target has no Mongo user"). Mint it once the API is
# up:  curl -X POST localhost:8000/api/v1/dev/users \
#        -H 'content-type: application/json' \
#        -d '{"email":"dev@gaia.local","name":"Dev User"}'
# Then impersonate anyone per-request with the X-Dev-User header.
export DEV_AUTH_BYPASS_EMAIL=dev@gaia.local

# Backing services from sandbox-services.sh. The database the app actually uses
# is GAIA — the name in this URI's path is not what the repositories read.
export MONGO_DB="mongodb://localhost:27017/gaia_local?serverSelectionTimeoutMS=2000&connectTimeoutMS=2000"
export REDIS_URL="redis://localhost:6379/0"
export RABBITMQ_URL="amqp://guest:guest@localhost:5672/"
export CHROMADB_HOST=127.0.0.1
export CHROMADB_PORT=8080

# Required by settings validation; all fake. WORKOS_COOKIE_PASSWORD and the
# secrets have minimum-length constraints, hence the padding.
export WORKOS_API_KEY=sandbox-placeholder-workos-key               # pragma: allowlist secret
export WORKOS_CLIENT_ID=client_fake
export WORKOS_COOKIE_PASSWORD=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export MCP_ENCRYPTION_KEY="dGVzdF9lbmNyeXB0aW9uX2tleV8zMl9ieXRlcw=="  # pragma: allowlist secret
export AGENT_SECRET="sandbox-agent-secret-xxxxxxxxxxxxxxxx"           # pragma: allowlist secret
export BOT_SESSION_TOKEN_SECRET="sandbox-bot-secret-xxxxxxxxxxxxxxxx" # pragma: allowlist secret
export E2B_DOMAIN="e2b.dev"

# Embeddings are constructed at startup (GoogleGenerativeAIEmbeddings) and the
# triggers store refuses to initialize without them. Construction does not call
# the API, so a placeholder clears startup; anything that actually embeds will
# fail at call time, which is the honest failure mode for a sandbox.
export GOOGLE_API_KEY="sandbox-placeholder-not-a-real-key"            # pragma: allowlist secret
