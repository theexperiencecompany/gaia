# @heygaia/cli

CLI tool for setting up and managing GAIA - your proactive personal AI assistant.

## Installation

```bash
# Quick install (recommended)
curl -fsSL https://heygaia.io/install.sh | sh

# Or via package managers
bun install -g @heygaia/cli
npm install -g @heygaia/cli

# Or run without installing
npx @heygaia/cli init
```

## Commands

| Command | Description |
|---------|-------------|
| `gaia init` | Full setup from scratch - clones repo, installs tools, configures env, starts services |
| `gaia setup` | Configure an existing GAIA repository (env vars, dependencies) |
| `gaia start` | Start all GAIA services (auto-detects selfhost vs developer mode) |
| `gaia stop` | Stop all running GAIA services |
| `gaia status` | Check health of all services with latency |

### `gaia init`

Interactive wizard for first-time setup:

1. Prerequisites check (Git, Docker, Mise)
2. Repository cloning
3. Tool installation (Node.js, Python, uv, Nx)
4. Environment variable configuration
5. Project setup (`mise setup`)
6. Service startup (optional)

### `gaia setup`

For existing repos that need configuration or reconfiguration. Run from within a cloned GAIA directory:

```bash
cd /path/to/gaia && gaia setup
```

### `gaia start` / `gaia stop`

Start or stop services. Automatically detects selfhost vs developer mode from your `.env` configuration.

### `gaia status`

Shows health and latency for: API (8000), Web (3000), PostgreSQL (5432), Redis (6379), MongoDB (27017), RabbitMQ (5672), ChromaDB (8080).

## Setup Modes

- **Self-Host (Docker)**: Everything runs in Docker. Best for deployment.
- **Developer (Local)**: Databases in Docker, API + web run locally. Best for contributing.

## Environment Variable Auto-Discovery

The CLI discovers env vars from the codebase at runtime:

- **API**: Extracted from `apps/api/app/config/settings.py` and `settings_validator.py` via Python AST
- **Web**: Parsed from `apps/web/.env`

No CLI updates needed when new variables are added.

## Development

```bash
# Dev mode (no build, uses current workspace)
GAIA_CLI_DEV=true bun packages/cli/src/index.ts <command>

# Build
cd packages/cli && bun run build

# Test built CLI
./packages/cli/dist/index.js --help
```

### Install Script

Source of truth: `packages/cli/install.sh`. After modifying, sync to the web app:

```bash
./packages/cli/sync-install.sh
```

This keeps `https://heygaia.io/install.sh` up to date.

### Publishing

1. Update version in `package.json`
2. Build: `bun run build`
3. Sync install script: `./sync-install.sh`
4. Commit and tag: `git tag cli-v<version>`
5. Push tag — GitHub Actions publishes to npm

### Troubleshooting

| Issue | Fix |
|-------|-----|
| `command not found: gaia` | Ensure `~/.bun/bin` or `~/.npm-global/bin` is in PATH |
| Raw mode not supported | CLI requires interactive terminal — don't run in background |
| Port conflicts not detected | Ensure `lsof` is available (macOS/Linux) |
| Env vars not discovered | Check `settings_validator.py` and `apps/web/.env` exist |

## License

MIT
