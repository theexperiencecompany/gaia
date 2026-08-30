# apps/bots

Five GAIA chat bots (Discord, Slack, Telegram, WhatsApp, iMessage) plus a shared Vitest suite. Each bot is an independent ESM package that talks to the GAIA backend by extending `BaseBotAdapter` from `@gaia/shared`. All platform-agnostic logic (commands, streaming, markdown, API client, config) lives in `libs/shared/ts/src/bots/` — the per-bot packages are thin adapters.

```
apps/bots/
  discord/    @gaia/bot-discord   (discord.js v14, WebSocket gateway)
  slack/      @gaia/bot-slack     (@slack/bolt v4, Socket Mode)
  telegram/   @gaia/bot-telegram  (grammY, long polling)
  whatsapp/   @gaia/bot-whatsapp  (Kapso proxy, Hono webhook)
  imessage/   @gaia/bot-imessage  (Photon Spectrum SDK, Hono webhook)
  __tests__/  Vitest suite (nx project: bots-e2e)
```

## Commands

```bash
mise dev:bots                    # all five bots in parallel
nx dev bot-discord               # single bot, hot reload (tsx watch)
nx build bot-discord             # tsup → dist/index.js, all deps bundled
nx test bots-e2e                 # Vitest (or: mise test:bots)

# Register platform commands after adding/renaming a command:
pnpm --filter @gaia/bot-discord deploy-commands   # Discord slash + context menu
pnpm --filter @gaia/bot-telegram set-commands     # Telegram /-menu
# Slack: configured in the Slack App dashboard. WhatsApp: matched by text prefix.

mise ci:docker:bot-<platform>    # Dagger Docker build
```

**Single-instance constraint**: Discord and Telegram hold a persistent connection per token. Running `mise dev:bots` while a Docker container runs the same bot causes Telegram `409 Conflict` / Discord gateway disconnects. Run one or the other, not both.

## Architecture

`BaseBotAdapter` (`libs/shared/ts/src/bots/adapter/base.ts`) owns `dispatchCommand`, `buildContext`, the `GaiaClient`, error handling, and the shared `BotServer`. Each bot implements five abstract methods, called in this order by `boot()`:

`initialize` (create SDK client) → `registerCommands` (wire commands) → `registerEvents` (listen for mentions/DMs, mount webhook routes) → `start` (connect) → then `boot()` starts `BotServer` automatically. `stop()` is the only shutdown hook.

Each bot's `index.ts` is three lines: `runBotProcess(new XAdapter(), allCommands)` (`adapter/process-lifecycle.ts`). That owns the whole process lifecycle once — boot, `SIGINT`/`SIGTERM` → `adapter.shutdown(signal)`, and `unhandledRejection` / `uncaughtException` → one final `process_fault` event before a non-zero exit. Do not hand-wire signal handlers in a bot package; without the fault handlers Node prints a raw multi-line V8 stack instead, which carries no `trace_id`, no `service` and no `outcome`, and breaks NDJSON framing for everything the shipper parses after it.

