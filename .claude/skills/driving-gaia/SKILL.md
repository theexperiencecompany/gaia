---
name: driving-gaia
description: Operate the running GAIA app as an agent — boot the right stack, authenticate with zero login via the dev bypass, drive the REST/SSE API and bots directly, script the LLM deterministically, and verify outcomes in Mongo instead of trusting stdout. The cookbook for end-to-end testing a change against a live stack.
---

# Driving GAIA

You need to see a change *actually work* — not lint-clean, not "reads correct", but run against a live stack. This skill is the one-way-to-do-each-thing cookbook: boot the right stack, become a user with no login, drive the surface (API / browser / bot), and confirm the data landed.

Every command, port, path, and payload below is verified against source. When a shape is unclear, open the linked file — do not guess. To debug a run that misbehaves, see the `reading-gaia-logs` skill.

---

## 1. Boot the stack — pick one

One command per intent. Each starts infra in Docker (`nx run docker:docker:up`, idempotent) and the app natively unless noted.

**Everything in this skill needs the dev auth bypass (zero login, §2), enabled by the `--agent` / `--sim` flags.** Plain `mise dev` (no flag) is the *human* path — real WorkOS login, no bypass — so don't use it bare for agent driving. `--agent` and `--sim` compose onto both the native (`dev`) and dockered (`dev:vm`) runtimes; both fail loudly under `ENV=production` (§2).

| You need… | Command | Why |
|---|---|---|
| **Agent driving, real LLM** (API + web natively, zero login) | `mise dev --agent` | Dev auth bypass ON — every request is `DEV_USER` (default `dev@gaia.local`), no WorkOS. Hot reload, API on host `:8000`. The default for this skill. JuiceFS-dependent paths raise `JuiceFSUnavailable` here — expected, not a bug. |
| **Deterministic, credential-free** — scripted LLM, no OpenRouter cost | `mise dev --sim` | `--agent` + the scripted LLM stub (`tools/llm-stub`, `:9797`). Bypass also ON. Model replies come from directives in the chat message (§3). Run `mise seed` once the API is up. |
| **JuiceFS paths** — workspace v2, file uploads, artifact streaming, sandbox file ops | `mise dev:vm --agent` | Runs the API in a container with the FUSE mount; web stays native. `--agent` (or `--sim`, reaching the host stub via `host.docker.internal`) turns on the bypass; plain `mise dev:vm` is real login. Use the moment you hit `JuiceFSUnavailable`. |
| **Real login flow** (human testing, no bypass) | `mise dev` | Same native stack, no flag — the real WorkOS login, for testing signup/auth as an actual user. Not for agent driving. |

Every bypass command authenticates as `DEV_USER` (default `dev@gaia.local`); set `DEV_USER=<email>` to be someone else (it also becomes the `mise seed` target — §2).

Single API only: `mise dev:api`. Web only: `mise dev:web`. (See `mise tasks` for the full list.)

### No Docker daemon? (cloud sandboxes, CI runners, dev containers)

Every command above starts infra with `nx run docker:docker:up`, which needs a
Docker daemon. Cloud sandboxes usually have none, and `mise dev` then fails on
missing services rather than on anything you changed. Bring the same backing
services up natively instead:

```bash
sudo ./scripts/dev/sandbox-services.sh up      # mongo, redis, rabbitmq, postgres, chroma
./scripts/dev/sandbox-services.sh seed         # the rows the API refuses to boot without
./scripts/dev/sandbox-services.sh status
source scripts/dev/sandbox-env.sh              # there is no .env in a fresh sandbox
cd apps/api && uv run uvicorn app.main:app --port 8000
```

Then mint the bypass user — **without it every request 401s** with
`Dev bypass target has no Mongo user`:

```bash
curl -X POST localhost:8000/api/v1/dev/users \
  -H 'content-type: application/json' -d '{"email":"dev@gaia.local","name":"Dev User"}'
```

Three things that will cost you an hour if you don't know them, all encoded in
those scripts: the app reads the **`GAIA`** database, not the one named in
`MONGO_DB`'s path, so seeding the URI's database leaves startup validation
still failing; RabbitMQ must run as the `rabbitmq` user, not root; and
`LOG_FORMAT=json` makes `configure_file_logging()` a no-op, so logs go to
stdout and `apps/api/logs/` stays empty — that is correct behavior, not a
broken sink (see `reading-gaia-logs`).

