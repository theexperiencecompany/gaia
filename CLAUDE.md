# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

GAIA is a proactive personal AI assistant built as a full-stack monorepo using Nx. The system consists of:
- **Frontend**: Next.js web app, Electron desktop app, React Native mobile app
- **Backend**: FastAPI Python API with LangGraph agents
- **Bots**: Discord, Slack, and Telegram integrations
- **Infrastructure**: PostgreSQL, MongoDB, Redis, ChromaDB, RabbitMQ

## Development Commands

### Setup
```bash
# Install dependencies (uses pnpm)
pnpm install

# Sync Python dependencies for API
nx run api:sync

# Sync Python dependencies for voice agent
nx run voice-agent:sync
```

### Running Applications

```bash
# Run web app (Next.js with Turbopack)
nx dev web

# Run desktop app (Electron + Next.js)
nx dev desktop

# Run mobile app (React Native)
nx dev mobile

# Run API backend (FastAPI with hot reload)
nx dev api

# Run ARQ worker for background tasks
nx worker api

# Run voice agent
nx dev voice-agent
```

### Docker Development
```bash
# Start all services
cd infra/docker && docker compose up

# Start specific profiles
docker compose --profile backend up  # Backend + dependencies
docker compose --profile worker up   # Worker + dependencies
docker compose --profile voice up    # Voice agent
```

### Testing & Quality

```bash
# Lint all projects
nx run-many -t lint

# Lint and fix
nx run-many -t lint:fix

# Format code
nx run-many -t format

# Check formatting
nx run-many -t format:check

# Type check
nx run-many -t type-check

# Build all projects
nx run-many -t build

# Build specific project
nx build web
nx build api
```

### Python-Specific Commands

```bash
# API linting (ruff)
nx lint api

# API formatting
nx format api

# API type checking (mypy)
nx type-check api

# Run API tests
cd apps/api && uv run pytest
```

### Project Management

```bash
# Clean build artifacts
nx clean web
nx clean api

# Run multiple targets in parallel (max 3 by default)
nx run-many -t build lint type-check

# View task graph
nx graph
```

## Architecture

### Monorepo Structure

```
apps/
  web/          - Next.js web application
  desktop/      - Electron desktop app
  mobile/       - React Native mobile app
  api/          - FastAPI backend with LangGraph agents
  voice-agent/  - Voice processing worker
  bots/
    discord/    - Discord bot
    slack/      - Slack bot
    telegram/   - Telegram bot
  docs/         - Documentation site

libs/
  shared/       - Shared Python utilities (gaia-shared package)
    py/         - Python shared code
    ts/         - TypeScript shared code
```

### Frontend (Web/Desktop)

**Tech Stack**: Next.js 16, React 19, TypeScript, Zustand, TailwindCSS, Biome

**Key Directories**:
- `src/app/` - Next.js App Router pages (organized by route groups)
- `src/features/` - Feature modules (chat, todo, calendar, workflows, integrations, etc.)
- `src/stores/` - Zustand state management stores
- `src/components/` - Reusable React components
- `src/lib/` - Utility functions and configurations
- `src/types/` - TypeScript type definitions

**State Management**: Uses Zustand for global state. Each feature can have its own store in `src/stores/` or `src/features/{feature}/stores/`.

**Styling**: TailwindCSS with custom configuration. Uses Biome for linting/formatting instead of ESLint/Prettier.

**Desktop App**: The Electron app uses the Next.js standalone build output to bundle the web app for desktop.

### Backend (API)

**Tech Stack**: FastAPI, LangGraph, Python 3.11+, PostgreSQL, MongoDB, Redis, ChromaDB, RabbitMQ

**Key Directories**:
- `app/main.py` - Application entry point
- `app/core/` - Core application logic (app factory, middleware, lifespan)
- `app/api/v1/` - API routes and endpoints
- `app/agents/` - LangGraph agent system
  - `core/` - Core agent logic (agent.py, state.py, graph_manager.py, nodes/, subagents/)
  - `tools/` - Agent tools
  - `prompts/` - Agent prompts
  - `memory/` - Agent memory management
  - `llm/` - LLM integrations