- **BotServer** (`adapter/base-server.ts`): Hono server auto-created in `boot()`, serves `GET /health`. Mount extra routes on `this.botServer.app` inside `registerEvents()` (before it starts). Default ports: discord 3200, slack 3201, telegram 3202, whatsapp 3203, imessage 3204; override with `BOT_SERVER_PORT`. Do not start/stop it manually.
- **Unified commands** (`bots/commands/`): defined once, exported as `allCommands`. Each `BotCommand.execute()` gets a platform-agnostic `RichMessageTarget` (`send`, `sendEphemeral`, `sendRich`, `startTyping`) and never touches a platform SDK. The `/gaia` command is special-cased in every adapter to route through `handleStreamingChat` instead of `execute`.
- **Streaming** (`bots/utils/streaming.ts`): `handleStreamingChat` does throttled edits, cursor indicator, `<NEW_MESSAGE_BREAK>` splitting, and auth-vs-generic error classification. Per-platform behavior in `STREAMING_DEFAULTS`.
- **Markdown**: each platform needs different syntax. Converters in `bots/utils/formatters.ts` (`convertToTelegramMarkdown`, `convertToSlackMrkdwn`, `convertToWhatsAppMarkdown`); all use `applyOutsideCodeBlocks()` to leave fenced code untouched. Discord uses native embeds via `richMessageToEmbed`.
- **Inbound media** (`bots/utils/media.ts`): `processBotMedia`, reached via `BaseBotAdapter.resolveIncomingMedia`, makes one cross-platform decision — video/sticker → polite reply (no download); audio/voice → `gaia.transcribeAudio` (Whisper) becomes the chat message; image/document → `gaia.uploadFile` referenced via `fileIds`/`fileData`. Caps: 10 MB files, 25 MB audio (`BOT_MEDIA_LIMITS`); upload/transcribe failures map to friendly replies via `friendlyMediaError`. Each adapter supplies only the glue — detect type → build `IncomingMedia` → pass a lazy `download` thunk → act on the returned `MediaOutcome` (`reply` vs `chat`). Slack is text-only for now.
- **Auth** (`GaiaClient`, `bots/api/index.ts`): sends `X-Bot-API-Key`, `X-Bot-Platform`, `X-Bot-Platform-User-Id`. Session tokens cached 12 min; on 401 the cache is cleared and the call retried once. Users link accounts via `/auth` → backend issues a 10-min Redis token → web confirm → `platform_links.{platform}` in MongoDB. The "link your account" prompt is one shared string (`buildAuthLinkMessage`) used by both the `/auth` command and every adapter's streaming `onAuthError` — never hardcode an auth message in an adapter. The chat-stream endpoint refuses a turn before any work with a single SSE frame `{"error": <code>}` (`BOT_STREAM_ERROR` in `bots/api/chat-stream.ts`, mirrored by `BOT_STREAM_ERROR_*` in the API's `bot.py`): `not_authenticated` → the auth prompt above; `plan_required` (a linked user whose plan no longer allows a Pro-only platform such as iMessage) → the shared upgrade prompt `buildPlanRequiredMessage`, rendered through the streaming chokepoint like every other generic error.

## Simulation harness (`gaia-sim`)

`apps/bots/harness` (`@gaia/bot-harness`) is a fifth `BaseBotAdapter` for testing: its `gaia-sim` CLI drives the real shared bot pipeline against a running API while emulating a platform's real `PLATFORM_LIMITS` / converters, and writes a JSONL transcript to assert on — no real Discord/Slack/Telegram/WhatsApp connection. A golden conformance suite (`apps/bots/__tests__/harness/`, wired into `mise test:bots`) fails CI if harness output ever diverges from the real adapter's. For how to run it end to end, see the **`driving-gaia`** skill.

## Config

`loadConfig()` (`bots/config/index.ts`) is called inside `boot()`, not the constructor. Resolution order, first wins: process env → `apps/bots/.env` (shared by all bots) → `apps/bots/{platform}/.env` (legacy) → Infisical. dotenv is loaded in code, so no `--require dotenv` flag.

Required for every bot (process throws if missing): `GAIA_API_URL`, `GAIA_BOT_API_KEY` (must equal backend `BOT_API_KEY`), `GAIA_FRONTEND_URL`, `BOT_LOG_HASH_SECRET` (≥64 hex chars = 32 bytes, HMAC key for hashing PII in logs; `openssl rand -hex 32`).

Platform-specific: Discord `DISCORD_BOT_TOKEN` + `DISCORD_CLIENT_ID`; Slack `SLACK_BOT_TOKEN` + `SLACK_SIGNING_SECRET` + `SLACK_APP_TOKEN`; Telegram `TELEGRAM_BOT_TOKEN`; WhatsApp `KAPSO_API_KEY` + `KAPSO_PHONE_NUMBER_ID` + `KAPSO_WEBHOOK_SECRET`; iMessage `SPECTRUM_PROJECT_ID` + `SPECTRUM_PROJECT_SECRET` + `SPECTRUM_WEBHOOK_SECRET`.

Infisical is optional in dev, fatal-if-missing in production, and only fills keys not already in `process.env`. The environment slug comes from `ENV`, falling back to `NODE_ENV === "production"` and otherwise `development`. A bare local checkout therefore resolves `development` with no setup; deployed containers can only resolve `production`, because `apps/bots/Dockerfile` pins `ENV=production` and `docker-compose.prod.yml` sets it again per service. This differs from the Python loaders, which default an absent `ENV` to `production` — deliberate, since `ENV` has never been required in `apps/bots/.env`.

## Logging

`emitBotLogLine()` (`libs/shared/ts/src/bots/utils/logger.ts`) is the single writer for every bot log line — both real-time lines and the `bot_event` wide event from `withWideEvent()`. Each line goes to **two** sinks:

