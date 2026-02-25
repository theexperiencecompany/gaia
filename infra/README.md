# infra

Infrastructure configuration for GAIA.

## Structure

- **docker/** — Docker Compose files and Nx project config for managing local and production services.

## Docker

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Local development environment (all services) |
| `docker-compose.prod.yml` | Production deployment |
| `docker-compose.selfhost.yml` | Self-hosted deployment configuration |

### Services

Includes PostgreSQL, MongoDB, Redis, ChromaDB, and RabbitMQ.

### Nx Commands

```bash
nx docker:up      # Start all services (detached)
nx docker:down    # Stop and remove containers
nx docker:restart # Restart all services
nx docker:logs    # Tail logs from all services
nx docker:ps      # List running containers
```

### Profiles

```bash
docker compose --profile backend up   # Backend + dependencies
docker compose --profile worker up    # Worker + dependencies
docker compose --profile voice up     # Voice agent
```

Copy `.env.example` to `.env` inside `infra/docker/` before running.
