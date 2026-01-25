# GAIA Bots

Discord, Slack, and Telegram bot integrations.

## Run Locally

```bash
# First time setup: copy env template
cp apps/bots/.env.example apps/bots/.env
# Edit .env with your tokens

# Then run any bot
cd apps/bots/{discord|slack|telegram}
pnpm dev
```

## Environment Variables

**All bots need:**
- `GAIA_API_URL` - GAIA API endpoint
- `GAIA_BOT_API_KEY` - API key

**Platform-specific:**
- Discord: `DISCORD_BOT_TOKEN`, `DISCORD_CLIENT_ID`, `DISCORD_GUILD_ID` (dev only, instant updates)
- Slack: `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN`
- Telegram: `TELEGRAM_BOT_TOKEN`

Copy `apps/bots/.env.example` to `apps/bots/.env` and fill in your values.

## Docker

All bots share a single Dockerfile. Build with `BOT_NAME`:

```bash
# Discord
docker build --build-arg BOT_NAME=discord -f apps/bots/Dockerfile -t gaia-bot-discord .

# Slack
docker build --build-arg BOT_NAME=slack -f apps/bots/Dockerfile -t gaia-bot-slack .

# Telegram
docker build --build-arg BOT_NAME=telegram -f apps/bots/Dockerfile -t gaia-bot-telegram .
```

## Development Commands

All bots are integrated with mise and nx:

```bash
# Lint all bots
mise lint:bots

# Type-check all bots
mise type-check:bots

# Format all bots
mise format:bots

# Run specific bot with API
mise dev:bot:discord
mise dev:bot:slack
mise dev:bot:telegram

# Run all bots at once
mise dev:bots
```

Individual bot commands:
```bash
nx lint bot-discord
nx type-check bot-slack
nx format bot-telegram
```

## Run in Development

You can run any bot in development mode with hot-reload:

```bash
# Discord
cd apps/bots/discord && pnpm dev

# Slack
cd apps/bots/slack && pnpm dev

# Telegram
cd apps/bots/telegram && pnpm dev
```

Or use mise/nx for all bots:

```bash
mise dev:bots         # Run all bots in parallel
mise dev:bot:discord  # Run Discord bot only
mise dev:bot:slack    # Run Slack bot only
mise dev:bot:telegram # Run Telegram bot only
```
