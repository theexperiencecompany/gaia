# GAIA Slack Bot

The official Slack bot for GAIA - your proactive personal AI assistant.

## Features

- 🤖 Chat with GAIA using slash commands
- 📋 Manage todos directly from Slack
- 🔄 Execute and monitor workflows
- 💬 Access your conversation history



## Setup

### Prerequisites

- Node.js 18+ and pnpm
- Slack workspace with admin access
- GAIA API running

### 1. Create a Slack App

1. Go to [Slack API](https://api.slack.com/apps)
2. Click "Create New App" → "From scratch"
3. Give your app a name and select your workspace

### 2. Configure Bot Settings

#### Enable Socket Mode

1. Go to "Socket Mode" in the sidebar
2. Toggle "Enable Socket Mode"
3. Generate an app-level token with `connections:write` scope
4. Copy the token (starts with `xapp-`)

#### Add Bot User

1. Go to "OAuth & Permissions"
2. Add these Bot Token Scopes:
   - `chat:write`
   - `commands`
   - `im:history`
   - `im:read`
   - `im:write`
3. Install the app to your workspace
4. Copy the "Bot User OAuth Token" (starts with `xoxb-`)

#### Configure Slash Commands

Go to "Slash Commands" and create these commands:

- `/gaia` - Chat with GAIA (Request URL can be blank in Socket Mode)
- `/auth` - Link your Slack account
- `/workflow` - Manage workflows
- `/todo` - Manage todos
- `/conversations` - View conversations



### 3. Environment Configuration

Create `.env` file in `apps/bots/slack/`:

```bash
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
SLACK_SIGNING_SECRET=your-signing-secret
GAIA_API_URL=http://localhost:8000
GAIA_BOT_API_KEY=your_secure_bot_api_key
```

### 4. Start the Bot

```bash
# Development mode
nx dev bot-slack

# Production mode
nx build bot-slack
nx start bot-slack
```

## Available Commands

### General

- `/gaia <message>` - Chat with GAIA
- `/auth` - Link your Slack account to GAIA

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



## Authentication

1. Use `/auth` command in any Slack channel
2. Click the provided link
3. Log in to your GAIA account
4. Your Slack account is now linked!

## Troubleshooting

### Bot doesn't respond

- Verify Socket Mode is enabled
- Check that all tokens are correct
- Ensure the bot is running

### Command not found errors

- Verify slash commands are configured in Slack App settings
- Re-install the app to your workspace

## Development

```bash
# Install dependencies
pnpm install

# Run in development mode
nx dev bot-slack

# Build for production
nx build bot-slack
```

## Support

For issues and feature requests, visit [GAIA Documentation](https://docs.gaia.com).
