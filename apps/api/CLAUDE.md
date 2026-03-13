# GAIA API

FastAPI backend for the GAIA personal AI assistant. Runs LangGraph agents, exposes REST/SSE/WebSocket endpoints, and manages all user data.

## Key Commands

All commands run from `apps/api/`. Prefer the `nx` wrappers (they set `cwd` and groups correctly) but the raw `uv` equivalents work too.

```bash
# Install / sync deps
nx run api:sync                        # uv sync --frozen --group backend --group dev

# Dev server (hot reload, port 8000)
nx dev api

# ARQ background worker
nx worker api

# Lint / format / type-check
nx lint api                            # ruff check
nx run api:lint:fix                    # ruff check --fix
nx format api                          # ruff format
nx type-check api                      # mypy app --ignore-missing-imports

# Tests (see Testing section below)
nx test api                            # unit + integration, 4 workers
nx run api:test:unit
nx run api:test:integration
nx run api:test:e2e                    # requires live services, not cached
nx run api:test:coverage
```

## Architecture

### Two-Agent Graph

The agent system uses two compiled LangGraph graphs registered via `GraphManager` / `ProviderRegistry`:

- **`comms_agent`** — thin front-door agent. Has only three tools: `call_executor`, `add_memory`, `search_memory`. Handles user-facing chat (streaming or silent).
- **`executor_agent`** — full-tool agent. Receives tasks from `comms_agent` via the `call_executor` tool. Has access to the entire tool registry retrieved from ChromaDB.

Both graphs are built in `app/agents/core/graph_builder/build_graph.py` and registered during startup via `build_graphs()`.

### Agent Execution Modes

`app/agents/core/agent.py` exposes two entry points that share `_core_agent_logic()`:

- `call_agent()` — returns `AsyncGenerator` for SSE streaming (chat endpoint)
- `call_agent_silent()` — returns `(message, tool_data)` tuple (workflows, background tasks)

### Streaming Architecture

Chat streaming is **decoupled from the HTTP connection** (see `app/api/v1/endpoints/chat.py`):

1. Endpoint launches an `asyncio.Task` that runs LangGraph and publishes SSE chunks to a Redis channel.
2. The HTTP response subscribes to that Redis channel and forwards chunks.
3. If the client disconnects, the background task keeps running and saves the conversation to MongoDB.
4. Stream cancellation via `POST /api/v1/cancel-stream/{stream_id}` sets a Redis flag that the background task checks.

### Lazy Provider System

All external clients (DBs, LLM clients, agent graphs) are registered as lazy providers via `app/core/lazy_loader.py`. A provider is initialized on first `providers.aget(name)` call, not at import time. Use the `@lazy_provider(name=..., required_keys=[...])` decorator to register new providers. Never call `providers.get(...)` for async providers — use `await providers.aget(...)`.

Providers are registered (not initialized) during `unified_startup()` in `app/core/provider_registration.py`.

### State

`app/agents/core/state.py` defines `State(DictLikeModel)`. It implements `MutableMapping` so LangGraph can use it like a dict. The `messages` field uses `add_messages` reducer — always append, never replace.

### Nodes

Pre-model hooks in `app/agents/core/nodes/`:
- `filter_messages_node` — trims history to fit context window
- `manage_system_prompts_node` — injects dynamic system prompt
- `follow_up_actions_node` — end-of-graph hook on `comms_agent` only

### Tools

`app/agents/tools/core/registry.py` — central tool registry backed by ChromaDB for semantic retrieval. Tools that the executor agent may need are retrieved at inference time, not statically bound.

## Code Style

- All functions and methods require full type annotations (enforced by mypy).
- No inline imports — all imports at the top of the file.
- Use `ruff` for linting and formatting (not black/flake8/isort).
- Raise `AppError` (from `app/utils/errors.py`) for domain errors — it serializes to a structured JSON response automatically.
- Structured logging uses `from shared.py.wide_events import log`. Call `log.set(key=value)` to attach context fields, `log.info(...)` / `log.error(...)` to emit.

## Database

| Store | Used for |
|---|---|
| **MongoDB** | All user data: conversations, todos, reminders, workflows, notes, files, payments, integrations, etc. DB name is `GAIA`. Collections are accessed via `from app.db.mongodb.collections import <name>_collection` — lazy-loaded, async (Motor). Use `get_sync_collection()` only in sync code (e.g. Composio tools). |
| **PostgreSQL** | LangGraph checkpointer (conversation thread state / memory). Also general relational data. |
| **Redis** | Caching (`fastapi-cache2`), SSE stream channels, rate limiter counters, stream cancellation flags. |
| **ChromaDB** | Vector store for tool retrieval (which tools the executor should use), trigger embeddings, and public integration descriptions. |
| **RabbitMQ** | Event publishing for cross-service messaging (bots, voice agent). |

