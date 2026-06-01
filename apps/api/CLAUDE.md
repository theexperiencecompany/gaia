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

### Tooling and the autofix hook

After every `.py` edit, a PostToolUse hook runs `uvx ruff format` then `uvx ruff check --fix` on the file. Formatting, import order/grouping, `Optional[X]` → `X | None`, `Union[X, Y]` → `X | Y`, lowercase generics, unused imports, mutable default args, bare `except`, and `print` are corrected automatically — do not hand-fix them.

What the hook does NOT fix, you handle:

- **Type errors** — `nx type-check api` (mypy strict). Add the missing annotation or correct the type. Use `Any` only for genuinely untyped third-party code.
- **Lint warnings ruff can't auto-resolve** — `nx lint api`, read the rule, fix the cause.

Python 3.11+: use modern syntax (`X | Y` unions, `match` statements).

## File & Structural Organization

One domain per file. Never let a file span multiple domains.

- `app/models/` — SQLAlchemy / MongoDB document models, one file per domain (`todo_models.py`).
- `app/schemas/` — Pydantic request/response schemas, one file per domain. Separate `CreateRequest`, `UpdateRequest`, `Response`.
- `app/services/` — business logic, one file per domain. No route handling.
- `app/api/v1/endpoints/` — route handlers, one file per domain. No business logic.
- `app/db/` — DB client setup and connection utilities only.
- `app/constants/` — constants by domain (`cache.py`, `llm.py`, `auth.py`). Never hardcode values.

## Pydantic Models

- `BaseModel` for all schemas; `model_config = ConfigDict(from_attributes=True)` on ORM-mapped models.
- `Field(description="...")` on fields that appear in API docs; constraints inline (`Field(min_length=1, max_length=255)`).
- Naming: `CreateTodoRequest`, `UpdateTodoRequest`, `TodoResponse`, `TodoModel`.

## FastAPI — Route Handlers

One `APIRouter` per domain with `prefix` and `tags`. Every handler follows the same 3-step contract:

1. `log.set()` with everything known at the start (user, operation, IDs).
2. Delegate all work to a service function.
3. `log.set()` again with result IDs, then return `JSONResponse`.

```python
@router.post("/todos", response_model=TodoResponse, status_code=201)
async def create_todo(
    payload: CreateTodoRequest,
    user: dict = Depends(get_current_user),
) -> JSONResponse:
    log.set(user={"id": user["user_id"]}, todo={"operation": "create"})
    result = await create_todo_service(payload, user)
    log.set(todo={"id": result["_id"]})
    return JSONResponse(content=result)
```

- Always set `response_model=` on the decorator; use correct status codes (`201` create, `204` delete, `404` not found).
- Never return raw dicts — always `JSONResponse` or a Pydantic response model.

## Service Layer

Services are async module-level functions, not classes.

- No service classes with `__init__`, instance methods, or injected dependencies. If grouping is needed, use a class with `@staticmethod` methods only — never `self`.
- Services access MongoDB collections directly via `app.db.mongodb.collections` — no repository layer.
- Keep one-off query logic in the service function where it is used; return domain models, not raw DB documents.

```python
# wrong
class TodoService:
    def __init__(self, db):
        self.db = db
    async def get_todo(self, todo_id: str): ...

# correct
async def get_todo(todo_id: str, user_id: str) -> TodoModel | None:
    return await todos_collection.find_one({"_id": todo_id, "user_id": user_id})
```

## Anti-Patterns

- No sync DB/HTTP calls in async endpoints — all I/O must be `async`.
- No `time.sleep()` — use `asyncio.sleep()`; use `asyncio.gather()` for concurrent independent ops.
- No global mutable state — pass dependencies explicitly.
- No monolithic service files spanning multiple domains.
- No copying logic from `gaia-shared` into app code — import it.

## Database

| Store          | Used for                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **MongoDB**    | All user data: conversations, todos, reminders, workflows, notes, files, payments, integrations, etc. DB name is `GAIA`. Collections are accessed via `from app.db.mongodb.collections import <name>_collection` — lazy-loaded, async (Motor). Use `get_sync_collection()` only in sync code (e.g. Composio tools).                                                                                                                                                                                                                                                                                                                                                       |
| **PostgreSQL** | LangGraph checkpointer (conversation thread state / memory). Also general relational data.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **Redis**      | Caching (`fastapi-cache2`), SSE stream channels, rate limiter counters, stream cancellation flags. Use Redis for all server-side caching of JSON-serializable data (integration status, tool schemas, API responses). The `@Cacheable` decorator (`app/utils/cacheable.py`) is the standard pattern — see `get_all_integrations_status()` in oauth_service.py for usage. **Do NOT try to cache Composio tool objects in Redis** — they contain dynamically-generated Pydantic models and `functools.partial` closures that are not pickleable. Cache these in-memory on the `ComposioService` singleton instead (keyed by `(tool_name, user_id, hook_flags)` with a TTL). |
| **ChromaDB**   | Vector store for tool retrieval (which tools the executor should use), trigger embeddings, and public integration descriptions.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **RabbitMQ**   | Event publishing for cross-service messaging (bots, voice agent).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |

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

