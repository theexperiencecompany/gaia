# Real-Infra Tests (`integration/real/`)

Real-database tests. Production functions run unmodified against a real Redis (via the `real_redis` fixture in `db_fixtures.py` / `conftest.py`) or real MongoDB (`conversations_collection`, `mongo_db`) — no mocking of GAIA's own code. These catch bugs that only show up against real pub/sub timing, real key expiry, or real query semantics, which pure-mock unit tests can't see.

Requires the local infra containers (`nx run docker:up` from the repo root, or `mise dev`) plus `USE_REAL_SERVICES=1` — without the env var the root conftest mocks Mongo away. Run with:

```bash
USE_REAL_SERVICES=1 nx run api:test:real
```

The shared DB connection fixtures (`mongodb_url`, `redis_url`, `postgres_url`, `mongo_db`, `real_redis`, `hil_approvals_collection`) live in `db_fixtures.py` — the e2e suite's real-infra tests (`tests/e2e/test_hil_*_e2e.py`) import the same fixtures rather than redefining them. Reuse them; never hand-roll a connection in a test file.

Sub-suites:

- **`memory/`** — Memory engine suite (real Postgres/ChromaDB/Redis, mocked LLM only). Own conftest keeps its autouse guards scoped to its own tests. Run as part of the directory above.

Notable files:

- **`test_stream_manager_real.py`** — SSE chunk publish/subscribe, cancellation, cleanup against real Redis.
- **`test_device_bridge_real.py`** — The device bridge's cross-pod plumbing: presence compare-and-delete ownership (a stale pod's teardown must not evict a live reconnect on another pod), up-channel dispatch isolation between sessions, revoke-listener targeting, and a full `DeviceConnector` open/initialize/disconnect round trip against a fake in-process daemon (standing in for `gaia bridge` — see the module docstring for why `pod` only rides the `mcp.open` frame). Each test targets a bug this bridge has actually shipped with. These tests call the internal Python modules directly (`bridge.mark_online`, `up_listener.register_up_session`, ...) — a deliberate, narrower tier that isolates one piece of plumbing at a time.
- **`test_device_bridge_e2e.py`** — The device bridge's full user journey, black-box: a real `gaia bridge` daemon subprocess (via `tsx`, no build step) does its own real pairing/token/WebSocket work against a real, live GAIA API instance (`live_api_server` fixture — a genuine `uvicorn.Server` bound to a real localhost port, so an external process can actually dial in), exposing the real `@modelcontextprotocol/server-everything` reference server over stdio (not the built-in `filesystem` special case). Nothing about the daemon or the device-bridge service layer is mocked or called into directly — pairing, listing, testing a connection, and revoking are all driven through the exact HTTP/WS calls a real user's browser and machine would make. The only direct Redis access is for two states no API can produce without a real wait (a 15-minute pairing-code TTL, a 60-second refresh-token retry grace window) — every assertion is still made through a real API response. Requires `packages/cli`'s `node_modules` installed and network access (the reference server is fetched via `npx` on first run). Run serially — real subprocesses and a real bound port don't parallelize well under xdist: `uv run pytest tests/integration/real/test_device_bridge_e2e.py -v -n0`.
- **`test_redis_cache_real.py`** — Cache get/set/delete/pattern-delete against real Redis.

When adding a service test, patch the module singleton (`redis_cache.redis`, or the repository layer's `get_async_collection` accessor via `mongo_db`) rather than the function under test — see `conftest.py`'s `real_redis` fixture for the pattern. If a test needs a real bound TCP port (an external process, like a daemon, dialing in over a real socket), see `live_api_server` — it builds the real app via `create_app()` with only two substitutions: a lifespan that starts what the feature under test needs instead of the full `unified_startup` (which pulls in RabbitMQ, ChromaDB, and other infra unrelated to most single-feature tests), and `HeaderDrivenAuthMiddleware` in place of WorkOS SSO (which no automated test can drive for real). Every route, dependency, and service function underneath is the real, unmodified production code. If your test touches Postgres, depend on `clean_bridge_tables`-style cleanup rather than asserting on row counts that could accumulate across runs — and never call `unified_shutdown()` from a custom lifespan, since it tears down process-wide singletons (schedulers, the websocket consumer) that other test files in the same run may depend on staying up; dispose only the specific provider your fixture forced into existence.

## PostgreSQL credentials

CI's test container runs `gaia:gaia` (see `scripts/ci/start-test-services.sh`) — the fixture defaults match CI. Local `docker compose` Postgres uses `postgres:postgres`; when testing against it, export
`DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres`.