## Testing

Tests run with `pytest-asyncio` in `asyncio_mode = auto` (all async tests work without `@pytest.mark.asyncio` on the function, but the class still needs the marker or `@pytest.mark.asyncio` on individual tests to satisfy strict mode).

Default `addopts`: `-m "not composio" --strict-markers -n 4` — four parallel workers, composio tests excluded.

**Test structure:**
- `tests/unit/` — no external deps, mock everything. Fast.
- `tests/integration/` — compiles real LangGraph graphs or exercises the full FastAPI request cycle (mocked service layer, no real DBs).
- `tests/e2e/` — marked `e2e`, require real or near-real services, not cached, run separately.
- `tests/composio/` — require real Composio credentials, excluded by default.

**Root `conftest.py` gotchas:**
- Sets `ENV=development` at import time before any app module loads. Must stay first.
- Patches `inject_infisical_secrets` and `MongoDB.ping` globally so tests never hang on external connections.
- Patches `tiered_limiter.check_and_increment` and `payment_service.get_user_subscription_status` globally.
- Provides `client` (authenticated) and `unauthed_client` fixtures that use `ASGITransport` with a no-op lifespan.

**Integration API tests** use a separate `conftest.py` in `tests/integration/api/` that provides `test_client` and `unauthenticated_client` fixtures with `_MockAuthMiddleware` / `_NoAuthMiddleware`. These are different from the root `client` fixture.

Run composio tests (needs credentials): `uv run pytest tests/composio -v`

Run e2e tests (needs live services): `nx run api:test:e2e`

## Environment

Settings class is selected by `ENV` env var (`production` | `development`). `DevelopmentSettings` makes most keys optional. `ProductionSettings` requires all keys.

Settings are loaded once via `@lru_cache` in `app/config/settings.py`. In tests, call `get_settings.cache_clear()` before recreating the app to pick up env changes.

Secrets in production are injected from **Infisical** before Pydantic validates the settings object. In development, use `.env` only.

See `apps/api/.env.example` or the `ProductionSettings` class in `app/config/settings.py` for the full list of required keys. For local dev, `DevelopmentSettings` makes most keys optional — set at minimum `ENV=development`, MongoDB URL, Redis URL, and WorkOS credentials.

## Pre-commit Hooks & Security Scanners

The API pre-commit config (`.pre-commit-config.yaml`) runs: **ruff**, **ruff-format**, **bandit**, **pip-audit**, and **mypy**.

### Bandit

Bandit runs `uvx bandit -r app` on every commit. When it flags a genuine false positive:

1. Confirm it is actually a false positive — read the rule, understand why Bandit is triggering.
2. Suppress inline using `# nosec B<rule_id>` (prefer explicit rule IDs over bare `# nosec`).
3. Always add a comment on the line above explaining why it is a false positive — do not suppress silently.

Common rules: `B101` (assert), `B106` (hardcoded password — often env var defaults), `B311` (random for non-crypto use), `B603/B607` (subprocess), `B324` (md5/sha1 for non-security purposes).

### SonarQube

SonarQube scans run in CI. Suppress false positives with `# NOSONAR` (all rules) or `# NOSONAR python:S<id>` (specific rule) on the offending line. Only suppress after confirming it is a false positive, and add a comment explaining why.

### After Major Changes

Always run these before considering work complete:
```bash
# Backend
nx type-check api
nx lint api

# Frontend
nx run-many -t type-check --projects=web,desktop
nx run-many -t lint --projects=web,desktop
```

## Non-Obvious Patterns

- **`app/patches.py`** is imported at the top of `main.py` with `# noqa: F401` — it applies monkey-patches to third-party libraries at startup. Do not remove this import.
- **Docs are disabled in production**: `/docs` and `/redoc` return 404 when `ENV=production`. Use `ENV=development` locally.
- **`app/core/lazy_loader.py` `providers` is a global singleton** — unique provider names are critical. Use UUID suffixes in tests to avoid cross-test pollution (the registry is never reset between tests).
- **LangGraph checkpointer**: Uses PostgreSQL (`langgraph-checkpoint-postgres`) in production, falls back to in-memory `InMemorySaver` if the checkpointer manager is unavailable.
- **Background memory storage**: `store_user_message_memory()` is fire-and-forget in `_core_agent_logic()`. Use the `_background_tasks` set pattern to prevent garbage collection of running tasks.
- **`UJSONResponse`** is the default response class (faster JSON serialization). Custom error handlers in `app_factory.py` return plain `JSONResponse` to avoid double-serialization issues.
- **`ENABLE_LAZY_LOADING=true`** (default) means startup blocks until services initialize. Setting it to `false` makes the server start immediately and warm up in the background — safe for requests because `LazyLoader` uses per-provider locks.