## Native vs Dockered API (JuiceFS trade-off)

The API can run two ways in dev. They are **not** equivalent — the difference matters whenever you touch workspace v2, file uploads, artifacts, or sandbox file ops.

| Mode | How | Port | JuiceFS mount | Hot reload |
|---|---|---|---|---|
| **Native** (default) | `mise dev` / `nx dev api` | host:8000 | not available | `uvicorn --reload` |
| **Dockered** | `mise dev:vm` / `docker compose --profile backend up -d` | host:8000 → container:80 | mounted at `/mnt/jfs` | `WATCHFILES_FORCE_POLLING` |

### Why this split exists

JuiceFS is the host-side FUSE mount that backs workspace v2 (per-session FS, uploads, artifacts, skill installs). Mounting FUSE on Linux needs `CAP_SYS_ADMIN` + `/dev/fuse` + `apparmor:unconfined`. A native macOS process can't grant itself those — they only exist inside the dockered container. So the API code on the host has no `/mnt/jfs`, and `_require_mount()` in `app/services/storage/juicefs.py` raises `JuiceFSUnavailable`.

The compose file profile-gates `gaia-backend` (`profiles: ["backend", "all"]`) precisely so `mise dev` can give you a native API with fast iteration without forcing the JuiceFS plumbing on every dev session.

### What works in native mode

- Chat (LLM calls, message persistence, SSE streaming)
- Memory, todos, reminders, integrations, workflows, payments — anything Mongo/Postgres-only
- Most agent tool calls
- Sandbox tools that don't depend on the API seeding files via JuiceFS first

### What raises `JuiceFSUnavailable` in native mode

All of these call `_require_mount()` in `app/services/storage/juicefs.py`:

- `write_session_file` — user file uploads from the chat UI
- `ensure_user_workspace` — first-time workspace bootstrap for a user
- `write_skill_file` / `ensure_user_skills_dir` — installing skills to the user's workspace
- The artifact watcher in `app/services/sandbox/artifact_watcher.py` — needs to tail `/mnt/jfs/.accesslog`
- Any service path under `app/services/storage/sessions/` that touches the FS

If you hit `JuiceFSUnavailable` while running natively, **that is expected** — the fix is to switch to `mise dev:vm`, not to "fix" the error. Do not silence the exception, do not add a no-op fallback, do not stub `_is_mounted` to return `True`. The mount being missing is a load-bearing signal that JuiceFS-dependent features need the dockered API.

### When to use which

- **Default to native (`mise dev`).** Faster start, port 8000 free, `uv` commands work directly, hot reload is instant.
- **Switch to `mise dev:vm`** when your task touches `app/services/storage/`, `app/services/sandbox/`, file upload endpoints, artifact streaming, workspace v2 in general, or you start seeing `JuiceFSUnavailable` in logs.

### Coding-agent note

If you are an agent fixing a bug here and you see `JuiceFSUnavailable`: do **not** wrap it in `try/except: pass`, do **not** stub the storage helpers, and do **not** create a fake `/mnt/jfs` directory. The user's `mise dev` is intentionally configured to surface this. Either tell the user to switch to `mise dev:vm` for tasks that actually exercise JuiceFS, or confirm with them that the failing code path isn't relevant to the current task before changing anything.

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
- **Sandbox user has no `sudo`.** The `gaia-coder` template strips the sandbox user from the `sudo` and `wheel` groups (see `apps/api/scripts/build_e2b_template.py`). Drive root-needing operations (mount.sh, accesslog tail) through e2b's `sbx.commands.run(..., user="root")` parameter — never prefix shell commands with `sudo` in API code, the call will fail. JuiceFS itself runs under `/etc/gaia/jfs_launcher.py` which marks the daemon non-dumpable (`PR_SET_DUMPABLE=0`) so its `/proc/<pid>/{environ,cmdline}` are unreadable to the unprivileged user. `/proc` is mounted `hidepid=invisible` so even PID enumeration is denied. Verify after template rebuilds with `apps/api/scripts/verify_sandbox_hardening.sh`.