1. **stdout/stderr** (unchanged) — what Promtail's Docker service-discovery job scrapes for dockered bots.
2. **`<logDir>/structured-<YYYY-MM-DD>.json`** (`utils/log-file-sink.ts`) — NDJSON, daily rollover, pruned after 30 days, tailed by Promtail's `gaia_bots_local` file job so a locally-run bot reaches Loki too. Exact port of `_json_file_sink_factory` in `libs/shared/py/logging.py`.

`logDir` resolution: `BOT_LOG_DIR` if set to a non-empty path (set it to an empty string to disable); otherwise `<cwd>/logs` when the process started from `apps/bots/<platform>` — which `nx dev bot-<platform>` does. The bot image runs with WORKDIR `/app`, so no default resolves and the file sink stays off in Docker (stdout is already scraped there). A failed open/write disables the sink permanently, reports once on stderr, and leaves stdout untouched — logging must never take a bot down.

**Field parity is a contract, and it is enforced.** The emitted envelope uses the same key names *and value types* as the Python services (`libs/shared/py/logging.py` + `wide_events.py`) so one LogQL query spans every surface. On every line: `time` (UTC, milliseconds, `Z`), `level`, `env`, `service`, `commit`, `logger`, `message`. On every `bot_event`: `task`, `trace_id`, `duration_ms`, `outcome`, `final_level`, and `errors[]` / `warnings[]` / `audit[]` (entries keyed by `msg`). A thrown value is described by `error_type` (its name) + `error` (its message) — two flat strings, never a nested `error: {...}` object, which is the one shape `| json` cannot unwrap.

Consequences to respect when editing the logger: the **event name lands under `message`**, not `event`; `level` uses **loguru names** (`WARNING`, not `WARN`); a caller field colliding with an envelope key is re-emitted as `ctx_<key>` (same prefix as Python); and `env` resolves `ENV` → `NODE_ENV` → `"development"`, because `env` is GAIA's deployment environment, not Node's build mode. `service` intentionally differs per surface (`discord-bot` vs `gaia-backend`) and must keep matching the Promtail label.

`scripts/ci/wide-event-conformance/run.py` runs both logging stacks for real and diffs what they actually print against each other and against `contract.json`. Change the shape on one side only and the `wide-event-conformance` lane goes red — so mirror the change in `libs/shared/py/` and update `contract.json` in the same commit.

### Wide events at the boundary

Every bot entry point wraps its body in `withWideEvent(task, { platform, component, ...context }, async () => { ... })` — `task` names the unit of work ("command", "chat", "webhook") and is emitted under that key, matching Python's `wide_task("<name>")`, so `sum by (task)` covers bots and workers alike (`libs/shared/ts/src/bots/utils/wide-events.ts`). That boundary is what creates the event, the `trace_id`, and the `duration_ms`/`outcome` fields.

"Entry point" is what the scanner discovers, and it is wider than the platform handlers:

| class | what it looks like | where |
|---|---|---|
| command / event / webhook | `app.command(...)`, `client.on(...)`, `bot.on(...)`, `botServer.app.post("/webhook", …)` | the four adapters |
| error-handler | `bot.catch(...)` (grammY), `app.error(...)` (Bolt) — the terminal handler for anything a middleware threw | adapters |
| signal / fault | `process.on("SIGTERM"…)`, `process.on("uncaughtException"…)` | `adapter/process-lifecycle.ts` |
| worker | `channel.consume(queue, …)` — the outbound RabbitMQ consumer | `consumer/outbound-consumer.ts` |
| lifecycle / dispatch | `boot`, `shutdown`, `dispatchCommand`, `resolveIncomingMedia`, `handleStreamingChat` — named shared boundaries with several independent callers | `adapter/base.ts`, `utils/streaming.ts` |

The last row is also the scanner's only cross-file knowledge, and it is *derived*: a handler that calls one of those names scores as instrumented **only while that function still holds a boundary of its own**. Delete the `withWideEvent` from `shutdown()` and every signal handler that calls it goes dark in the same run.

A boundary is per unit of work, not per layer — do **not** add one in an adapter around a call that already routes through `dispatchCommand` / `handleStreamingChat`, or one turn emits two events with unrelated `trace_id`s. Conversely a real-time line that only restates the boundary event (a `*_received` line in front of it, a `*_completed` line after it) is duplicate volume with no `trace_id` to join on: delete it, or move its unique fields onto the event with `wideLog.set` / `setNs`.

