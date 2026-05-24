# Dagger CI -- Developer Guide

The `gaia-ci` Dagger module provides containerized quality checks and Docker image builds that run identically locally and in CI. Same container, same steps, no surprises.

## Prerequisites

- **Dagger CLI v0.20.3** -- matches the version pinned in CI:
  ```bash
  curl -fsSL https://dl.dagger.io/dagger/install.sh | DAGGER_VERSION=0.20.3 sh
  ```
- **Docker** running locally (Dagger uses it as the container runtime)
- Run all `dagger call` commands from the **repo root**

---

## Quick Reference

```bash
# Full quality gate (what CI runs on every PR)
dagger call quality-checks

# Individual checks
dagger call lint
dagger call type-check
dagger call build
dagger call test
dagger call dead-code
dagger call validate-release

# Integration tests (spins up Postgres, Redis, MongoDB automatically)
dagger call integration-test

# Docker image builds
dagger call docker-build --app api
dagger call docker-build --app web
dagger call docker-build --app voice-agent
dagger call docker-build --app bot-discord
dagger call docker-build --app bot-slack
dagger call docker-build --app bot-telegram
dagger call docker-build-all
```

Or use the equivalent mise tasks (all use `-s` for clean output by default):

```bash
mise ci:dagger                # Full quality gate (clean output)
mise ci:dagger:lint           # Lint only
mise ci:dagger:type-check     # Type-check only
mise ci:dagger:build          # Build only
mise ci:dagger:test           # Test only
mise ci:dagger:dead-code      # Dead code detection
mise ci:dagger:integration    # Integration tests
mise ci:dagger:debug          # Quality gate with interactive debugging on failure
mise ci:dagger:verbose        # Quality gate with full TUI + debug logs
```

---

## Quality Checks

### What runs in `quality-checks`

The `quality-checks` function runs **six checks in parallel** via `asyncio.gather`:

| Check | What it does |
|---|---|
| **lint** | Biome (JS/TS) + Ruff (Python) via `nx run-many -t lint` |
| **type-check** | mypy (Python) + tsc (TypeScript) via `nx run-many -t type-check` |
| **build** | All projects via `nx run-many -t build` |
| **test** | Nx tests + pytest with 80% coverage minimum (excludes integration/composio) |
| **dead-code** | vulture (Python) + knip (TypeScript) |
| **validate-release** | Release manifest version validation |

All six run concurrently from the same base container. Dagger deduplicates the shared environment setup automatically, so each check forks from the cached base without re-installing dependencies.

### CI integration

`.github/workflows/main.yml` runs `dagger call quality-checks` as its only quality gate step. The workflow is three steps total: checkout, master promotion policy check, Dagger. All toolchain setup and dependency installation happen inside the Dagger container.

---

## Docker Image Builds

Build production Docker images locally using the same Dockerfiles as CI:

```bash
# Build a single app
dagger call docker-build --app api

# Build all apps in parallel
dagger call docker-build-all
```

### Available apps

| App | Dockerfile | Build args |
|---|---|---|
| `api` | `apps/api/Dockerfile` | none |
| `web` | `apps/web/Dockerfile` | `NEXT_PUBLIC_API_BASE_URL` |
| `voice-agent` | `apps/voice-agent/Dockerfile` | none |
| `bot-discord` | `apps/bots/Dockerfile` | `BOT_NAME=discord` |
| `bot-slack` | `apps/bots/Dockerfile` | `BOT_NAME=slack` |
| `bot-telegram` | `apps/bots/Dockerfile` | `BOT_NAME=telegram` |

`docker-build` returns a `Container` object. `docker-build-all` builds all six in parallel and reports success/failure for each.

---

## Integration Tests

The `integration-test` function spins up live service containers and runs the integration test suite against them:

```bash
dagger call integration-test
```

### Service containers

| Service | Image | Port | Credentials |
|---|---|---|---|
| PostgreSQL 16 | `postgres:16-alpine` | 5432 | `gaia:gaia` / db: `gaia_test` |
| Redis 7 | `redis:7-alpine` | 6379 | none |
| MongoDB 7 | `mongo:7` | 27017 | `gaia:gaia` |

