---
name: reading-gaia-logs
description: Read and query GAIA's logs to debug a failing local run — wide events, where logs land per run mode, ready-made Loki/LogQL queries, LangGraph checkpoint + Langfuse introspection, bot logs, and a symptom→fix table for common startup failures.
---

# Reading GAIA Logs

Debug a failing local run by finding the right log, then the right line. This repo emits **one canonical structured line per unit of work** (wide events), so the fastest path is almost always: identify the run mode → grep/query the canonical line → pivot on `trace_id`.

Every path, port, and field below is verified against source. When in doubt, open the linked file — do not guess field names.

---

## 1. Wide events — the canonical log line

One structured line summarizes each request/task. Build it up with `log.set(...)`; it emits automatically at the boundary.

- **Module:** `libs/shared/py/wide_events.py`. Import in app code: `from shared.py.wide_events import log`.
- **API** (`wide_events.py`):
  - `log.set(**kwargs)` — merge structured fields into the current event (top-level).
  - `log.set_ns(namespace, **kwargs)` — merge into a nested `event[namespace]` dict; identical to `set(namespace={...})` (which also merges), with the namespace named explicitly. Prefer it on multi-step paths.
  - `log.info/debug(msg, ...)` — real-time Loguru line only; **not** recorded in the wide event.
  - `log.warning/error/critical/exception(msg, ...)` — Loguru line **and** appended to the event's `warnings`/`errors` array, bumping its final level.
- **Emit boundaries** (exactly one line each):
  - HTTP requests → `LoggingMiddleware` in `apps/api/app/api/v1/middleware/logging.py` emits message `http_request` (`request_logger`, `logger_name="REQUEST"`).
  - ARQ worker tasks → `wide_task()` context manager emits `worker_task` (`logger_name="WORKER"`).
  - Background asyncio work → `log_context()` emits `background_task` (`logger_name="BG"`).
- **Format:** controlled by `LOG_FORMAT` (`libs/shared/py/logging.py`). `console` (default, local) = colorized human text; `json` (Docker) = newline-delimited flat JSON. Bind fields are flattened to top level so Loki `| json` filters work.
- **Namespaces:** the `WideEventFields` schema (`wide_events.py`, ~line 431) maps namespace keys to TypedDicts — `user`, `chat`, `model`, `conversation`, `todo`, `memory`, `sandbox`, `mcp`, `integration`, `oauth`, `bot`, `workflow`, `voice`, etc. Read that schema to learn what a field means; don't invent keys.

### Correlate a request's lines: `trace_id`
- `trace_id` = `uuid4().hex[:16]`, set per request in `log.reset()`. It's a **top-level** field on the emitted JSON.
- The HTTP middleware honors an inbound `x-trace-id` header and echoes the final `trace_id` on the response `x-trace-id` header — so a caller that sends its own `x-trace-id` can grep by a value it chose.
- `chat.stream_id` correlates one chat streaming turn; `request_id` only exists if the client sent `x-request-id` (may be null — prefer `trace_id`).

### LogTag — message prefixes (not fields)
`apps/api/app/constants/log_tags.py` defines `LogTag` — bracketed prefixes (`[AGENT]`, `[TOOL]`, `[MEMORY]`, `[SANDBOX]`, `[MCP]`, `[STARTUP]`, `[WORKER]`, `[STORAGE]`, …) f-stringed onto the human message of `log.info/warning/error`. They tag the *message string* for greppability; structured context still goes through `log.set(...)`. Grep a subsystem's real-time chatter with e.g. `rg '\[SANDBOX\]'`.

---

## 2. Where logs land, per run mode

| Run mode | Where the canonical line is | How to read it |
|---|---|---|
| **Native** (`mise dev` / `nx dev api`) | uvicorn **stdout** (console format) **and** JSON files at `apps/api/logs/structured-<date>.json` | scroll the terminal; or `rg` the structured file |
| **Native worker** (`nx worker api`) | stdout + `apps/api/logs/worker/structured-<date>.json` | same |
| **Dockered API** (`mise dev:vm` / `docker compose --profile backend up -d`) | container stdout as JSON | `docker logs -f gaia-backend` |
| **Observability stack up** | shipped to Loki by Promtail | LogQL via curl or Grafana (§3) |