**Ports.** `API_PORT` / `WEB_PORT` are honored everywhere (default 8000 / 3000). For several branches at once, `mise run wt:env` writes a per-worktree `.env.worktree` with collision-free ports (API 8000+offset, web 3000+offset, stub 9797+offset, bots 3200-3203+offset) that mise auto-loads. `mise dev` preflights those ports and refuses to start when one is taken (adding the stub port under `--sim`), naming the process that holds it — a stale server from another worktree used to silently absorb the whole session's traffic. Full workflow: **`parallel-worktrees` skill** — don't reinvent it here.

**WorkOS keys.** `DevelopmentSettings` still requires `WORKOS_API_KEY` / `WORKOS_CLIENT_ID` / `WORKOS_COOKIE_PASSWORD` even under the bypass (WorkOS is never called). Dummy values are fine locally; missing ones fail startup.

---

## 2. Become a user — the dev auth bypass (zero login)

The bypass is enabled by the `--agent` / `--sim` flag, not by editing `.env`. `mise dev --agent`, `mise dev --sim`, and `mise dev:vm --agent` (or `--sim`) each export `DEV_AUTH_BYPASS_EMAIL=${DEV_USER:-dev@gaia.local}` for the API process. Every API request then authenticates as that Mongo user — no WorkOS, no cookies, no login flow (`apps/api/app/api/v1/middleware/auth.py`, `_dispatch_dev_bypass`). Point `apps/web/.env.local` at your API base — `http://localhost:${API_PORT:-8000}/api/v1/` (worktrees get their own port via `.env.worktree`) — and the web app is authenticated on page load. Development only: the flags run `scripts/dev/assert-not-prod.sh` and abort if `ENV=production`, and `get_settings()` refuses to boot with the var set in prod regardless.

`apps/api/.env` keeps `DEV_AUTH_BYPASS_EMAIL` **commented out** on purpose so plain `mise dev` is a real login flow — enable the bypass through the `--agent`/`--sim` flag (pass `DEV_USER=<email>` to change the identity), don't hardcode it back into `.env`.

The user must already exist in Mongo. The dev router (`/api/v1/dev/*`) mints and seeds them — it is mounted **only** when `ENV=development` **and** `DEV_AUTH_BYPASS_EMAIL` is set (`app/core/app_factory.py:139`), and 404s otherwise. Because the bypass is on under `--agent`/`--sim`, the router is mounted there; it is itself exempt from the bypass, so you can mint the first user before any user exists. (Under a bare `mise dev` the bypass is off, so `/dev/*` 404s — add `--agent` or `--sim` to reach it.)

### One command: `mise seed`

`mise seed` is a thin curl wrapper over the two endpoints below — it `POST`s `/dev/users` then `/dev/seed` against the running API. This is the canonical bootstrap:

```bash
mise seed                                   # dev@gaia.local, 5 todos + 2 conversations
DEV_USER=alice@gaia.local SEED_TODOS=3 mise seed
```

To act as a non-default user, boot with the **same** `DEV_USER` you seeded (`DEV_USER=alice@gaia.local mise dev --agent`) — that email becomes both the seed target and the server's bypass identity. For a one-off different user against an already-running server, use the `X-Dev-User` header instead (below).

### The endpoints directly (`X-Dev-User` for multi-user)

Source of truth: `app/api/v1/endpoints/dev.py`, `app/services/dev_service.py`, `app/schemas/dev_schemas.py`.

