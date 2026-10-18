# packages/cli

The `@heygaia/cli` package — a Node.js CLI tool (`gaia`) for self-hosting GAIA. Built with Commander + Ink (React-in-terminal) for interactive UI.

## Commands

| Command | Description |
|---|---|
| `gaia up [--yes] [--llm-provider/--llm-key/--llm-base-url/--llm-model] [--domain] [--code-sandbox] [--no-local-name]` | One-command self-host install/resume; names it http://gaia.local on the LAN via portless (`lib/local-name.ts`) unless a domain is set |
| `gaia update [--yes] [--version <tag>] [--git]` | Move to the release this CLI ships: download + verify its `gaia-selfhost-<version>.tar.gz` bundle, pull the `v<version>` images, swap the setup files in (dropping removed ones), keep `.env` files and volumes, restart. Moves a clean detached release-tag checkout from an older `gaia up` to the bundle layout; refuses a branch or edited checkout (use `--git`) |
| `gaia doctor` | Ordered diagnostics, incl. per-dependency `/health/ready` |
| `gaia uninstall [--yes] [--delete-data]` | Remove the recorded self-host install: containers, networks, images, gaia.local, the install folder and ~/.gaia; volumes only on --delete-data (kept data keeps apps/api/.env and infra/docker/.env) |
| `gaia backup` / `gaia restore` | Dump / restore MongoDB + PostgreSQL, the storage volumes and `apps/api/.env` (INSTANCE_SECRET) |
| `gaia init [--branch <branch>]` | Developer setup wizard (clone, configure) |
| `gaia setup` | Interactive env setup (wizard) |
| `gaia start [-b/--build] [--pull]` | Start services via Docker Compose |
| `gaia dev [profile]` | Start infrastructure services for local development |
| `gaia stop [--force-ports]` | Stop running services |
| `gaia status` | Show service and per-dependency health |
| `gaia logs` | Stream Docker Compose logs |
| `gaia bridge <cmd>` | Connect this machine's local MCP servers to GAIA over an outbound tunnel; while connected, GAIA can also run commands and read/write files on it (`add`, `login`, `ls`, `rm`, `up`, `down`, `logout`) |

## Key Commands

```bash
# Development (watch mode with tsx)
pnpm dev

# Build (esbuild bundle → dist/index.js)
pnpm build

# Type check
pnpm type-check

# Lint / format (Biome)
pnpm lint
pnpm lint:fix
pnpm format

# Run tests
nx test cli                    # runs: pnpm vitest run

# Run built CLI locally
node dist/index.js
```

## Structure

```
src/
  index.ts                  - Entry point; Commander program + command wiring
  commands/
    bridge/                 - `gaia bridge` device tunnel daemon (see its README)
    init/                   - Clone repo flow
    setup/                  - Env file setup wizard
    start/                  - Docker Compose start flow
    dev/                    - Local dev infrastructure flow
    stop/                   - Stop services
    status/                 - Health check display
    stream-logs/            - Log streaming
  lib/
    config.ts               - CLI configuration constants
    docker.ts               - Docker Compose wrappers
    env-parser.ts           - Parse existing .env files
    env-setup.ts            - Env variable setup logic
    env-writer.ts           - Write .env files
    flow-utils.ts           - Shared flow helpers
    git.ts                  - Git operations (clone, branch)
    healthcheck.ts          - Service health polling
    interactive.ts          - Interactive prompts
    prerequisites.ts        - Check Docker/Git availability (self-host needs only Docker; Git only for a --build clone and developer commands)
    selfhost-bundle.ts      - Self-host bundle: download/verify/swap, and moving an old git-checkout install to the bundle layout
    download.ts             - Download a release asset and verify its sha256 (shared with gaia connect)
    pull-size.ts            - Registry layer sizes, for the image-pull total
    progress.ts / eta.ts    - Amount done and time left captions for progress bars
    service-starter.ts      - Start/stop service orchestration
    version.ts              - CLI version constant
  ui/
    app.tsx                 - Root Ink component (renders per-command screen)
    store.ts                - Shared reactive state store (passed to all commands)
    components/             - Reusable Ink UI components
    screens/                - Per-command screen components
```

## Trying unreleased changes

`mise run cli:try` (from the repo root) tries this tree's CLI on a fresh VM without CI or a publish. It builds and packs the CLI, builds the self-host bundle with `scripts/ci/release.sh selfhost-bundle`, serves both plus `install.sh` over HTTP on `CLI_TRY_PORT` (default 8790), and prints the command to paste in the VM:

```bash
curl -fsSL http://host.orb.internal:8790/install.sh | GAIA_CLI_TARBALL=http://host.orb.internal:8790/heygaia-cli-<v>.tgz GAIA_BUNDLE_BASE_URL=http://host.orb.internal:8790 GAIA_VERSION=v0.7.0-beta.3 sh
```

- `GAIA_CLI_TARBALL` (install.sh): an http(s) URL or absolute path ending `.tgz`, installed instead of the npm package; the installer says so out loud.
- `GAIA_BUNDLE_BASE_URL` (CLI): where to read the bundle and its `.sha256` instead of the GitHub Release.
- `GAIA_VERSION` (CLI): which release's images and bundle to install.

The CLI prints a warning line for each of the last two when set. Images come from a published release (default the newest `cli-v*` tag), so nothing is built. Export the two CLI variables in the VM shell too if you run `gaia update` there later.

## Release

`publish-cli.yml`'s `publish-binaries` job runs `release.sh selfhost-bundle` (`VERSION`, `RELEASE_TAG`) before npm publishes, so the `cli-v<version>` release carries the bundle `gaia up` and `gaia update` download. `DRY_RUN=1` builds the bundle and names the upload without making it.

## Architecture

Each command follows the same pattern (except `bridge/`, which is a non-Ink daemon — plain Commander subcommands defined in `bridge/command.ts`):
1. `handler.ts` — creates the store, renders `<App>`, calls `flow.ts`, handles SIGINT/SIGTERM
2. `flow.ts` — imperative business logic that mutates the store (no React)
3. The Ink `<App>` component reads from the store and re-renders reactively

Command descriptions are defined in `libs/shared/ts/src/cli/command-manifest.ts` and imported by both this CLI and other packages that display command info.

## Gotchas

- **pnpm only** — do not use npm or yarn.
- **No inline imports** — all imports at the top of the file.
- **Never use `any`** — always provide explicit TypeScript types. Check existing types in `src/lib/` before creating new ones.
- **Biome** is the linter/formatter — not ESLint/Prettier. Run `pnpm lint:fix` to auto-fix.
- **ESM only** (`"type": "module"`) — use `.js` extensions on relative imports even for `.ts` source files.
- **esbuild bundles to a single file** (`dist/index.js`) with `--packages=external`. External packages must be present in the install environment.
- **Node >= 20 required** at runtime.
- **Do not create tests** unless explicitly asked — the test runner is vitest but tests are not expected for new commands.
- `--force-ports` on `gaia stop` kills processes on API/Web ports and may affect non-GAIA processes — note this in any UI copy.
