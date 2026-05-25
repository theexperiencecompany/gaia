# apps/bots

Four GAIA chat bots (Discord, Slack, Telegram, WhatsApp) plus a shared Vitest suite. Each bot is an independent ESM package that talks to the GAIA backend by extending `BaseBotAdapter` from `@gaia/shared`. All platform-agnostic logic (commands, streaming, markdown, API client, config) lives in `libs/shared/ts/src/bots/` — the per-bot packages are thin adapters.

```
apps/bots/
  discord/    @gaia/bot-discord   (discord.js v14, WebSocket gateway)
  slack/      @gaia/bot-slack     (@slack/bolt v4, Socket Mode)
  telegram/   @gaia/bot-telegram  (grammY, long polling)
  whatsapp/   @gaia/bot-whatsapp  (Kapso proxy, Hono webhook)
  __tests__/  Vitest suite (nx project: bots-e2e)
```

## Commands

```bash
mise dev:bots                    # all four bots in parallel
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

`initialize` (create SDK client) → `registerCommands` (wire commands) → `registerEvents` (listen for mentions/DMs, mount webhook routes) → `start` (connect) → then `boot()` starts `BotServer` automatically. `stop()` is the only shutdown hook; entry points wire `SIGINT`/`SIGTERM` to it.

- **BotServer** (`adapter/base-server.ts`): Hono server auto-created in `boot()`, serves `GET /health`. Mount extra routes on `this.botServer.app` inside `registerEvents()` (before it starts). Default ports: discord 3200, slack 3201, telegram 3202, whatsapp 3203; override with `BOT_SERVER_PORT`. Do not start/stop it manually.
- **Unified commands** (`bots/commands/`): defined once, exported as `allCommands`. Each `BotCommand.execute()` gets a platform-agnostic `RichMessageTarget` (`send`, `sendEphemeral`, `sendRich`, `startTyping`) and never touches a platform SDK. The `/gaia` command is special-cased in every adapter to route through `handleStreamingChat` instead of `execute`.
- **Streaming** (`bots/utils/streaming.ts`): `handleStreamingChat` does throttled edits, cursor indicator, `<NEW_MESSAGE_BREAK>` splitting, and auth-vs-generic error classification. Per-platform behavior in `STREAMING_DEFAULTS`.
- **Markdown**: each platform needs different syntax. Converters in `bots/utils/formatters.ts` (`convertToTelegramMarkdown`, `convertToSlackMrkdwn`, `convertToWhatsAppMarkdown`); all use `applyOutsideCodeBlocks()` to leave fenced code untouched. Discord uses native embeds via `richMessageToEmbed`.
- **Auth** (`GaiaClient`, `bots/api/index.ts`): sends `X-Bot-API-Key`, `X-Bot-Platform`, `X-Bot-Platform-User-Id`. Session tokens cached 12 min; on 401 the cache is cleared and the call retried once. Users link accounts via `/auth` → backend issues a 10-min Redis token → web confirm → `platform_links.{platform}` in MongoDB.

## Config

`loadConfig()` (`bots/config/index.ts`) is called inside `boot()`, not the constructor. Resolution order, first wins: process env → `apps/bots/.env` (shared by all bots) → `apps/bots/{platform}/.env` (legacy) → Infisical. dotenv is loaded in code, so no `--require dotenv` flag.

Required for every bot (process throws if missing): `GAIA_API_URL`, `GAIA_BOT_API_KEY` (must equal backend `BOT_API_KEY`), `GAIA_FRONTEND_URL`, `BOT_LOG_HASH_SECRET` (≥32 chars, HMAC key for hashing PII in logs; `openssl rand -hex 32`).

Platform-specific: Discord `DISCORD_BOT_TOKEN` + `DISCORD_CLIENT_ID`; Slack `SLACK_BOT_TOKEN` + `SLACK_SIGNING_SECRET` + `SLACK_APP_TOKEN`; Telegram `TELEGRAM_BOT_TOKEN`; WhatsApp `KAPSO_API_KEY` + `KAPSO_PHONE_NUMBER_ID` + `KAPSO_WEBHOOK_SECRET`.

Infisical is optional in dev, fatal-if-missing when `NODE_ENV=production`, and only fills keys not already in `process.env`.

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

- **Discord**: 3s interaction deadline — adapter auto-defers on first `send`. The defer's ephemeral flag is set by whichever of `send`/`sendEphemeral` fires first. Slash commands need `deploy-commands` before they appear. Typing refreshes every 8s; presence rotates every 3 min; DM welcome sent once per user per process.
- **Slack**: every handler `ack()`s immediately (3s rule). No embeds, no typing API (`startTyping` is a no-op). Ephemeral messages cannot be edited (`edit` is a no-op). Auth URLs sent ephemeral to avoid leaking tokens.
- **Telegram**: `/start` maps to the `help` command. `setMyCommands()` runs inside `registerCommands` and via the standalone `set-commands` script. In group chats `sendEphemeral`/`sendRich` DM the user (with a group fallback if DMs are blocked). On a parse error the adapter retries without `parse_mode`. Username cached via `getMe()` on startup.
- **WhatsApp**: Kapso (`https://api.kapso.ai/meta/whatsapp`) POSTs `/webhook`; signature verified by HMAC-SHA256 over the raw body against `KAPSO_WEBHOOK_SECRET`. `platform_user_id` = wa_id (phone, no leading `+`). Non-text messages get a text-only-support reply. Welcome sent once per user per process.

## Conventions

- ESM only (`"type": "module"`). Build is `tsup` with `noExternal: [/.*/]` — bundles every dep into `dist/index.js` so the Docker image ships only `dist/` + `package.json` (no `node_modules`). A `banner` shims `require()` for CJS deps. All bots share one `BOT_NAME`-parameterized `apps/bots/Dockerfile`.
- Before adding a type, check `libs/shared/ts/src/bots/types/index.ts` — `BotCommand`, `RichMessage`, `RichMessageTarget`, `SentMessage`, `PlatformName`, etc. live there.
- `SentMessage` is `{ id: string; edit: (text) => Promise<void> }`. On platforms without edit support, `edit` sends a new message guarded by a sent-once flag.
- Tests use Vitest (not Jest), run sequentially (shared module-level mocks), all platform SDKs and `@gaia/shared` mocked with `vi.mock()`. `vitest.config.ts` aliases `@gaia/shared` to source, so no shared-lib build is needed. Real shared logic is tested in `__tests__/shared/`.

## Adding a new platform

A new bot touches many surfaces beyond this dir: a new package under `apps/bots/`, `PlatformName` + `PLATFORM_LIMITS` + `STREAMING_DEFAULTS` + a markdown converter in `libs/shared/ts/src/bots/`, an nx project + the `bots` release group in `nx.json`, a Docker Compose service, env vars in `.env.example`, backend platform-link + notification-channel + agent-platform-context handlers in `apps/api`, and notification toggles in `apps/web` + `apps/mobile`. Do not start without mapping all of these first.