```bash
API=http://localhost:${API_PORT:-8000}/api/v1

# Mint — idempotent find-or-create via the real signup path (store_user_info).
curl -sfS -X POST "$API/dev/users" -H 'content-type: application/json' \
  -d '{"email":"alice@gaia.local","name":"Alice"}'
# → {"id":"<mongo_id>","email":"alice@gaia.local","name":"Alice"}

# Seed — real service calls (create_todo, create_conversation_service,
# PlatformLinkService.link_account); also marks onboarding complete so specs
# land on the app shell, not onboarding. platform_links ∈ discord|slack|telegram|whatsapp.
curl -sfS -X POST "$API/dev/seed" -H 'content-type: application/json' \
  -d '{"email":"alice@gaia.local","todos":5,"conversations":2,"platform_links":["telegram"]}'
# → {"email":...,"user_id":...,"todos_created":5,"conversations_created":2,"platforms_linked":["telegram"]}

# Delete — teardown (removes user + owned todos/conversations/projects).
curl -sfS -X DELETE "$API/dev/users/alice@gaia.local"
```

**Impersonation.** With the bypass active, send `X-Dev-User: <email>` on any request to authenticate as that user instead of `DEV_AUTH_BYPASS_EMAIL` — one running server acts as many users, no restart. An email that resolves to no Mongo user **fails loud with 401**: `No GAIA user exists for '<email>' — mint it via POST /api/v1/dev/users`. Mint it (or drop the header) — never work around the 401.

---

## 3. Script the LLM deterministically (`--sim`)

Under `mise dev --sim` (one switch: `GAIA_SIM_MODE=1`, read by settings — every LLM factory resolves to the stub; real keys in `.env` stay untouched and unused), the model is replaced by `tools/llm-stub` — an OpenRouter-wire-compatible server that scripts from the **newest user message carrying directives** (the graph appends context slots as trailing user messages; the stub skips them) and emits them in order (`tools/llm-stub/directives.py`, `wire.py`). No scenario files, no cost, fully deterministic.

**When to use sim mode** — verifying plumbing, not intelligence: does a tool call flow comms → executor → real tool → Mongo; does the SSE stream shape render; does a bot/Playwright flow work end to end; any test that must pass identically every run with no credentials.
**When NOT to use it** — anything judging real model behavior: prompt changes, tool-selection quality, response tone/format, memory extraction quality, model regressions. The stub does exactly what the directive says and nothing else, so "the agent chose the right tool" is meaningless under sim. Use `mise dev --agent` with real keys for those, and expect nondeterminism.

```text
[[tool:<name> <json-args>]]   one scripted tool call — repeatable, ordered
[[say:<text>]]                the final assistant reply — at most one, terminal
```

- A message with **no** directives → the canned reply `ok (llm-stub)`.
- The stub is stateless: each call it counts the tool-call turns already in the request and emits the next pending directive, then the `say` text once all tools are consumed.
- **Malformed directive JSON → HTTP 500** echoing the bad directive (fail loud) — e.g. `[[tool:foo {bad}]]`. Fix the JSON; don't retry blindly.
- GAIA's two-agent front door is handled automatically: a directive naming an executor-only tool becomes one `call_executor` hand-off that replays the whole script to the executor. Keep one script to one agent level (don't mix comms-only tools like `add_memory` with executor tools).
- The bigtool executor is also handled automatically: a scripted tool that isn't bound yet triggers a `retrieve_tools(exact_tool_names=[...])` call first — invisible to your script; the stub's stdout logs every request (`[llm-stub] roles=[...] directives=N script_msg=...`) when you need to debug a run.
- **Nesting works.** A tool directive's args end where its JSON value ends, not at the first `]]`, so args may contain a literal `]]` — including a whole nested directive, at any depth. That is how you script a hand-off: `[[tool:handoff {"subagent_id":"gmail","task":"[[tool:GMAIL_FETCH_MESSAGES {\"max_results\":3}]]"}]]`. JSON-encode the args (`json.dumps`) and the escaping takes care of itself.
- **Limitation:** a `[[say:…]]` body is plain text and ends at the first `]]`, so say text cannot contain that sequence. Put nested scripts in tool args.
- **A directive opened but never closed → HTTP 500**, not a silent fall-through to the canned reply.

Example message that files a todo then replies: `add a todo [[tool:create_todo {"title":"buy milk"}]] [[say:Added it.]]`

Stub knobs: `LLM_STUB_PORT` (default 9797) / `LLM_STUB_HOST` (default 127.0.0.1) on the stub process; `OPENROUTER_BASE_URL` on the API to point at a non-default stub address. The stub's own unit tests: `uv run --no-project --with pytest pytest tools/llm-stub -q`.