Inside it, use the `wideLog` facade: `wideLog.set({ ... })` / `wideLog.setNs("ns", { ... })` to attach context, `wideLog.warning(...)` / `wideLog.error(...)` for real-time lines that also land in the event's `warnings[]`/`errors[]`, and `wideLog.audit(...)` on anything money-, auth-, or PII-shaped. **Outside a boundary every `wideLog.set()` is a silent no-op** — the fields go nowhere, and no error tells you. A handler that sets fields without a boundary is not instrumented, it is dark.

**No raw platform identifier ever reaches a log field.** A Discord user id, a Telegram chat id and a WhatsApp `wa_id` (a phone number) all identify a person, so they go through `hashLogIdentifier()` and land as `user_hash` / `channel_hash` / `destination_hash` — the names in `BotWideEventFields`, and the only names the shared dashboards know. One concept, one field name: not `chat_hash` on Telegram and `wa_hash` on WhatsApp. `BOT_LOG_HASH_SECRET` is required at boot precisely so this is always available.

A field named like an envelope key (`platform`, `service`, `component`, `message`, `logger`, `level`, `time`, `env`, `commit`) is re-emitted as `ctx_<key>`. That is a bug marker, not a feature: `platform` is already on every line, so `logger.warn("x", { platform })` only produces a `ctx_platform` nobody queries. Drop the field.

**The bots surface is gated at 100/100.** `node scripts/ci/checks.mjs evlog-map-bots` (the TypeScript counterpart of `tools/evlog_map`) discovers every entry point above, scores it on boundary/context/audit/error-handling, and CI runs it as `--min-score 100 --min-entries 23` — the score gate blocks under-instrumented handlers, the entry-count gate blocks a refactor that makes the scanner stop finding them (an empty map scores a perfect 100). Run it locally before pushing. If a check genuinely does not apply, waive it with `// evlog-map-disable-next-line <check-id> -- <reason>`; the `--` reason is mandatory, and waivers are counted in every report.

## Analytics (PostHog)

Separate sink from the wide events above, and a separate purpose: Loki answers *what happened in this session*, PostHog answers *how much do people use this*. Naming and the no-PII rule are in the root `CLAUDE.md`.

- **Client**: `Analytics` (`libs/shared/ts/src/analytics/`), created in `boot()` from `POSTHOG_API_KEY`; a no-op when the key is absent, so a bare local checkout needs no setup. Import it via the subpath — `@gaia/shared/analytics`, never the root barrel, which deliberately does not re-export it (posthog-node pulls in Node-only modules Metro cannot resolve for React Native).
- **Event names**: `BOT_EVENTS` in `analytics/events/bots.ts`. Add there, never inline.
- **distinct_id is never the platform id if the account is linked.** Call `this.resolveDistinctId(platformUserId)`, or `this.analyticsFor(platformUserId)` when handing an identity to a shared helper like `handleStreamingChat`. It returns the stable GAIA user id from `checkAuthStatus`, caches it per process, and emits a one-time `alias` so pre-link history merges into the real profile. Only an unlinked user falls back to `"<platform>:<platformUserId>"`.
- **Do not capture a bot chat turn's submission** — `apps/api/app/api/v1/endpoints/bot.py` already captures `chat:message_submitted` for it against the same id. Duplicating it double-counts every message.
- Capture at the shared chokepoints, not per adapter: `dispatchCommand`, `resolveIncomingMedia` and `handleStreamingChat` each cover all four platforms, so one call there instruments everything and cannot drift between bots.

## Platform gotchas

| | Discord | Slack | Telegram | WhatsApp |
|---|---|---|---|---|
| Connection | WebSocket | Socket Mode | Long polling | Kapso → Hono webhook |
| Streaming | off | on | on | off |
| Edit interval | 1200ms | 1500ms | 1000ms | 2000ms |
| Editing | yes | non-ephemeral only | yes | no (sends new) |
| Ephemeral | flags | response_type | DM fallback | falls back to send |
| Rich msg | embeds | markdown | markdown | markdown |
| Response deadline | 3s | 3s | none | none |
| Max length | 2000 | 4000 | 4096 | 4096 |

