# GAIA Discord Bot

The official Discord bot for GAIA - your proactive personal AI assistant.

## Add to Your Server

**[➕ Add GAIA to Discord](https://discord.com/oauth2/authorize?client_id=1388905575399559370)**

Or visit: https://heygaia.io/discord-bot

## Features

- 🤖 Chat with GAIA using slash commands or mentions
- 📋 Manage todos directly from Discord
- 🔄 Execute and monitor workflows
- 💬 Access your conversation history



## Setup

### Prerequisites

- Node.js 18+ and pnpm
- Discord Developer Account
- GAIA API running

### 1. Create a Discord Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Navigate to "Bot" section and click "Add Bot"
4. Enable these Privileged Gateway Intents:
   - Message Content Intent
   - Server Members Intent (optional)
5. Copy the bot token

### 2. Configure OAuth2 Scopes

1. Go to "OAuth2" → "URL Generator"
2. Select scopes:
   - `bot`
   - `applications.commands`
3. Select bot permissions:
   - Send Messages
   - Use Slash Commands
   - Read Message History
4. Copy the generated URL and invite the bot to your server

### 3. Environment Configuration

Create `.env` file in `apps/bots/discord/`:

```bash
DISCORD_BOT_TOKEN=your_discord_bot_token
DISCORD_CLIENT_ID=your_discord_client_id
GAIA_API_URL=http://localhost:8000
GAIA_BOT_API_KEY=your_secure_bot_api_key
```

### 4. Deploy Slash Commands

```bash
# From monorepo root
nx run bot-discord:deploy-commands
```

### 5. Start the Bot

```bash
# Development mode
nx dev bot-discord

# Production mode
nx build bot-discord
nx start bot-discord
```

## Available Commands

### General

- `/gaia <message>` - Chat with GAIA
- `/auth` - Link your Discord account to GAIA

### Workflows

- `/workflow list` - List all your workflows
- `/workflow get <id>` - Get workflow details
- `/workflow execute <id>` - Execute a workflow
- `/workflow create <name> <description>` - Create a new workflow

### Todos

- `/todo list` - List your active todos
- `/todo add <title> [priority] [description]` - Create a new todo
- `/todo complete <id>` - Mark a todo as complete
- `/todo delete <id>` - Delete a todo

### Conversations

- `/conversations list [page]` - List your recent GAIA conversations

### Utilities



### Mentions

You can also mention the bot in any channel to chat with GAIA:

```
@GAIA How do I get started?
```

## Authentication

Before using most commands, you need to link your Discord account:

1. Use `/auth` command
2. Click the provided link
3. Log in to your GAIA account
4. Your Discord account is now linked!

## Troubleshooting

### Bot doesn't respond to commands

- Ensure slash commands are deployed (`nx run bot-discord:deploy-commands`)
- Check bot permissions in your server
- Verify the bot is online

### Authentication issues

- Ensure `GAIA_BOT_API_KEY` matches the key configured in the GAIA API
- Check that the API is running and accessible

### Message length errors

- Responses are automatically truncated to Discord's 2000 character limit
- Long lists may be paginated

## Development

```bash
# Install dependencies
pnpm install

# Run in development mode with hot reload
nx dev bot-discord

# Build for production
nx build bot-discord

# Deploy commands to Discord
nx run bot-discord:deploy-commands
```

## Support

For issues and feature requests, visit [GAIA Documentation](https://docs.gaia.com) or contact support.