Native dev writes rotating files only when `LOG_FORMAT != json` — see `apps/api/app/config/loggers.py`. Extra native sinks: `apps/api/logs/errors-<date>.log`, `critical-<date>.log`.

Grep one request natively (JSON files):
```bash
# all lines of one request
rg '"trace_id":"<TRACE_ID>"' apps/api/logs/structured-*.json
# just the canonical HTTP summary lines
rg '"message":"http_request"' apps/api/logs/structured-*.json | rg '"status_code":5'
```

### Start the observability stack
Services live in `infra/docker/docker-compose.yml` under the **`observability`** profile (also `all`): `loki` (grafana/loki:3.3.2, host **:3100**), `promtail` (internal), `grafana` (grafana/grafana:11.4.0, host **:4000** → container 3000, admin password `GRAFANA_ADMIN_PASSWORD`, default `changeme`).
```bash
cd infra/docker
docker compose --profile observability up -d
# Grafana → http://localhost:4000  (Explore, Loki datasource is default)
```
Grafana comes pre-provisioned (`infra/docker/observability/grafana/provisioning/`): Loki datasource (uid `loki`, default) and dashboards (`overview.json` is home, plus `api-endpoints`, `arq-worker`, `databases`, `fs-ops`, `rabbitmq`, `voice-agent`, …). There is a Prometheus datasource but **no Prometheus service** in this compose file — those panels stay empty under the `observability` profile alone.

---

## 3. Ready-made LogQL queries

**Labels are the only thing you can select on** (everything else needs `| json`). Promtail applies exactly these labels (`infra/docker/observability/promtail-config.yaml`):
- Docker job: `container`, `service`, `service_name`, `stack`, `compose_project`, `stream`, `level`, `logger_name`
- File job (`gaia_api_local`, for natively-run services shipped from mounted `apps/api/logs`): `service`, `service_name`, `container`, `level`, `logger_name`

Service label values: `gaia-backend`, `arq_worker`, `voice-agent-worker` (files) / the same three plus `discord-bot`, `slack-bot`, `telegram-bot`, `whatsapp-bot`, `embedding-sidecar` (docker). High-cardinality fields (`user_id`, `path`, `trace_id`) are deliberately **not** labels — filter them with `| json` or a line filter `|=`.

**`| json` drops arrays.** `errors[]` / `warnings[]` / `audit[]` yield no field at all, and they're absent (not empty) on a clean request — so `| errors != "[]"` matches *every* line. Reach in with an explicit JSON expression, or filter on `final_level`.

**Via curl** (Loki HTTP API, `query_range`):
```bash
LOKI=http://localhost:3100
# URL-encode the LogQL in `query`; window via start/end (RFC3339 or unix-ns)
curl -sG "$LOKI/loki/api/v1/query_range" \
  --data-urlencode 'query={service="gaia-backend"} | json | trace_id="<TRACE_ID>"' \
  --data-urlencode "start=$(python3 -c 'import time; print(int((time.time()-3600)*1e9))')" | jq '.data.result'
```
(Grafana Explore: paste the same LogQL into the Loki datasource.)

**Errors for one user** (`|=` line-filters the raw id, robust to JSON nesting):
```logql
{service="gaia-backend", level="ERROR"} |= "<USER_ID>"
```

**One request's whole lifecycle:**
```logql
{service="gaia-backend"} | json | trace_id="<TRACE_ID>"
```

**Just the canonical HTTP summaries / errors:**
```logql
{service="gaia-backend"} | json | message="http_request" | status_code>=500
```

**Every failed request** (`final_level` folds in the HTTP status, so it also catches a 5xx that logged nothing):
```logql
{service="gaia-backend"} | json | message="http_request" | final_level=~"ERROR|CRITICAL"
```

**Requests that logged an error mid-flight** (even if they returned 200) — the second `| json` is what reaches into the array:
```logql
{service="gaia-backend"} | json | message="http_request" | json first_error="errors[0].msg" | first_error != ""
```

**Slow requests** (`duration_ms` is on the `http_request` line):
```logql
{service="gaia-backend"} | json | message="http_request" | duration_ms > 2000
```

**One chat turn** (line-filter the stream id):
```logql
{service="gaia-backend"} |= "<STREAM_ID>"
```

