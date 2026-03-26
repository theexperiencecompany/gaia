# CLAUDE.md — apps/bots

## Overview

This workspace contains three GAIA bot integrations (Discord, Slack, Telegram) plus a shared end-to-end test suite. Each bot is an independent npm package that connects to the GAIA backend by extending `BaseBotAdapter` from `@gaia/shared`.

```
apps/bots/
  discord/     - @gaia/bot-discord  (discord.js v14)
  slack/       - @gaia/bot-slack    (@slack/bolt v4, Socket Mode)
  telegram/    - @gaia/bot-telegram (grammY v1)
  __tests__/   - Vitest e2e/unit tests (run from apps/bots/)
```

## Key Commands

Use **pnpm**, not npm or yarn.

```bash
# Run a bot in dev mode (hot reload via tsx watch)
pnpm --filter @gaia/bot-discord dev
pnpm --filter @gaia/bot-slack dev
pnpm --filter @gaia/bot-telegram dev

# Build (tsup produces dist/index.js)
pnpm --filter @gaia/bot-discord build

# Run tests (always from apps/bots/ — vitest.config.ts lives there)
nx test bots-e2e
# or directly:
cd apps/bots && pnpm vitest run --config vitest.config.ts

# Deploy/register platform commands (run after adding or renaming commands)
pnpm --filter @gaia/bot-discord deploy-commands   # registers Discord slash + context menu commands
pnpm --filter @gaia/bot-telegram set-commands     # pushes command list to Telegram API
# Slack: no manual registration step — slash commands are configured in the Slack App dashboard
```

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

### Unified command system

Commands are defined **once** in `libs/shared/ts/src/bots/commands/` and exported as `allCommands` from `@gaia/shared`. Each `BotCommand` has an `execute(params: CommandExecuteParams)` function that receives a platform-agnostic `RichMessageTarget` — it never touches Discord/Slack/Telegram APIs directly.

The `/gaia` command is special-cased in every adapter to use `handleStreamingChat` instead of the unified `execute` path.

### RichMessageTarget

Each adapter creates a `RichMessageTarget` from its native context (Discord `Interaction`, Slack `respond`, Telegram `ctx`). This target has four methods: `send`, `sendEphemeral`, `sendRich`, `startTyping`. Commands only use these — they never import platform libraries.

### Shared library path alias

`vitest.config.ts` maps `@gaia/shared` to `libs/shared/ts/src/index.ts` directly (not the built output). Tests do not require a prior build of the shared lib.

## Per-Platform Notes

### Discord (`discord/`)

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

- Runs in **Socket Mode** (no public HTTP endpoint needed)
- Every slash command handler must call `ack()` immediately (Slack's 3-second rule). This happens before any async work.
- Slack has **no native embed API**. `sendRich` renders `RichMessage` as markdown via `richMessageToMarkdown`.
- Ephemeral messages (via `respond({ response_type: "ephemeral" })`) **cannot be edited** after sending. The `SentMessage.edit` returned from `sendEphemeral` is a no-op.
- Slack has no typing indicator API for bots. `startTyping` returns a no-op.
- Streaming chat posts an initial "Thinking..." message and updates it via `chat.update` (keyed by the message's `ts` timestamp).
- Auth URLs are sent as ephemeral messages to avoid exposing tokens publicly in a channel.
- Required env vars: `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN`

### Telegram (`telegram/`)

- Runs with **long polling** (no webhook setup needed for dev)
- `/start` is a Telegram convention — the adapter maps it to the `help` command, not a separate handler.
- Bot commands are also registered with Telegram's API via `bot.api.setMyCommands()` inside `registerCommands` (so the "/" suggestion menu stays current). The standalone `set-commands.ts` script does the same thing manually.
- `sendEphemeral` in group chats sends a DM to the user instead of posting publicly. If the user's privacy settings block DMs, the adapter posts a fallback message in the group.
- `sendRich` also DMs rich content in group chats.
- Markdown: all outbound text goes through `convertToTelegramMarkdown` which converts `**bold**` → `*bold*`, headings → bold, strips blockquotes/horizontal rules, and leaves code blocks unchanged. If Telegram rejects the markdown (`"can't parse entities"`), the adapter retries without `parse_mode`.
- Typing indicator refreshes every 5 s (Telegram's typing action expires after ~5 s).
- `hasTelegramMention` / `stripTelegramMention` are exported from `adapter.ts` for testability (case-sensitive string matching, not regex).
- Bot username is fetched once on startup via `bot.api.getMe()` and cached to avoid repeated API calls.
- Required env vars: `TELEGRAM_BOT_TOKEN`

## Testing

- Framework: **Vitest** (not Jest). All test files are under `__tests__/`.
- Tests run sequentially (`fileParallelism: false`, `sequence.concurrent: false`) because some test suites share module-level mocks.
- Timeout: 15 s per test, 10 s for hooks.
- Platform libraries (discord.js, @slack/bolt, grammy) are fully mocked with `vi.mock()`. No real network calls are made.
- `@gaia/shared` is also mocked in adapter tests — its real implementation is tested in `__tests__/shared/`.
- Private adapter methods are accessed in tests via `(adapter as unknown as { method: ... }).method(...)` casting.
- Do not create test files unless explicitly asked.

## Code Rules

- Package manager: **pnpm**
- No inline imports — all imports at the top of the file
- Never use `any` type — use explicit interfaces or `unknown` with narrowing
- Before adding a new type, check `libs/shared/ts/src/bots/types/index.ts` — most domain types (`BotCommand`, `RichMessage`, `CommandContext`, `SentMessage`, `PlatformName`, etc.) are already defined there
- Each bot package is `"type": "module"` (ESM). Avoid CommonJS patterns.
- Build tool is `tsup`; dev runner is `tsx watch`.
