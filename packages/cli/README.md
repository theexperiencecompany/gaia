# @heygaia/cli

![GAIA CLI](../../apps/web/public/images/screenshots/cli.png)

CLI tool for setting up and managing [GAIA](https://heygaia.io).

## Requirements

- **Node.js 20+** and one package manager (npm, pnpm, or bun)
- **macOS or Linux** (Windows via WSL2)
- **Docker** — `gaia up` offers to install it on apt-based Linux when missing
- **Git** installed

The CLI checks prerequisites at startup and reports what is missing.

## Installation

The standalone installer sets up Node.js if needed and installs the CLI:

```bash
curl -fsSL https://heygaia.io/install.sh | sh
gaia up
```

Or install globally with your preferred package manager:

```bash
npm install -g @heygaia/cli
pnpm add -g @heygaia/cli
bun add -g @heygaia/cli
```

## Commands

```bash
gaia up            # One-command self-host: configure, pull and start
gaia init          # Full setup from scratch
gaia setup         # Configure existing repo
gaia start         # Start services in self-host mode
gaia dev           # Developer mode (Nx TUI)
gaia dev full      # Developer mode + workers (Nx TUI)
gaia logs          # Stream running logs
gaia stop          # Stop all services
gaia status        # Check service health
gaia doctor        # Diagnose a GAIA install
gaia update        # Pull the latest GAIA and restart
gaia --version     # Show CLI version
gaia --help        # Show all commands
```

### `gaia up`

One-command self-hosted setup: checks prerequisites (installing Docker on apt-based Linux with consent), clones GAIA to `~/gaia` if needed, writes the configuration, pulls the published images and starts the stack. GAIA is served on a single port (default 3000) through a bundled Caddy proxy.

| Flag | Description |
|------|-------------|
| `--yes` | No prompts; also consents to installing Docker |
| `--domain <domain>` | Serve at `https://<domain>` with an automatic certificate (ports 80 and 443) |
| `--web-port <port>` | Host port GAIA is served on (default 3000) |
| `--llm-key <key>` / `--llm-provider <name>` | LLM key for first boot (`openrouter`, `gemini`, or `custom`) |
| `--build` | Build images from the checkout instead of pulling |
| `--no-start` | Configure only |

### `gaia update`

Fetches `origin/master`, shows what changed, then `git pull --ff-only` and restarts on freshly pulled images (rebuilding only when the web `Dockerfile` or `package.json` changed). Volumes and `infra/docker/.env` are preserved. `--yes` skips the confirmation.

### `gaia init`

Interactive first-time setup.

| Flag | Description |
|------|-------------|
| `--branch <name>` | Clone a specific branch |

### `gaia setup`

Reconfigure an existing GAIA repo:

```bash
cd /path/to/gaia
gaia setup
```

### `gaia start`

Starts services for **self-host mode**.

```bash
gaia start
```

Optional flags:

- `--build` rebuild Docker images before starting
- `--pull` pull latest base images before starting

### `gaia dev` / `gaia dev full`

Runs developer mode in foreground Nx TUI:

- `gaia dev` -> `mise dev`
- `gaia dev full` -> `mise dev:full`

### `gaia logs`

Streams logs for currently running services.

### `gaia stop`

Stops running GAIA services.

### `gaia status`

Shows health and latency for core services.

## Setup Modes

- **Self-Host (Docker)** — everything in Docker
- **Developer (Local)** — infra in Docker, app in local Nx TUI

## Port Overrides

When port conflicts are detected, overrides are written to `infra/docker/.env`. In self-host mode only the proxy port (`WEB_HOST_PORT`, plus `HTTPS_HOST_PORT` with a domain) is published.

## Development

```bash
# Build
cd packages/cli && pnpm run build

# Test the built CLI
./packages/cli/dist/index.js --help

# Run the test script
./packages/cli/test-cli.sh
```

## Publishing

1. Update version in `package.json`
2. Build: `pnpm run build`
3. Commit and tag: `git tag cli-v<version>`
4. Push tag — GitHub Actions publishes to npm

## License

MIT