---

## 4. LangGraph introspection (checkpointed thread state)

The agent's conversation state is checkpointed in Postgres.

- **Setup:** `apps/api/app/agents/core/graph_builder/checkpointer_manager.py` builds `AsyncPostgresSaver` over a psycopg pool from `settings.POSTGRES_URL`. Falls back to `InMemorySaver` if the manager is unavailable (state won't be in Postgres then).
- **Tables** (created by `.setup()`): `checkpoints`, `checkpoint_writes`, `checkpoint_blobs`, `checkpoint_migrations`; the long-term store adds `store`, `store_vectors`. Key columns: `thread_id`, `checkpoint_ns`, `checkpoint_id`, `parent_checkpoint_id`.
- **thread_id = conversation_id.** Set in `apps/api/app/helpers/agent_helpers.py` (`build_agent_config`): `"thread_id": thread_id or conversation_id`. One conversation = one thread.
- **Connection:** single DSN `POSTGRES_URL`. `apps/api/.env.example` ships `postgresql://postgres:postgres@localhost:5432/postgres`. Note `infra/docker/CLAUDE.md` says the dockered Postgres DB is `langgraph`, not `postgres` — **use whatever DB is in your own `POSTGRES_URL`**; confirm before connecting.

Inspect a thread's checkpoints (swap the DSN for your `POSTGRES_URL`):
```bash
psql "$POSTGRES_URL" -c \
  "SELECT checkpoint_id, checkpoint_ns, parent_checkpoint_id
   FROM checkpoints WHERE thread_id='<CONVERSATION_ID>'
   ORDER BY checkpoint_id DESC LIMIT 5;"
```

- **Streaming/debug:** the graph runs via `graph.astream(..., stream_mode=["messages","custom","updates"])` (`agent_helpers.py`, `subagent_runner.py`, `workflow_subagent.py`). `"updates"` carries node-level state deltas — the place to observe per-node progress. Note: `stream_mode="debug"` and `astream_events` are **not** wired up, so there's no lower-level event firehose to tap.

---

## 5. Langfuse (LLM tracing) — usually off locally

`apps/api/app/config/langfuse.py`. Host-agnostic (env-driven `LANGFUSE_HOST`, no hardcoded cloud host), gated on all three of `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` being set. Missing keys → `build_langfuse_callback()` returns `None` (silent no-op). **Default local checkout = disabled**; if you see no traces, that's expected — set the three env vars against your Langfuse instance to enable.

When enabled: the stock `CallbackHandler` attaches per-run in `agent_helpers.py` (`_build_agent_callbacks`, added to the run `callbacks`). Trace association comes from run `metadata` keys: `langfuse_session_id` = **conversation_id** (= the LangGraph thread_id — group by Session to find a conversation's trace), `langfuse_user_id` = Mongo user_id, `langfuse_trace_id`, `langfuse_tags`. Reconstruct a message's trace id deterministically with `trace_id_for_message(message_id)`. Spans are auto-named by the LangChain integration (LangGraph node names, chain names, model names, tool names) — no custom span names are set.

---

## 6. Bot logs (Discord / Slack / Telegram / WhatsApp)

`createBotLogger(platform, component)` in `libs/shared/ts/src/bots/utils/logger.ts` — **JSON lines to stdout**. Every line has: `time` (ISO), `level` (INFO/WARN/…), `env`, `service` (`gaia-bot-<platform>`), `platform`, `component`, `event` (the event name), plus merged `fields`. Read a bot's log from its dev terminal or `docker logs <bot>-bot`.

**Hashed PII — how to correlate a user.** Raw platform user/channel IDs are never logged; they're hashed to `user_hash` / `channel_hash` (Telegram: `chat_hash`) via `hashLogIdentifier()`: **HMAC-SHA256** keyed by `BOT_LOG_HASH_SECRET` (falls back to `GAIA_BOT_API_KEY`, then unkeyed SHA-256), hex, first **16 chars**, prefixed `h_`. It's deterministic and unsalted, so:
- **Correlate across lines:** pick any `user_hash` (e.g. `h_1a2b3c4d5e6f7890`) and grep that exact string — every line for that one user.
- **From a raw id → its hash** (needs the secret; the secret bytes are the HMAC key as-is, not hex-decoded):
  ```bash
  printf '%s' '<RAW_ID>' | openssl dgst -sha256 -mac HMAC -macopt key:"$BOT_LOG_HASH_SECRET" -r \
    | cut -c1-16 | sed 's/^/h_/'
  ```

**Health ports** (`GET /health` → `{status:"ok", platform}`, from the shared `BotServer`; override with `BOT_SERVER_PORT`): discord **3200**, slack **3201**, telegram **3202**, whatsapp **3203**.
```bash
curl -s localhost:3200/health   # discord; 3201 slack, 3202 telegram, 3203 whatsapp
```

---

## 7. Failure signatures — symptom → meaning → fix

All verified against the cited docs/code. If a symptom isn't here, read the "Common Issues"/"Gotchas" sections in the relevant `CLAUDE.md` rather than guessing.

| Symptom | Meaning | Fix | Source |
|---|---|---|---|
| `JuiceFSUnavailable` in native API logs | Host has no `/mnt/jfs` FUSE mount; `_require_mount()` fails. Expected when running natively — it's a load-bearing signal, not a bug. | Switch to `mise dev:vm` (dockered API with the FUSE mount). Do **not** stub/silence `_is_mounted` or add a fallback. | `apps/api/CLAUDE.md` (JuiceFS section); `mise.toml` `dev:vm`; `app/services/storage/juicefs.py` |
| Telegram **`409 Conflict`** on startup / long poll | Two `getUpdates` sessions on the same bot token (two dev processes, dev + Docker, a webhook still set, or a stale SIGKILL'd session). | Run **one** instance only (not `mise dev:bots` while a container runs the same bot). The adapter auto-deletes any webhook and retries after 35s. | `apps/bots/telegram/src/adapter.ts` (~L324-351); `apps/bots/CLAUDE.md` "Single-instance constraint" |
| ARQ/lifespan services time out, API startup fails (Windows + Memurai) | `localhost` resolves to IPv6 `::1` first; Memurai binds IPv4 only. | Use `REDIS_URL=redis://127.0.0.1:6379` (literal `127.0.0.1`, not `localhost`). | `apps/api/CLAUDE.md` |
| Startup fails validating `WORKOS_*` even with dev auth bypass | `DevelopmentSettings` still *requires* the `WORKOS_*` keys; WorkOS itself is never called under the bypass. | Set **dummy** values for `WORKOS_API_KEY`, `WORKOS_CLIENT_ID`, `WORKOS_COOKIE_PASSWORD` (no specific values are prescribed). | `apps/api/CLAUDE.md`; `apps/api/.env.example` |
| Python deps not resolving | Workspace venv out of sync | `nx run api:sync` (or `nx run voice-agent:sync`) | root `CLAUDE.md` "Common Issues" |
| API unreachable on host :8000 (Docker) | The container listens on port **80** internally (host maps 8000); the selfhost compose uses 8000:8000. | Check which compose file you're editing. | `infra/docker/CLAUDE.md` |
| Port 8000 collision with ChromaDB | ChromaDB uses 8000 internally but publishes **8080** on the host to avoid the API's host 8000. | Expected — nothing to fix; don't remap. | `infra/docker/CLAUDE.md` |
| RabbitMQ won't start (dev compose) | Missing `observability/rabbitmq-enabled-plugins` file (enables the Prometheus plugin). | Ensure that file exists. | `infra/docker/CLAUDE.md` |

---

## Quick recipe

1. **Which mode?** Native → terminal + `apps/api/logs/structured-*.json`. Docker → `docker logs gaia-backend`. Stack up → Grafana `:4000` / Loki `:3100`.
2. **Get a handle:** the `trace_id` (HTTP response `x-trace-id`, or the `http_request` line), or the `conversation_id` / `stream_id`.
3. **Pull the request:** `rg '"trace_id":"…"'` natively, or `{service="gaia-backend"} | json | trace_id="…"` in Loki.
4. **Go deeper:** LangGraph state → Postgres `checkpoints` by `thread_id` (=conversation_id); LLM trace → Langfuse session (=conversation_id), if enabled; bot issue → the bot's stdout + `user_hash` correlation.
5. **Known failure?** Match §7 before changing anything — several of these are expected signals, not bugs.
