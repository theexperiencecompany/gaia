# CLAUDE.md — apps/bots

## Overview

This workspace contains four GAIA bot integrations (Discord, Slack, Telegram, WhatsApp) plus a shared end-to-end test suite. Each bot is an independent npm package that connects to the GAIA backend by extending `BaseBotAdapter` from `@gaia/shared`.

```
apps/bots/
  discord/     - @gaia/bot-discord  (discord.js v14)
  slack/       - @gaia/bot-slack    (@slack/bolt v4, Socket Mode)
  telegram/    - @gaia/bot-telegram (grammY v1)
  whatsapp/    - @gaia/bot-whatsapp (Kapso + Hono webhook)
  __tests__/   - Vitest e2e/unit tests (run from apps/bots/)
```

## Key Commands

Use **pnpm**, not npm or yarn.

```bash
# Run all bots in parallel (mise task)
mise dev:bots

# Run a single bot in dev mode (hot reload via tsx watch)
nx dev bot-discord
nx dev bot-telegram
nx dev bot-slack
nx dev bot-whatsapp

# Build (tsup produces dist/index.js with all deps bundled)
nx build bot-discord

# Run tests (always from apps/bots/ — vitest.config.ts lives there)
nx test bots-e2e

# Deploy/register platform commands (run after adding or renaming commands)
pnpm --filter @gaia/bot-discord deploy-commands   # registers Discord slash + context menu commands
pnpm --filter @gaia/bot-telegram set-commands     # pushes command list to Telegram API
# Slack: no manual registration step — slash commands are configured in the Slack App dashboard
# WhatsApp: no registration step — commands matched by text prefix

# CI Docker builds (Dagger)
mise ci:docker:bot-discord
mise ci:docker:bot-slack
mise ci:docker:bot-telegram
mise ci:docker:bot-whatsapp
```

**Single-instance constraint**: Discord and Telegram use persistent connections (WebSocket / long polling). Only **one instance** can run per token at a time. Running `mise dev:bots` while a Docker container is also running the same bot will cause a `409 Conflict` on Telegram or gateway disconnects on Discord. Stop one before starting the other.

## Configuration Pipeline

Environment variables are resolved in this order (first value wins):

```
1. Process env vars         (Docker -e flags, CI env, shell exports)
2. apps/bots/.env           (shared across all bots, loaded by loadConfig via dotenv)
3. apps/bots/{platform}/.env (legacy/Docker fallback, rarely used)
4. Infisical remote secrets  (fills remaining gaps, local env takes precedence)
```

`loadConfig()` in `libs/shared/ts/src/bots/config/index.ts` handles this. It is called inside `BaseBotAdapter.boot()`, not in the constructor. No `--require dotenv` flags are needed — dotenv is loaded explicitly in code.