---

## 4. Drive the REST/SSE API directly

All routes under `/api/v1`. Under the bypass, add `-H 'X-Dev-User: <email>'` to act as a specific seeded user; omit it to be `DEV_AUTH_BYPASS_EMAIL`.

**Chat (streaming turn).** `POST /api/v1/chat-stream` (`app/api/v1/endpoints/chat.py:99`). Body is `MessageRequestWithHistory` (`app/models/message_models.py`): `messages` is a list of `{role, content}`; `conversation_id` optional (server mints one if absent); `turn_id` optional idempotency key (duplicate → 409). Response is SSE (`text/event-stream`); the stream id is on the `X-Stream-Id` response header, and the turn **continues in the background and persists to Mongo even if you disconnect**.

```bash
curl -sN -X POST "http://localhost:${API_PORT:-8000}/api/v1/chat-stream" \
  -H 'content-type: application/json' -H 'X-Dev-User: alice@gaia.local' \
  -d '{"messages":[{"role":"user","content":"[[say:hello from sim]]"}]}'
# SSE frames stream as `data: ...`; grab X-Stream-Id from the response headers (-D -) to reattach/cancel.
```

- Reattach to a live/finished stream: `GET /api/v1/stream/{stream_id}` (replays the event log).
- Cancel: `POST /api/v1/cancel-stream/{stream_id}`.

**Todos.** `GET /api/v1/todos` (list), `POST /api/v1/todos` (create) (`app/api/v1/endpoints/todos.py`):

```bash
curl -sfS "http://localhost:${API_PORT:-8000}/api/v1/todos" -H 'X-Dev-User: alice@gaia.local'
curl -sfS -X POST "http://localhost:${API_PORT:-8000}/api/v1/todos" \
  -H 'content-type: application/json' -H 'X-Dev-User: alice@gaia.local' \
  -d '{"title":"from curl"}'
```

**Verify it landed — check Mongo, not stdout.** The API's database is `GAIA` (`app/db/mongodb/mongodb.py`, `get_database("GAIA")`), regardless of the db path in `MONGO_DB`. Resolve the user id from the mint/seed response, then:

```bash
mongosh 'mongodb://localhost:27017/GAIA' --quiet --eval \
  'db.todos.countDocuments({user_id:"<USER_ID>"})'
# chat persisted → the conversation + messages exist:
mongosh 'mongodb://localhost:27017/GAIA' --quiet --eval \
  'db.conversations.find({user_id:"<USER_ID>"}).sort({_id:-1}).limit(1).toArray()'
```

---

## 5. Drive one agent layer in isolation (executor / subagents)

The full chain is comms → executor → `handoff` → subagent. §4's `/chat-stream` always enters at comms; these dev-only routes (same mount gate as the rest of `/dev`, §2) enter lower, so you can test one layer without scripting the hops above it. Responses are plain JSON — the agent's final message — not SSE.

```bash
# what can I invoke? (ids are what POST /dev/subagents/{id} accepts)
curl -sfS "http://localhost:${API_PORT:-8000}/api/v1/dev/subagents"

# run the EXECUTOR directly (skips comms entirely)
curl -sfS -X POST "http://localhost:${API_PORT:-8000}/api/v1/dev/executor" \
  -H 'content-type: application/json' \
  -d '{"email":"dev@gaia.local","task":"[[tool:create_todo {\"title\":\"direct\"}]] [[say:Done.]]"}'

# run ONE subagent directly (skips comms AND the executor)
curl -sfS -X POST "http://localhost:${API_PORT:-8000}/api/v1/dev/subagents/gmail" \
  -H 'content-type: application/json' \
  -d '{"email":"dev@gaia.local","task":"list unread emails"}'
```

- Runs reuse the exact production preparation (`prepare_executor_execution` / `prepare_subagent_execution` — the same code the `handoff` tool calls), so a direct run cannot drift from what a real hand-off does.
- Response `{user_id, conversation_id, thread_id, agent, message}` — `message` is the final text to assert on; verify side effects in Mongo (§4).
- Multi-turn: pass the returned `conversation_id` back on the next call — the derived agent thread is reused, so the layer keeps its history.
- Sim directives (§3) work unchanged in `task`; under `--sim` the executor's `retrieve_tools` hop is handled automatically, same as via chat.
- Failures are loud: unknown email → 404 naming the mint fix; unknown subagent id → 400 pointing at `GET /dev/subagents`.