Dagger handles the full lifecycle: services start just-in-time, are health-checked, and stop when no longer needed. No Docker Compose required.

You can also use the service containers individually:

```bash
dagger call postgres-service
dagger call redis-service
dagger call mongo-service
```

---

## Debugging

### Interactive debugging

Drop into a shell at the exact point of failure:

```bash
dagger call quality-checks --interactive
dagger call test --interactive
dagger call lint --interactive
```

When a step fails, Dagger opens an interactive shell inside the container with all context preserved (env vars, working directory, installed deps). You can inspect files, re-run commands, and iterate without pushing.

### Terminal breakpoints

For deeper inspection, add `.terminal()` calls in the pipeline code:

```python
# In .dagger/src/gaia_ci/main.py
env = self.ci_env(source).terminal()  # pauses here for inspection
```

### Output modes

```bash
dagger call -s quality-checks     # silent — clean output only (mise default)
dagger call quality-checks        # normal — animated TUI with DAG visualization
dagger call -v quality-checks     # verbose — info-level logs
dagger call -vv quality-checks    # debug — debug-level logs
dagger call -vvv quality-checks   # trace — full trace logs
```

The mise tasks use `-s` (silent) by default for clean, readable output. Use `mise ci:dagger:verbose` or run `dagger call` directly when you need the TUI or debug logs.

---

## Caching

Dagger persists named cache volumes across local runs automatically. The module uses five volumes:

| Volume | Mount path | Contents |
|---|---|---|
| `pnpm-store` | `/root/.local/share/pnpm/store` | pnpm package store |
| `uv-cache` | `/root/.cache/uv` | uv download cache |
| `pip-cache` | `/root/.cache/pip` | pip download cache |
| `nx-cache` | `/app/.nx/cache` | Nx computation cache |
| `next-cache` | `/app/apps/web/.next/cache` | Next.js build cache |

First run downloads everything. Subsequent runs reuse caches and are significantly faster.

### Cache management

```bash
# Prune Dagger engine cache
dagger core engine local-cache prune
```

---

## MCP Server (AI IDE Integration)

The Dagger module is configured as an MCP server in `.mcp.json`, making all functions available as tools in Claude Code and other MCP-compatible IDEs.

All exported functions (lint, test, build, docker-build, integration-test, etc.) are automatically exposed as MCP tools. No manual registration needed.

### Setup

The `.mcp.json` at the repo root is already configured. Claude Code picks it up automatically. For other MCP clients, add:

```json
{
  "mcpServers": {
    "dagger": {
      "command": "dagger",
      "args": ["-s", "mcp"],
      "env": {}
    }
  }
}
```

---

## Architecture

### Module structure

```
dagger.json                          # Module definition (name, SDK, source)
.dagger/
  pyproject.toml                     # Python deps (dagger-io)
  src/gaia_ci/
    __init__.py                      # Exports GaiaCi
    main.py                          # All pipeline functions
```

### Source context

The module syncs the full repo to the Dagger engine, excluding build artifacts and caches (defined in `_IGNORE`). The `Source` type alias applies these exclusions to every function parameter automatically.

### How parallelism works

`quality_checks` creates one `ci_env` container, then forks it into six independent branches via `asyncio.gather`. Dagger's engine deduplicates the shared base container. Each check runs in its own isolated fork. Wall-clock time equals the duration of the slowest check, not the sum.

---

## Extending the Module

To add a new check:

1. Add a new `@function` method to `GaiaCi` in `.dagger/src/gaia_ci/main.py`
2. Use `Source` as the type annotation for the source directory parameter
3. Chain operations on `self.ci_env(source)` and return `.stdout()`
4. If it should run in the quality gate, add it to `asyncio.gather` in `quality_checks`
5. Add a mise task in `mise.toml` under the `ci:dagger:` namespace

Example:

```python
@function
async def my_check(self, source: Source) -> str:
    """Run my custom check."""
    return await (
        self.ci_env(source)
        .with_exec(["my-tool", "check"])
        .stdout()
    )
```
