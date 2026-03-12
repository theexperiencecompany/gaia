# packages/cli

The `@heygaia/cli` package — a Node.js CLI tool (`gaia`) for self-hosting GAIA. Built with Commander + Ink (React-in-terminal) for interactive UI.

## Commands

| Command | Description |
|---|---|
| `gaia init [--branch <branch>]` | Clone the GAIA repo |
| `gaia setup` | Interactive env setup (wizard) |
| `gaia start [-b/--build] [--pull]` | Start services via Docker Compose |
| `gaia dev [profile]` | Start infrastructure services for local development |
| `gaia stop [--force-ports]` | Stop running services |
| `gaia status` | Show service health status |
| `gaia logs` | Stream Docker Compose logs |

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
    path-setup.ts           - Project path resolution
    prerequisites.ts        - Check Docker/Git availability
    service-starter.ts      - Start/stop service orchestration
    version.ts              - CLI version constant
  ui/
    app.tsx                 - Root Ink component (renders per-command screen)
    store.ts                - Shared reactive state store (passed to all commands)
    components/             - Reusable Ink UI components
    screens/                - Per-command screen components
```

## Architecture

Each command follows the same pattern:
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