- **Discord**: 3s interaction deadline — adapter auto-defers on first `send`. The defer's ephemeral flag is set by whichever of `send`/`sendEphemeral` fires first. Slash commands need `deploy-commands` before they appear. Typing refreshes every 8s; presence rotates every 3 min; DM welcome sent once per user per process. Inbound media mapped from `message.attachments` (`extractDiscordMedia`), downloaded from the public CDN URL.
- **Slack**: every handler `ack()`s immediately (3s rule). No embeds, no typing API (`startTyping` is a no-op). Ephemeral messages cannot be edited (`edit` is a no-op). Auth URLs sent ephemeral to avoid leaking tokens.
- **Telegram**: `/start` maps to the `help` command. `setMyCommands()` runs inside `registerCommands` and via the standalone `set-commands` script. In group chats `sendEphemeral`/`sendRich` DM the user (with a group fallback if DMs are blocked). On a parse error the adapter retries without `parse_mode`. Username cached via `getMe()` on startup. Inbound media mapped from the grammY message (`extractTelegramMedia`), downloaded via `getFile`.
- **iMessage**: Photon Spectrum Cloud POSTs `/webhook`; the spectrum-ts SDK verifies the `X-Spectrum-Signature` HMAC against `SPECTRUM_WEBHOOK_SECRET` and yields `[space, message]` pairs. `platform_user_id` = `sender.id` (E.164 with `+`, or an Apple ID email); `channelId` = `space.id`. Outbound sends go through `im.space.create(handle).send(...)` — no REST send endpoint exists. Shared-pool lines require the recipient registered with the Photon project first (the API's connect flow does this), and only route phone-number handles — a user whose iMessage sends from their Apple ID email gets Photon's canned bounce until they switch Settings → Messages → Send & Receive to their phone number. DMs only; group spaces are ignored. No editing (`edit` sends new), streaming off, plain-text rendering.
- **WhatsApp**: Kapso (`https://api.kapso.ai/meta/whatsapp`) POSTs `/webhook`; signature verified by HMAC-SHA256 over the raw body against `KAPSO_WEBHOOK_SECRET`. `platform_user_id` = wa_id (phone, no leading `+`). Inbound media extracted from the Kapso webhook (`extractMedia`) and downloaded via the Kapso SDK, then routed through the shared `resolveIncomingMedia` pipeline (audio transcribed, images/documents uploaded, video/stickers get a polite reply). Welcome sent once per user per process.

## Conventions

- ESM only (`"type": "module"`). Build is `tsup` with `noExternal: [/.*/]` — bundles every dep into `dist/index.js` so the Docker image ships only `dist/` + `package.json` (no `node_modules`). The one exception is iMessage: Photon's gRPC transport calls `import.meta.resolve()` on `nice-grpc`, `nice-grpc-common` and `@grpc/grpc-js` at runtime, so the Dockerfile stages just those three into the runner and fails the build if any is missing. A `banner` shims `require()` for CJS deps. All bots share one `BOT_NAME`-parameterized `apps/bots/Dockerfile`.
- Before adding a type, check `libs/shared/ts/src/bots/types/index.ts` — `BotCommand`, `RichMessage`, `RichMessageTarget`, `SentMessage`, `PlatformName`, etc. live there.
- `SentMessage` is `{ id: string; edit: (text) => Promise<void> }`. On platforms without edit support, `edit` sends a new message guarded by a sent-once flag.
- Tests use Vitest (not Jest), run sequentially (shared module-level mocks), all platform SDKs and `@gaia/shared` mocked with `vi.mock()`. `vitest.config.ts` aliases `@gaia/shared` to source, so no shared-lib build is needed. Real shared logic is tested in `__tests__/shared/`.

## Adding a new platform

A new bot touches many surfaces beyond this dir: a new package under `apps/bots/`, `PlatformName` + `PLATFORM_LIMITS` + `STREAMING_DEFAULTS` + a markdown converter in `libs/shared/ts/src/bots/`, a `deliverOutbound` implementation in the new adapter plus its outbound queue in **both** `apps/api/app/constants/outbound.py` and `libs/shared/ts/src/bots/consumer/topology.ts` (kept byte-identical — RabbitMQ rejects a divergent redeclare), an nx project + the `bots` release group in `nx.json`, a Docker Compose service, env vars in `.env.example`, backend platform-link + notification-channel + agent-platform-context handlers in `apps/api`, and notification toggles in `apps/web` + `apps/mobile`. Do not start without mapping all of these first.