---

## 6. Drive the browser

Every page load is already authenticated (§2), so there is no login step — just navigate and act.

**Interactive / exploratory → agent-browser.** Install with `npm i -g agent-browser && agent-browser install` — a Rust CDP daemon + MCP server with accessibility-tree snapshots, stable element refs (`@e1`), and persistent encrypted profiles. Snapshot → act on the stable element ref → assert. Run `mise dev --agent` (or `--sim`), open `http://localhost:${WEB_PORT:-3000}` (your worktree's `WEB_PORT`), and verify against a snapshot/screenshot before claiming a UI change works. (chrome-devtools MCP is the alternative when you need console/network introspection.)

**Repeatable / scripted → Playwright.** Minimal setup lives in `apps/web/e2e/` (`playwright.config.ts`, `global-setup.ts`, `smoke.spec.ts`, `harness.ts`). One command:

```bash
mise e2e:web          # runs nx run web:e2e against a stack you already started
E2E_SIM=1 mise e2e:web   # also runs the scripted-chat spec (needs `mise dev --sim`)
```

- Start the stack in another terminal first (`mise dev --sim`, or `mise dev --agent` for a real LLM) — `mise e2e:web` does not boot it.
- **Never run `mise seed` for e2e.** `global-setup.ts` resets → mints → seeds `dev@gaia.local` itself through the real dev endpoints; a manual seed is redundant and fights the reset.
- The scripted-chat spec is `test.skip`ped unless `E2E_SIM=1` (it needs the stub's deterministic reply). Ports honor `WEB_PORT` / `API_PORT`.

---

## 7. Drive bot conversations (`gaia-sim`)

`gaia-sim` (package `@gaia/bot-harness`, `apps/bots/harness`) is a fifth `BaseBotAdapter` that runs the **real** shared bot pipeline against the running API while emulating a platform's real limits/converters, and writes a JSONL transcript you assert on. It exercises platform-link, streaming, splitting, and formatting paths without a real Telegram/Slack/WhatsApp connection.

Run it via the nx `sim` target (or `pnpm --filter @gaia/bot-harness dev`). The one-shot `send` mints + links the dev user for you (`POST /api/v1/dev/users` + `/dev/seed`) — no separate `mise seed` needed — then injects the message as `dev-<platform>-<userId>`:

```bash
# one-shot: mint+link the dev user, inject one message emulating a platform,
# print the JSONL transcript (and write it to --out)
pnpm nx run bot-harness:sim -- send --emulate telegram --user dev@gaia.local --out t.jsonl "remind me tomorrow"

# multi-turn YAML scenario with transcript assertions (exits non-zero on failure)
pnpm nx run bot-harness:sim -- run apps/bots/harness/scenarios/plain-reply.yaml --out run.jsonl
```

Flags (see `apps/bots/harness/src/cli.ts`):
- `send`: `--emulate <discord|slack|telegram|whatsapp>` (required), `--user <email>` (required), `--out <file>` (optional), `--api <url>` (optional; default `$GAIA_API_URL` → `http://localhost:${API_PORT:-8000}`), `--channel <id>` (optional). The message is the trailing positional arg.
- `run <scenario.yaml>`: `--out <file>`, `--api <url>`. Scenario schema lives in `apps/bots/harness/src/scenario.types.ts`; starters are in `apps/bots/harness/scenarios/` (`plain-reply.yaml`, `tool-call.yaml`, `multi-turn.yaml`).

Details:
- `--emulate <platform>` pulls that platform's real `PLATFORM_LIMITS` / `STREAMING_DEFAULTS` / markdown converter from `libs/shared/ts/src/bots/` — the only residual is a conformance-locked `supportsEdit` map (`apps/bots/harness/src/emulation.ts`).
- Requires the same `apps/bots/.env` a real bot uses (`GAIA_API_URL`, `GAIA_BOT_API_KEY`, `GAIA_FRONTEND_URL`, `BOT_LOG_HASH_SECRET`) and a running API (real LLM, or the `--sim` stub via §3). Set `RABBITMQ_URL` to record proactive `outbound-delivery` events through the real outbound consumer (a loud warning prints when it is unset).
- Transcript is JSONL events (`inbound`, `send`, `edit`, `typing`, `ephemeral`, `rich`, `split`, `outbound-delivery`) with final rendered payloads — assert on that, not on logs. Types: `apps/bots/harness/src/transcript.types.ts`.
- A golden conformance suite (`apps/bots/__tests__/harness/conformance.test.ts`, wired into `mise test:bots`) drives the harness and the real adapter with only the SDK faked and fails CI if their output diverges. WhatsApp webhook replay lives in `apps/bots/__tests__/whatsapp/webhook-replay.e2e.test.ts`. See `apps/bots/CLAUDE.md`.

---

## 8. When something misbehaves

Read logs with the **`reading-gaia-logs`** skill (wide events, where logs land per mode, Loki/LogQL, LangGraph/Langfuse, bot logs). Common surfaces you'll hit while driving:

| Symptom | Meaning | Fix |
|---|---|---|
| `401 … mint it via POST /api/v1/dev/users` | The bypass/`X-Dev-User` email has no Mongo user (fail-loud, by design). | Mint it (§2) or drop the `X-Dev-User` header. |
| Dev routes 404 (or the web app shows a login screen) | Bypass off — you booted a bare `mise dev` (real login), or `ENV != development`. | Add the flag: `mise dev --agent` / `--sim` (or `mise dev:vm --agent`). |
| Boot aborts: "refusing to enable the dev auth bypass / sim mode with ENV=production" | You passed `--agent`/`--sim` with `ENV=production` (`scripts/dev/assert-not-prod.sh`, by design). | Set `ENV=development` for local driving, or drop the flag. |
| `JuiceFSUnavailable` on a native boot (`mise dev --agent` / `--sim` / bare `dev`) | Native host has no FUSE mount — expected for workspace v2 / file / artifact / sandbox paths. | Switch to `mise dev:vm` (add `--agent` for zero login). Never stub/silence the mount check. |
| Stub returns HTTP 500 echoing a directive | Malformed `[[tool:… <json>]]` args (or a literal `]]` inside them). | Fix the JSON in the message (§3). |
| Telegram `409 Conflict` | Same bot token running twice (dev + Docker, or two worktrees). | Run one instance only — see `parallel-worktrees` + `apps/bots/CLAUDE.md`. |

---

## 9. The full testing map

Every way to test or simulate GAIA, in one table — this skill covers the live-stack rows in depth; the others are pointers so nothing is invisible.

| Surface | Command | Docs |
|---|---|---|
| Chat via comms (SSE, full chain) | `curl POST /api/v1/chat-stream` (§4) | this skill |
| Executor directly | `curl POST /api/v1/dev/executor` (§5) | this skill |
| One subagent directly | `curl POST /api/v1/dev/subagents/{id}` (§5) | this skill |
| Browser (scripted) | `mise e2e:web` / `E2E_SIM=1 mise e2e:web` (§6) | this skill, `apps/web/e2e/` |
| Bots (emulated platforms) | `pnpm nx run bot-harness:sim -- send\|run` (§7) | this skill, `apps/bots/CLAUDE.md` |
| Deterministic LLM | `mise dev --sim` → directives (§3) | this skill, `tools/llm-stub/` |
| Python unit (mocked infra) | `mise test:python:unit` | `apps/api/CLAUDE.md` |
| Python full suite vs live services | `mise test:python` (Dagger local) / CI `test-python` | `apps/api/CLAUDE.md`, `.github/CLAUDE.md` |
| Python e2e tier (incl. device-bridge black box) | `nx run api:test:e2e` | `apps/api/tests/CLAUDE.md` |
| TypeScript tests | `mise test` / `mise test:bots` / `mise test:cli` | `apps/bots/CLAUDE.md` |
| LLM stub's own tests | `uv run --no-project --with pytest pytest tools/llm-stub -q` (§3) | this skill |
| Parallel branches | `wt switch -c …` + per-worktree ports | `parallel-worktrees` skill |
