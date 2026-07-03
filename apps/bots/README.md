# GAIA Bots — Setup & Required Permissions

GAIA ships chat bots for **Discord, Slack, Telegram, and WhatsApp**. Each bot is
a thin adapter over the shared logic in `libs/shared/ts/src/bots/` and talks to
the GAIA backend over REST/SSE (inbound) and RabbitMQ (outbound). This document
is the canonical reference for the **permissions, scopes, and credentials** each
platform needs when you install the bot into a new workspace/server.

> Credentials go in `apps/bots/.env` (shared by all four bots). See
> `apps/bots/.env.example` for the variable list and where each value comes from.

---

## Discord

**App:** Discord Developer Portal → your application.

| Requirement | Where | Notes |
|---|---|---|
| Bot token | Bot → Token → `DISCORD_BOT_TOKEN` | Gateway login |
| Client ID | OAuth2 → `DISCORD_CLIENT_ID` | Used by `deploy-commands` |
| **Privileged intent: MESSAGE CONTENT** | Bot → Privileged Gateway Intents | **Must be toggled ON** — the bot requests `MessageContent` and won't connect without it enabled. Required to read DM/message text. |
| Gateway intents (in code) | `apps/bots/discord/src/adapter.ts` | `Guilds`, `GuildMessages`, `MessageContent`, `DirectMessages` + partials `Channel`, `Message` |

**Invite the bot** with both scopes — `bot` **and** `applications.commands`:

```text
https://discord.com/oauth2/authorize?client_id=<CLIENT_ID>&scope=bot+applications.commands&permissions=2147568640
```

Bot permissions in `permissions=2147568640`: View Channels, Send Messages,
Embed Links, Read Message History, Use Application Commands.

> Run `pnpm --filter @gaia/bot-discord deploy-commands` after adding/renaming a
> command so the slash commands register.
>
> **Known gotcha:** a bot only receives **DM** `MESSAGE_CREATE` over the gateway
> for an established bot↔user DM relationship. If DMs aren't received despite
> correct intents (slash commands still work), the DM channel relationship is the
> issue — start a fresh DM with the bot. Guild @mentions use a separate path.

---

## Slack

**App:** api.slack.com/apps → your app. Uses **Socket Mode** (no public URL).

| Requirement | Where | Notes |
|---|---|---|
| Bot User OAuth Token (`xoxb-`) | OAuth & Permissions → `SLACK_BOT_TOKEN` | |
| App-Level Token (`xapp-`) | Basic Information → App-Level Tokens, scope `connections:write` → `SLACK_APP_TOKEN` | **Required for Socket Mode.** Not the `xoxp-` user token — using that fails with `not_allowed_token_type`. |
| Signing Secret | Basic Information → `SLACK_SIGNING_SECRET` | |

**Bot Token Scopes** (OAuth & Permissions):

| Scope | Why |
|---|---|
| `app_mentions:read` | receive @mentions |
| `chat:write` | send messages |
| `im:write` | **open a DM with a user** (`conversations.open`) — required for outbound DMs (connection confirmation, reminders). Missing this fails with `missing_scope`. |
| `im:history` | read DM content |
| `commands` | slash commands |
| `assistant:write` | act as an app agent |
| `incoming-webhook` | post to a chosen channel (asks for a channel at install) |

**User Token Scope:** `identity.basic`.

Enable **Socket Mode** and register the slash commands (`/gaia`, `/auth`,
`/help`, `/settings`, `/status`, `/todo`, `/workflow`, `/conversations`, `/new`,
`/stop`, `/unlink`) under Slash Commands. After changing scopes, **reinstall the
app** to the workspace.

---

## Telegram

**Bot:** create via [@BotFather](https://t.me/BotFather).

| Requirement | Where | Notes |
|---|---|---|
| Bot token | BotFather → `TELEGRAM_BOT_TOKEN` | |
| Group privacy **disabled** | BotFather → `/setprivacy` → Disable | Needed for the bot to see @mentions in group chats. |

Commands menu is set via `pnpm --filter @gaia/bot-telegram set-commands`.

---

## WhatsApp (via Kapso)

**Provider:** [Kapso](https://app.kapso.ai) (WhatsApp Cloud API proxy).

| Requirement | Where | Notes |
|---|---|---|
| API key | Kapso → project API key → `KAPSO_API_KEY` | |
| Phone number ID | Kapso → Phone numbers → `KAPSO_PHONE_NUMBER_ID` | sandbox or production number |
| Webhook secret | Kapso → phone-number webhook → `KAPSO_WEBHOOK_SECRET` | Kapso signs each webhook body with HMAC-SHA256; the bot verifies it |

Kapso POSTs inbound messages to the bot's **`/webhook`** route (default port
`3203`). Point the Kapso phone-number webhook at a publicly reachable URL
(production host, or an ngrok/cloudflared tunnel in dev) ending in `/webhook`.
`platform_user_id` is the `wa_id` (phone number, no leading `+`).

---

## Outbound delivery (all platforms)

Backend-originated messages (reminders, workflow results, the "you're connected"
confirmation) are published to per-platform RabbitMQ queues `outbound.<platform>`
and consumed by the running bot. Set `RABBITMQ_URL` to the same broker + vhost
the API uses. The Python (`apps/api/app/constants/outbound.py`) and TypeScript
(`libs/shared/ts/src/bots/consumer/topology.ts`) queue sets are kept in sync by a
pre-commit parity guard.