- `app/models/` - Database models
- `app/schemas/` - Pydantic schemas
- `app/services/` - Business logic services
- `app/db/` - Database clients (postgresql, mongodb, redis, chroma, rabbitmq)
- `app/workers/` - Background task workers
- `app/config/` - Configuration and settings
- `app/utils/` - Utility functions

**Database Setup**: The API depends on PostgreSQL, MongoDB, Redis, ChromaDB, and RabbitMQ. Use Docker Compose for local development.

**Background Tasks**: Uses ARQ (Redis-based task queue) for async job processing. Run with `nx worker api`.

**Dependency Management**: Uses `uv` for Python package management. Run `nx run api:sync` to install dependencies.

### Mobile App

**Tech Stack**: React Native, Expo, TypeScript

Similar structure to web app with React Native components. Uses React Navigation for routing.

### Shared Libraries

**Python Shared (`libs/shared/`)**: Common utilities used across Python apps (API, voice-agent, bots). Includes logging, config, and Pydantic models.

**Install**: The `gaia-shared` package is automatically available to Python apps via workspace dependencies.

## Code Style Guidelines

### TypeScript/JavaScript

- Use Biome for linting and formatting (configured in `biome.json`)
- **No inline imports** - all imports must be at the top of the file
- **Never use `any` type** - always provide proper type definitions
- Line width: 80 characters
- Indentation: 2 spaces
- Use strict TypeScript configuration
- No unnecessarily verbose comments - code should be self-documenting

### Python

- Use Ruff for linting and formatting (configured in `ruff.toml` or `pyproject.toml`)
- **No inline imports** - all imports must be at the top of the file
- **Use strict types** - always provide type annotations for function parameters and return values
- Follow PEP 8 style guide
- Use type hints extensively (enforced by mypy)
- No unnecessarily verbose comments - code should be self-documenting

### General

- Follow feature-based organization - group related files by feature, not by type
- Use absolute imports with path aliases (`@/` for web/desktop, configured in tsconfig)
- Keep components small and focused on a single responsibility

## Key Technologies

### Frontend
- **Next.js 16**: App Router with React Server Components
- **React 19**: Latest React features
- **Zustand**: Lightweight state management
- **TailwindCSS**: Utility-first CSS
- **Biome**: Fast linter and formatter (replaces ESLint + Prettier)
- **TypeScript**: Strict type checking
- **Electron**: Desktop app wrapper (electron-vite for build)

### Backend
- **FastAPI**: Modern Python web framework
- **LangGraph**: Agent orchestration framework
- **PostgreSQL**: Primary relational database
- **MongoDB**: Document storage for flexible data
- **Redis**: Caching and task queue (ARQ)
- **ChromaDB**: Vector database for embeddings
- **RabbitMQ**: Message broker
- **Pydantic**: Data validation and settings
- **uv**: Fast Python package installer

## Testing

For Python tests, run pytest directly in the project directory:
```bash
cd apps/api
uv run pytest
```

## Environment Variables

Each app has its own `.env` file:
- `apps/api/.env` - Backend configuration
- `apps/web/.env.local` - Web app configuration

Refer to `.env.example` files in each directory for required variables.

## Docker

Dockerfiles are located in each app directory. Docker Compose configuration is in `infra/docker/`:
- `docker-compose.yml` - Development environment
- `docker-compose.prod.yml` - Production environment

## Release Management

The project uses Nx release with Docker support. Release groups are configured in `nx.json`:
- **apps group**: `api`, `voice-agent` (published to ghcr.io)

Build Docker images:
```bash
nx docker:build api
nx docker:build voice-agent
```

## Implementation Plans

When creating implementation plans, store them in `.agents/plans/` directory. This folder is gitignored and used for planning documents before execution.

## Common Issues

- If Python dependencies are not resolving, run `nx run api:sync` or `nx run voice-agent:sync`
- If you see Nx daemon issues, the daemon is disabled (`useDaemonProcess: false` in `nx.json`)
- The web app uses standalone output mode for Electron bundling
- Console logs are removed in production builds except for errors