After all sources are exhausted, three vars are validated as required:
- `GAIA_API_URL` — backend API URL
- `GAIA_BOT_API_KEY` — shared secret (must match backend's `BOT_API_KEY`)
- `GAIA_FRONTEND_URL` — web app URL for auth redirects

If any are missing, the process throws and exits.

**Infisical** (production secrets manager):
- Optional in dev (skipped if not configured)
- Required in production (`NODE_ENV=production`) — missing Infisical creds = fatal error
- Only injects keys not already set in `process.env`
- Needs: `INFISICAL_TOKEN`, `INFISICAL_PROJECT_ID`, `INFISICAL_MACHINE_IDENTITY_CLIENT_ID`, `INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET`

## Architecture

### Adapter pattern

Every bot follows the same lifecycle:

```
boot(allCommands)
  → initialize()       create platform client
  → registerCommands() wire BotCommand list to platform slash/command handlers
  → registerEvents()   register mention/DM event listeners
  → start()            connect to gateway / start polling
```

The `BaseBotAdapter` (in `libs/shared/ts/src/bots/adapter/base.ts`) owns `dispatchCommand`, `buildContext`, error handling, and the `GaiaClient` instance. Each bot only implements the five abstract methods above.

Shutdown: entry points register `SIGINT`/`SIGTERM` handlers that call `adapter.shutdown()` → `stop()`. No `uncaughtException` or `unhandledRejection` handlers are registered — errors during boot propagate to `main().catch()` and exit with code 1.

### Unified command system

Commands are defined **once** in `libs/shared/ts/src/bots/commands/` and exported as `allCommands` from `@gaia/shared`. Each `BotCommand` has an `execute(params: CommandExecuteParams)` function that receives a platform-agnostic `RichMessageTarget` — it never touches Discord/Slack/Telegram APIs directly.

The `/gaia` command is special-cased in every adapter to use `handleStreamingChat` instead of the unified `execute` path.

### RichMessageTarget

Each adapter creates a `RichMessageTarget` from its native context (Discord `Interaction`, Slack `respond`, Telegram `ctx`, WhatsApp `waId`). This target has four methods: `send`, `sendEphemeral`, `sendRich`, `startTyping`. Commands only use these — they never import platform libraries.

### Streaming

The shared `handleStreamingChat` function in `libs/shared/ts/src/bots/utils/streaming.ts` handles the full streaming lifecycle:
- Text accumulation with throttled edits (respects platform rate limits)
- Cursor indicator display during streaming
- `<NEW_MESSAGE_BREAK>` tag support for splitting long responses
- Error classification: auth vs. generic
- Platform-specific config via `STREAMING_DEFAULTS`

Each platform defines its streaming behavior in `STREAMING_DEFAULTS`:

| Platform  | Streaming | Edit Interval | Notes |
|-----------|-----------|---------------|-------|
| Discord   | false     | 1200ms        | Uses deferred reply + edit |
| Slack     | true      | 1500ms        | Uses chat.update by timestamp |
| Telegram  | true      | 1000ms        | Edits message in-place |
| WhatsApp  | false     | 2000ms        | No edit API; full response sent once |

### Markdown conversion

Each platform has different markdown syntax. The shared library provides:

| Function | Input | Output |
|----------|-------|--------|
| `richMessageToMarkdown(msg, platform)` | `RichMessage` | Platform-appropriate markdown |
| `convertToTelegramMarkdown(text)` | CommonMark | Telegram legacy markdown (`*bold*`) |
| `convertToSlackMrkdwn(text)` | CommonMark | Slack mrkdwn (`*bold*`, `<url\|label>`) |
| `convertToWhatsAppMarkdown(text)` | CommonMark | WhatsApp markdown (`*bold*`, bare URLs) |

All converters use `applyOutsideCodeBlocks()` to preserve fenced code blocks.

### Shared library path alias

`vitest.config.ts` maps `@gaia/shared` to `libs/shared/ts/src/index.ts` directly (not the built output). Tests do not require a prior build of the shared lib.

## Per-Platform Notes

### Discord (`discord/`)

- **Connection**: WebSocket gateway via discord.js Client
- Slash commands must be **deployed** to Discord's API before they appear. Run `pnpm deploy-commands` after any command change. This calls `Routes.applicationCommands(clientId)` globally.
- Interactions have a **3-second deadline**. The adapter auto-defers (`interaction.deferReply()`) on the first `send`/`sendEphemeral`/`sendRich` call to avoid expiry.
- Ephemeral replies defer with `MessageFlags.Ephemeral`. Public replies defer without it. The flag is determined by which method (`send` vs `sendEphemeral`) fires first.
- `sendRich` converts `RichMessage` to a Discord `EmbedBuilder` via `richMessageToEmbed` (exported from `discord/src/adapter.ts`).
- Typing indicator: `sendTyping()` lasts ~10 s; the adapter refreshes it every 8 s.
- Rotating presence statuses cycle every 3 minutes (`ROTATING_STATUSES` array).
- DM welcome embed is sent once per user per process lifetime (tracked in `dmWelcomeSent` Set).
- Context menu commands ("Summarize with GAIA", "Add as Todo") use `MessageContextMenuCommandInteraction` and always reply ephemeral.
- Required env vars: `DISCORD_BOT_TOKEN`, `DISCORD_CLIENT_ID`

### Slack (`slack/`)

- **Connection**: Socket Mode (no public HTTP endpoint needed)
- Every slash command handler must call `ack()` immediately (Slack's 3-second rule). This happens before any async work.
- Slack has **no native embed API**. `sendRich` renders `RichMessage` as markdown via `richMessageToMarkdown`.
- Ephemeral messages (via `respond({ response_type: "ephemeral" })`) **cannot be edited** after sending. The `SentMessage.edit` returned from `sendEphemeral` is a no-op.
- Slack has no typing indicator API for bots. `startTyping` returns a no-op.
- Streaming chat posts an initial "Thinking..." message and updates it via `chat.update` (keyed by the message's `ts` timestamp).
- Auth URLs are sent as ephemeral messages to avoid exposing tokens publicly in a channel.
- Required env vars: `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN`

### Telegram (`telegram/`)

- **Connection**: Long polling (no webhook setup needed for dev)
- `/start` is a Telegram convention — the adapter maps it to the `help` command, not a separate handler.
- Bot commands are also registered with Telegram's API via `bot.api.setMyCommands()` inside `registerCommands` (so the "/" suggestion menu stays current). The standalone `set-commands.ts` script does the same thing manually.
- `sendEphemeral` in group chats sends a DM to the user instead of posting publicly. If the user's privacy settings block DMs, the adapter posts a fallback message in the group.
- `sendRich` also DMs rich content in group chats.
- Markdown: all outbound text goes through `convertToTelegramMarkdown` which converts `**bold**` → `*bold*`, headings → bold, strips blockquotes/horizontal rules, and leaves code blocks unchanged. If Telegram rejects the markdown (`"can't parse entities"`), the adapter retries without `parse_mode`.
- Typing indicator refreshes every 5 s (Telegram's typing action expires after ~5 s).
- `hasTelegramMention` / `stripTelegramMention` are exported from `adapter.ts` for testability (case-sensitive string matching, not regex).
- Bot username is fetched once on startup via `bot.api.getMe()` and cached to avoid repeated API calls.
- Required env vars: `TELEGRAM_BOT_TOKEN`

### WhatsApp (`whatsapp/`)

- **Connection**: HTTP webhook server (Hono + `@hono/node-server`) — Kapso calls `POST /webhook`
- **Kapso** is a Meta WhatsApp Cloud API proxy service at `https://api.kapso.ai/meta/whatsapp`. It simplifies webhook handling and message sending.
- Webhook signature verified via HMAC-SHA256 on raw body against `KAPSO_WEBHOOK_SECRET`. Verification happens in both the API proxy and the bot (defense in depth).
- No slash-command registry step needed — commands matched by text prefix (`/command`)
- Non-command messages (plain text) are treated as chat messages (like Telegram DMs)
- Non-text messages (images, audio, video, documents) receive a helpful reply explaining text-only support
- WhatsApp does **not** support message editing — `SentMessage.edit()` sends a new message instead, guarded by `finalMessageSent` flag to prevent multi-send
- `sendEphemeral` falls back to `send` (no ephemeral concept in WhatsApp)
- `sendRich` renders `RichMessage` via `richMessageToMarkdown` then `convertToWhatsAppMarkdown` to convert `**bold**` → `*bold*` and `[label](url)` → `label (url)`
- Typing indicator: shown via `messages.markRead({ typingIndicator: { type: 'text' } })` at the start of every incoming message. Auto-dismisses after ~25s or when a reply is sent. Refreshed every 20s. `startTyping()` on the target is a no-op.
- Welcome message sent once per user per process lifetime (tracked in `welcomeSent` Set), matching Discord's DM welcome pattern
- Streaming is **disabled** (`streaming: false`) — full response sent once complete
- `platform_user_id` = wa_id (phone number without leading `+`, e.g. `"15551234567"`)
- **Webhook architecture**: Public webhook at `api.heygaia.io/api/v1/webhook/whatsapp` verifies signature, then forwards to internal bot container on Docker network (`http://whatsapp-bot:3001/webhook`). This keeps port 3001 off public internet.
- Required env vars: `KAPSO_API_KEY`, `KAPSO_PHONE_NUMBER_ID`, `KAPSO_WEBHOOK_SECRET`, `WHATSAPP_WEBHOOK_PORT`

## Testing

- Framework: **Vitest** (not Jest). All test files are under `__tests__/`.
- Tests run sequentially (`fileParallelism: false`, `sequence.concurrent: false`) because some test suites share module-level mocks.
- Timeout: 15 s per test, 10 s for hooks.
- Platform libraries (discord.js, @slack/bolt, grammy, @kapso/whatsapp-cloud-api) are fully mocked with `vi.mock()`. No real network calls are made.
- `@gaia/shared` is also mocked in adapter tests — its real implementation is tested in `__tests__/shared/`.
- Private adapter methods are accessed in tests via `(adapter as unknown as { method: ... }).method(...)` casting.
- Do not create test files unless explicitly asked.

### Test file organization

```
__tests__/
  discord/
    adapter.test.ts       - Discord adapter behavior tests
  slack/
    adapter.test.ts       - Slack adapter behavior tests
  telegram/
    adapter.test.ts       - Telegram adapter behavior tests
    mention.test.ts       - Mention detection/stripping + markdown tests
  whatsapp/
    adapter.test.ts       - WhatsApp adapter behavior tests (welcome, media, streaming, commands)
    webhook.test.ts       - Pure webhook utilities (signature, wa_id extraction, message filtering)
  shared/
    adapter/
      rich-renderer.test.ts - RichMessage → markdown rendering tests
    utils/
      commands.test.ts      - Unified command handler tests (todo, workflow, conversations)
      formatters.test.ts    - Formatter tests (Telegram/Slack/WhatsApp markdown, errors, display)
      text-utils.test.ts    - parseTextArgs, truncateResponse tests
```

## Code Rules

- Package manager: **pnpm**
- No inline imports — all imports at the top of the file
- Never use `any` type — use explicit interfaces or `unknown` with narrowing
- Before adding a new type, check `libs/shared/ts/src/bots/types/index.ts` — most domain types (`BotCommand`, `RichMessage`, `CommandContext`, `SentMessage`, `PlatformName`, etc.) are already defined there
- Each bot package is `"type": "module"` (ESM). Avoid CommonJS patterns.
- Build tool is `tsup`; dev runner is `tsx watch`.

## Adding a New Bot

This is a complete checklist for integrating a new messaging platform into GAIA. Follow every step — skipping any will result in a partially working integration.

### 1. Scaffold the bot package

Create `apps/bots/{platform}/` with the following files:

```
apps/bots/{platform}/
  src/
    adapter.ts    - Main adapter extending BaseBotAdapter
    index.ts      - Entry point (create adapter, call boot, handle signals)
  package.json    - ESM package with platform SDK dependency
  tsconfig.json   - TypeScript config (target ES2022, module ESNext)
  tsup.config.ts  - Build config (format esm, target node20+)
```

**`tsup.config.ts`** must match the standard config used by all bots:

```typescript
import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: "esm",
  target: "node20",
  outDir: "dist",
  clean: true,
  noExternal: [/.*/],      // Bundle ALL dependencies into dist/index.js (required for Docker)
  banner: {
    js: `import{createRequire}from"module";const require=createRequire(import.meta.url);`,
  },
});
```

The `noExternal` flag bundles everything into a single file so the Docker production image only needs `dist/` and `package.json` — no `node_modules`. The `banner` shims `require()` for any CJS dependencies consumed from ESM.

**`package.json`** must include:
- `"name": "@gaia/bot-{platform}"`
- `"type": "module"`
- `"private": true`
- `"@gaia/shared": "workspace:*"` as a dependency
- The platform's SDK as a dependency
- Scripts: `build`, `dev`, `start`

**`tsconfig.json`** is identical for all bots:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true
  },
  "include": ["src"],
  "exclude": ["node_modules", "dist"]
}
```

**`index.ts`** is always the same pattern:

```typescript
import { allCommands } from "@gaia/shared";
import { {Platform}Adapter } from "./adapter";

const adapter = new {Platform}Adapter();
adapter.boot(allCommands).catch((err) => {
  console.error("Failed to boot:", err);
  process.exit(1);
});

process.on("SIGINT", () => adapter.stop().then(() => process.exit(0)));
process.on("SIGTERM", () => adapter.stop().then(() => process.exit(0)));
```

### 2. Implement the adapter

Your adapter class must extend `BaseBotAdapter` and implement:

```typescript
class {Platform}Adapter extends BaseBotAdapter {
  readonly platform: PlatformName = "{platform}";

  protected async initialize(): Promise<void> { /* create SDK client */ }
  protected async registerCommands(commands: BotCommand[]): Promise<void> { /* wire commands */ }
  protected async registerEvents(): Promise<void> { /* listen for messages */ }
  protected async start(): Promise<void> { /* connect/start */ }
  protected async stop(): Promise<void> { /* graceful shutdown */ }
}
```

#### Key decisions for each method:

**`initialize()`**: Load config from env vars, create the platform SDK client. Validate required env vars and throw if missing.

**`registerCommands()`**: Wire the command list to the platform's command system. Options:
- **Discord**: Deploy slash commands via REST API
- **Telegram**: Register via `bot.api.setMyCommands()`
- **Slack**: Configured externally in the Slack App dashboard
- **WhatsApp/others**: No registration needed — match by text prefix

**`registerEvents()`**: Subscribe to incoming messages. Route them to:
- Commands (text starting with `/`) → `this.dispatchCommand(name, target, args)`
- Chat messages → `handleStreamingChat(this.gaia, request, ...callbacks)`
- Non-text messages → graceful rejection message

**`start()`**: Connect to the platform (WebSocket, long polling, or HTTP server).

**`stop()`**: Clean up connections, close servers, clear intervals.

#### Creating a RichMessageTarget

Every adapter must create a `RichMessageTarget` for each incoming message context. This is the bridge between platform-agnostic commands and platform-specific message sending.

```typescript
private createTarget(/* platform context */): RichMessageTarget {
  return {
    platform: "{platform}",
    userId: /* platform user ID */,
    channelId: /* channel/conversation ID */,
    send: async (text) => { /* send a message, return SentMessage */ },
    sendEphemeral: async (text) => { /* send user-only message, or fallback to send */ },
    sendRich: async (richMsg) => { /* render RichMessage for this platform */ },
    startTyping: async () => { /* show typing indicator, return stop function */ },
  };
}
```

#### SentMessage contract

`send` and `sendEphemeral` must return `{ id: string, edit: (text: string) => Promise<void> }`.
- `id` — the platform's message ID
- `edit` — updates the message in-place, or sends a new message if the platform doesn't support edits

### 3. Handle platform-specific concerns

Research and document these for your platform:

| Concern | What to decide |
|---------|---------------|
| **Connection type** | WebSocket, long polling, HTTP webhook, or Socket Mode? |
| **Message editing** | Does the platform support editing sent messages? If not, `SentMessage.edit` should send a new message with a guard flag to prevent multi-send. |
| **Ephemeral messages** | Does the platform support user-only messages? If not, `sendEphemeral` falls back to `send`. |
| **Rich messages** | Native embeds (Discord), or render as markdown? If markdown, add a `convertTo{Platform}Markdown()` function in `libs/shared/ts/src/bots/utils/formatters.ts`. |
| **Typing indicator** | How long does the platform show "typing"? Set a refresh interval accordingly. |
| **Streaming** | Can you edit messages fast enough for streaming? If not, set `streaming: false` in `STREAMING_DEFAULTS`. |
| **Rate limits** | What are the API rate limits? Set `editIntervalMs` accordingly. |
| **Response deadline** | Does the platform require a response within N seconds? (Discord: 3s, Slack: 3s) If so, defer immediately. |
| **Media messages** | What non-text message types can arrive? Reply gracefully to unsupported types. |
| **Group vs DM** | Does the bot need different behavior in groups vs DMs? (Telegram does.) |
| **Welcome message** | Send a welcome on first contact per-process lifetime (tracked via a Set). |
| **Command registration** | Does the platform have a command menu that needs updating? Add a registration script if so. |

### 4. Add markdown conversion (if needed)

If the platform uses different markdown syntax from CommonMark, add a converter in `libs/shared/ts/src/bots/utils/formatters.ts`:

```typescript
export function convertTo{Platform}Markdown(text: string): string {
  return applyOutsideCodeBlocks(text, (segment) =>
    segment
      .replace(/\*\*\*(.+?)\*\*\*/g, "*$1*")   // ***bold italic*** → platform bold
      .replace(/\*\*(.+?)\*\*/g, "*$1*")         // **bold** → platform bold
      // ... platform-specific conversions
  );
}
```

Apply it in `sendRich` after `richMessageToMarkdown()`, and optionally to streaming responses.

### 5. Add streaming defaults

In `libs/shared/ts/src/bots/utils/streaming.ts`, add your platform to `STREAMING_DEFAULTS`:

```typescript
{platform}: {
  editIntervalMs: 1500,   // milliseconds between message edits
  streaming: true,         // or false if edits not supported
  platform: "{platform}",
}
```

### 6. Update shared types

In `libs/shared/ts/src/bots/types/index.ts`:
- Add `"{platform}"` to the `PlatformName` union type
- Add platform to `PLATFORM_LIMITS` in `libs/shared/ts/src/bots/utils/index.ts` (character limit)

### 7. Wire into Nx

**`apps/bots/{platform}/project.json`**:

```json
{
  "$schema": "../../../node_modules/nx/schemas/project-schema.json",
  "name": "bot-{platform}",
  "root": "apps/bots/{platform}",
  "sourceRoot": "apps/bots/{platform}/src",
  "projectType": "application",
  "release": {
    "docker": {
      "repositoryName": "theexperiencecompany/gaia-bot-{platform}"
    }
  },
  "targets": {
    "build": { "executor": "nx:run-commands", "options": { "command": "pnpm tsup", "cwd": "{projectRoot}" } },
    "dev": { "executor": "nx:run-commands", "options": { "command": "pnpm tsx watch src/index.ts", "cwd": "{projectRoot}" } },
    "lint": { "executor": "nx:run-commands", "options": { "command": "pnpm biome check src/", "cwd": "{projectRoot}" } },
    "type-check": { "executor": "nx:run-commands", "options": { "command": "pnpm tsc --noEmit", "cwd": "{projectRoot}" } },
    "docker:build": {
      "executor": "nx:run-commands",
      "options": {
        "command": "docker build -f apps/bots/Dockerfile --build-arg BOT_NAME={platform} -t ghcr.io/theexperiencecompany/gaia-bot-{platform}:latest ."
      }
    }
  }
}
```

**`nx.json`** — add `"bot-{platform}"` to the `bots` release group `projects` array and the `groupPreVersionCommand`.

### 8. Wire into Docker

The shared `apps/bots/Dockerfile` is parameterized by `BOT_NAME` build arg — no Dockerfile changes needed.

**`infra/docker/docker-compose.yml`** — add a service:

```yaml
{platform}-bot:
  container_name: {platform}-bot
  profiles: ["bots", "all"]
  build:
    context: ../..
    dockerfile: apps/bots/Dockerfile
    args:
      BOT_NAME: {platform}
  env_file:
    - ../../apps/bots/.env
  restart: on-failure
  depends_on:
    gaia-backend:
      condition: service_healthy
  networks:
    - gaia_network
```

If the bot runs an HTTP server (like WhatsApp), expose the port:
```yaml
  ports:
    - "${PORT_VAR:-default}:port"
```

**`infra/docker/docker-compose.prod.yml`** — add the same service using the pre-built image:
```yaml
  image: ghcr.io/theexperiencecompany/gaia-bot-{platform}:latest
```

### 9. Add to workspace dependencies

**`apps/bots/package.json`** — add `"@gaia/bot-{platform}": "workspace:*"` to dependencies.

### 10. Add environment variables

**`apps/bots/.env.example`** — add all required env vars with descriptions.

### 11. Backend integration (if webhook-based)

If the platform uses webhooks (like WhatsApp), you need a **two-hop architecture**: external service → API proxy → internal bot container. This keeps the bot's webhook port off the public internet and consolidates TLS termination at the API layer.

```
[External Service] → POST api.heygaia.io/api/v1/webhook/{platform}
                           ↓ (verify signature)
                     [API Proxy] → POST http://{platform}-bot:3001/webhook
                                         ↓ (verify signature again, defense in depth)
                                   [Bot Container] → process message
```

1. **API webhook proxy** (`apps/api/app/api/v1/endpoints/webhook_{platform}.py`):
   - Route: `POST /api/v1/webhook/{platform}`
   - Verifies platform-specific webhook signature (HMAC, etc.)
   - Reads internal bot URL from settings (e.g. `{PLATFORM}_BOT_URL`)
   - Forwards raw body + relevant headers via `httpx` to internal bot
   - Returns 200 immediately to the external service
   - Handles 502 (bot unavailable) and 504 (bot timeout) errors
   - Register the router in `apps/api/app/api/v1/routes.py`

2. **Signature verification** (`apps/api/app/utils/webhook_utils.py`):
   - Add a `verify_{platform}_webhook_signature(request)` function
   - Use timing-safe comparison (`hmac.compare_digest`)
   - Raise 401 if invalid, 503 if secret not configured

3. **API settings** (`apps/api/app/config/settings.py`):
   - Add to both `DevelopmentSettings` and `ProductionSettings`:
     - `{PLATFORM}_BOT_URL: str` — internal Docker network URL (e.g. `"http://{platform}-bot:3001"`)
     - API keys, phone numbers, webhook secrets as needed
   - Document each setting with examples in comments

### 12. Notification channel

To send proactive notifications (not just replies):

1. **Channel adapter** (`apps/api/app/utils/notification/channels/{platform}.py`):
   - Extend `ExternalPlatformAdapter`
   - Implement `send_notification()` using the platform's API
   - Define `channel_type`, `max_message_length`, `bold_marker`

2. **Constants** (`apps/api/app/constants/notifications.py`):
   - Add `CHANNEL_TYPE_{PLATFORM}`
   - Add to `ALL_AUTO_INJECTED_CHANNELS`
   - Add to `DEFAULT_CHANNEL_PREFERENCES`

3. **Models** (`apps/api/app/models/notification/notification_models.py`):
   - Add `{platform}: bool` field to `ChannelPreferences`
   - Add `{platform}: Optional[bool]` to `ChannelPreferencesUpdate`

4. **Orchestrator** (`apps/api/app/utils/notification/orchestrator.py`):
   - Register the new adapter in `_register_default_components()`

5. **Frontend** (`apps/web/src/features/settings/components/NotificationSettings.tsx`):
   - Add platform to `NOTIFICATION_PLATFORMS` array
   - Add platform icon to `public/images/icons/macos/`

6. **Mobile** (`apps/mobile/src/features/settings/`):
   - Update `ChannelPreferences` type in `api/settings-api.ts` (add `{platform}: boolean`)
   - Update `updateChannelPreference()` platform union type to include `"{platform}"`
   - Add `SettingsSwitchRow` toggle in `components/sections/notification-section.tsx`
   - Icon: add to `apps/mobile/src/lib/gaia-icons.tsx` via `createIcon("{Platform}Icon")`, import from `@/components/icons`
   - Update initial state, `updatingChannel` type, and `handleToggle` type to include `"{platform}"`

### 13. Platform linking / auth

Users link their platform account to GAIA via:

1. Bot sends `/auth` → backend creates a time-limited link token (Redis, 10-min TTL)
2. User visits web URL with the token
3. Web app confirms connection, stores `platform_links.{platform}` in MongoDB
4. Backend can now identify the user by `platform_user_id`

Add the platform to:
- `apps/api/app/api/v1/endpoints/platform_links.py` — `initiate_platform_connect()` handler
- `apps/api/app/services/platform_link_service.py` — platform enum/validation
- Bot auth headers: `X-Bot-Platform: {platform}`, `X-Bot-Platform-User-Id: {id}`

### 14. Agent platform context

The LangGraph agent adjusts its output based on the platform:
- `apps/api/app/agents/core/nodes/message_helpers.py` — `get_platform_context_message()`
  - Add formatting instructions for the new platform
  - Specify which markdown syntax works (bold, italic, code, links)
  - Note: messaging platforms should NOT use artifacts, HTML, or files

### 15. Write tests

Create `apps/bots/__tests__/{platform}/adapter.test.ts` following the existing patterns:

1. Mock the platform SDK with `vi.mock()`
2. Mock `@gaia/shared` with a `BaseBotAdapter` stub
3. Create a `makeAdapter()` helper that injects mock client + config
4. Use `PrivateAdapter` type cast to access private methods
5. Test: platform identity, message sending, editing, rich messages, typing, command routing, streaming, welcome message, media handling, error callbacks

Also create `__tests__/{platform}/webhook.test.ts` if the bot uses webhooks (pure function tests, no mocks needed).

### 16. Quality checks

Run before considering work complete:

```bash
nx type-check bot-{platform}
nx lint bot-{platform}
nx test bots-e2e
```

### Platform comparison reference

| Feature | Discord | Slack | Telegram | WhatsApp |
|---------|---------|-------|----------|----------|
| Connection | WebSocket | Socket Mode | Long polling | HTTP webhook |
| Message editing | Yes | Yes (non-ephemeral) | Yes | No |
| Ephemeral messages | Yes (flags) | Yes (response_type) | DM fallback | No |
| Native embeds | Yes (EmbedBuilder) | No | No | No |
| Typing indicator | ~10s, refresh 8s | No API | ~5s, refresh 5s | ~25s, refresh 20s |
| Streaming | Disabled | Enabled | Enabled | Disabled |
| Command menu | Slash commands API | App dashboard | setMyCommands API | Text prefix only |
| Response deadline | 3 seconds | 3 seconds | None | None |
| Markdown syntax | `**bold**` | `*bold*` | `*bold*` | `*bold*` |
| Link syntax | `[label](url)` | `<url\|label>` | `[label](url)` | Bare URLs |
| Max message length | 2000 | 4000 | 4096 | 4096 |
| Welcome message | DM embed + buttons | None | None | Text markdown |
| Media support | Text only | Text only | Text only | Text only (graceful rejection) |
| Auth flow | Link token + web | Link token + web | Link token + web | Link token + web |
| Webhook proxy | No | No | No | Yes (API → bot) |

### Docker build

All bots share a single parameterized `apps/bots/Dockerfile`:

```dockerfile
ARG BOT_NAME
FROM node:20-alpine AS builder
# Copies pnpm-workspace.yaml, libs/shared/ts, and apps/bots/${BOT_NAME}
# Runs pnpm install --frozen-lockfile, then pnpm --filter @gaia/bot-${BOT_NAME} build

FROM node:20-alpine AS runner
# Copies only dist/ and package.json from builder
# Runs as non-root 'node' user
# CMD ["node", "dist/index.js"]
```

Because `noExternal: [/.*/]` in tsup bundles everything into `dist/index.js`, the production image has no `node_modules` and is very small (~50MB). The `BOT_NAME` build arg selects which bot to build.

### Env vars

All bots read from a single `apps/bots/.env` file (shared via `env_file` in Docker Compose). Platform-specific vars are only read by the bot that needs them. The `.env.example` documents every variable.

Shared vars (required by all bots):
- `GAIA_API_URL` — backend URL (e.g. `http://localhost:8000` or `http://gaia-backend:8000`)
- `GAIA_BOT_API_KEY` — must match the backend's `BOT_API_KEY` setting
- `GAIA_FRONTEND_URL` — web app URL for auth redirects (e.g. `https://heygaia.io`)

### GaiaClient authentication

The `GaiaClient` (in `libs/shared/ts/src/bots/api/index.ts`) authenticates with the backend using:
- `X-Bot-API-Key` — shared secret between bot and backend
- `X-Bot-Platform` — `"discord"`, `"slack"`, `"telegram"`, or `"whatsapp"`
- `X-Bot-Platform-User-Id` — platform-specific user ID

Session tokens are cached client-side (12-min TTL) to avoid repeated auth calls. On 401, the token cache is cleared and retried once.

### Key shared library files

| File | Purpose |
|------|---------|
| `libs/shared/ts/src/bots/adapter/base.ts` | `BaseBotAdapter` — abstract lifecycle, command dispatch |
| `libs/shared/ts/src/bots/adapter/rich-renderer.ts` | `richMessageToMarkdown()` — RichMessage to text |
| `libs/shared/ts/src/bots/types/index.ts` | All type definitions (BotCommand, RichMessage, PlatformName, etc.) |
| `libs/shared/ts/src/bots/api/index.ts` | `GaiaClient` — authenticated API client for bot endpoints |
| `libs/shared/ts/src/bots/utils/streaming.ts` | `handleStreamingChat()` + `STREAMING_DEFAULTS` |
| `libs/shared/ts/src/bots/utils/formatters.ts` | Markdown converters, error formatter, display formatters |
| `libs/shared/ts/src/bots/utils/index.ts` | `parseTextArgs()`, `truncateResponse()`, `PLATFORM_LIMITS` |
| `libs/shared/ts/src/bots/commands/` | All unified command handlers (help, auth, todo, workflow, etc.) |
| `libs/shared/ts/src/bots/config/index.ts` | `loadConfig()` — env var loading |
