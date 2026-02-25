# GAIA Telegram Bot

The official Telegram bot for GAIA - your proactive personal AI assistant.

## Features

- 🤖 Chat with GAIA using bot commands
- 📋 Manage todos directly from Telegram
- 🔄 Execute and monitor workflows
- 💬 Access your conversation history



## Setup

### Prerequisites

- Node.js 18+ and pnpm
- Telegram account
- GAIA API running

### 1. Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` command
3. Follow the prompts to choose a name and username
4. Copy the bot token provided by BotFather

### 2. Configure Bot Settings (Optional)

Send these commands to BotFather:

```
/setcommands
```

Then paste this command list:

```
start - Start the bot
gaia - Chat with GAIA
auth - Link your Telegram account
workflow - Manage workflows
todo - Manage todos
conversations - View conversations


help - Show help message
```

### 3. Environment Configuration

Create `.env` file in `apps/bots/telegram/`:

```bash
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GAIA_API_URL=http://localhost:8000
GAIA_BOT_API_KEY=your_secure_bot_api_key
```

### 4. Start the Bot

```bash
# Development mode
nx dev bot-telegram

# Production mode
nx build bot-telegram
nx start bot-telegram
```

## Available Commands

### General

- `/start` - Start the bot and see welcome message
- `/gaia <message>` - Chat with GAIA
- `/auth` - Link your Telegram account to GAIA

### Workflows

- `/workflow list` - List all workflows
- `/workflow get <id>` - Get workflow details
- `/workflow execute <id>` - Execute a workflow

### Todos

- `/todo list` - List your todos
- `/todo add <title>` - Create a new todo
- `/todo complete <id>` - Mark as complete
- `/todo delete <id>` - Delete a todo

### Conversations

- `/conversations` - List your recent GAIA conversations

### Utilities


- `/help` - Show all available commands

## Authentication

1. Send `/auth` to the bot
2. Click the provided link
3. Log in to your GAIA account
4. Your Telegram account is now linked!

## Troubleshooting

### Bot doesn't respond

- Verify the bot token is correct
- Check that the bot is running
- Ensure you've started a conversation with the bot

### Authentication issues

- Ensure GAIA_BOT_API_KEY matches the API configuration
- Verify the API is running and accessible

## Development

```bash
# Install dependencies
pnpm install

# Run in development mode
nx dev bot-telegram

# Build for production
nx build bot-telegram
```

## Support

For issues and feature requests, visit [GAIA Documentation](https://docs.gaia.com).
