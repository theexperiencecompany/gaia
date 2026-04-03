# infra/docker

Docker Compose configuration for all GAIA environments.

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Local development — profile-gated app services, infra always on |
| `docker-compose.prod.yml` | Production — pulls pre-built images from ghcr.io |
| `docker-compose.selfhost.yml` | Self-hosting — builds from source, includes web frontend |
| `observability/` | Config files for Prometheus, Loki, Promtail, Grafana, Blackbox |

## Port Mappings (defaults, overridable via .env)

| Service | Host Port | Container Port | Override Var |
|---|---|---|---|
| API (gaia-backend) | 8000 | 80 (dev) / 8000 (selfhost) | `API_HOST_PORT` |
| ChromaDB | 8080 | 8000 | `CHROMADB_HOST_PORT` |
| PostgreSQL | 5432 | 5432 | `POSTGRES_HOST_PORT` |
| Redis | 6379 | 6379 | `REDIS_HOST_PORT` |
| MongoDB | 27017 | 27017 | `MONGO_HOST_PORT` |
| RabbitMQ AMQP | 5672 | 5672 | `RABBITMQ_HOST_PORT` |
| RabbitMQ Management UI | 15672 | 15672 | `RABBITMQ_MGMT_PORT` |
| RabbitMQ Prometheus | 15692 | 15692 | `RABBITMQ_PROM_PORT` |
| Mongo Express | 8083 | 8081 | `MONGO_EXPRESS_HOST_PORT` |
| Grafana | 4000 | 3000 | `GRAFANA_HOST_PORT` |
| Loki | 3100 | 3100 | `LOKI_HOST_PORT` |
| Web (selfhost only) | 3000 | 3000 | `WEB_HOST_PORT` |
| WhatsApp webhook | 3001 | 3001 | `WHATSAPP_WEBHOOK_PORT` |

## Key Commands

```bash
# Via Nx (preferred — auto-loads .env if present)
nx docker:up docker
nx docker:down docker
nx docker:restart docker
nx docker:logs docker
nx docker:ps docker

# Direct Docker Compose (from infra/docker/)
docker compose up -d
docker compose --profile backend up -d   # backend + infra
docker compose --profile worker up -d    # arq_worker + infra
docker compose --profile voice up -d     # voice-agent + infra
docker compose --profile bots up -d      # discord/slack/telegram/whatsapp bots
docker compose --profile all up -d       # everything

# Production
docker compose -f docker-compose.prod.yml up -d

# Self-hosting
docker compose -f docker-compose.selfhost.yml up -d
```

## Profiles (docker-compose.yml)

Services gated by profile (not started by default):
- `backend` — `gaia-backend`, `voice-agent-worker`
- `worker` — `arq_worker`
- `voice` — `voice-agent-worker`
- `bots` — `discord-bot`, `slack-bot`, `telegram-bot`, `whatsapp-bot`
- `all` — everything above

Infrastructure services (postgres, redis, mongo, chromadb, rabbitmq, observability stack) start without any profile.

## Service Dependencies

```
gaia-backend → chromadb, postgres, redis, mongo (all healthy)
arq_worker   → redis, mongo (healthy)
bots         → gaia-backend (healthy)
voice-agent  → (no hard deps in dev; depends on gaia-backend in prod)
grafana      → loki (healthy)
promtail     → loki (healthy)
```

## Gotchas

- **API listens on port 80 inside the container** in dev/prod compose files. The host-side port is 8000. The selfhost compose file uses 8000:8000 instead — check which file you're editing.
- **`LOG_FORMAT=json` and `LOG_COLORIZE=false`** are hardcoded in all compose files for Docker-hosted app services. Promtail expects NDJSON from stdout — do not change these.
- **Promtail mounts `apps/api/logs`** to ship logs from services running outside Docker (e.g., `nx dev api`). This directory is created automatically when file logging is enabled.
- **`arq_worker` uses the same `gaia` image as `gaia-backend`** — build once, run both.
- **RabbitMQ requires `observability/rabbitmq-enabled-plugins`** to be present (in dev compose). This file enables the Prometheus plugin.
- **Grafana default credentials**: admin / changeme (dev), admin / `$GRAFANA_ADMIN_PASSWORD` (prod). Set `GRAFANA_ADMIN_PASSWORD` in `.env` before production deployment.
- **PostgreSQL database name is `langgraph`** (not `gaia` or `postgres`).
- **`seed-models` service** in selfhost compose runs once (`restart: "no"`) to populate MongoDB with default model configs — it is not a persistent service.
- **Voice agent caches HuggingFace models** in the `voice_agent_models` named volume. First start downloads models and is slow. In prod, `HF_HUB_OFFLINE=1` prevents re-downloads.
- Port conflicts: ChromaDB uses port 8000 internally but exposes 8080 on the host specifically to avoid colliding with the API's host port 8000.
