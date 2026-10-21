# packages/cli

The `@heygaia/cli` package — a Node.js CLI tool (`gaia`) for self-hosting GAIA. Built with Commander + Ink (React-in-terminal) for interactive UI.

## Commands

| Command | Description |
|---|---|
| `gaia up [--yes] [--llm-provider/--llm-key/--llm-base-url/--llm-model] [--domain] [--code-sandbox] [--no-local-name]` | One-command self-host install/resume; names it http://gaia.local on the LAN via portless (`lib/local-name.ts`; gaia-2.local and on when another GAIA on the network holds it, recorded in ~/.gaia/config.json) unless a domain is set |
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
| `gaia bots add\|list\|remove <platform>` | Run the Telegram, Discord or Slack bot with your own token |
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
    start-steps.ts          - The download/start/answer rows every (re)start shows
    command-ending.ts       - A run's last lines: one next action, alternates dimmed
    version.ts              - CLI version constant
  ui/
    app.tsx                 - Root Ink component (renders per-command screen)
    store.ts                - Shared reactive state store (passed to all commands)
    components/             - Reusable Ink UI components (RunScreen: the shared step-list screen)
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

## CLI interface guidelines

Every command a self-hoster runs (`up`, `status`, `stop`, `start`, `update`, `doctor`, `logs`, `backup`, `restore`, `uninstall`, `bots`, `--help`, `--version`) holds `gaia up`'s bar. Rules, each with its reason:

- **One screen.** One header: the baked logo (`ui/header/`), or its one line when the terminal is too small or output is piped. One column, two in. One row grammar: mark (spinner, ✓, ✗) + label + time right-aligned (`ui/components/StepList.tsx`, mirrored by install.sh). One blank line between header, rows and ending. — A command that looks different reads as a different tool.
- **Never still for more than ~1s.** A wait longer than that is a step with a spinner and a clock; a long one has real sub-steps or real progress (done / total and time left, never a bare percentage). — A frozen line reads as a hang.
- **Labels say what is happening, in plain words.** No two steps that sound alike, no step that does nothing visible ("Ready 0s"); quick housekeeping is `minor` and folds away. — Every row should tell the user something new.
- **Answered prompts vanish.** A "no" leaves one line saying what was skipped and the command that does it later. — The scrollback is the record of what happened, not of what was asked.
- **The ending is minimal.** One next action, the one link that matters, alternates dimmed. No warning the tool could act on itself: fix it (re-run through the docker group, put `gaia` on PATH) instead of telling the user to. — The last lines are what gets read.
- **Errors are cause, then fix.** Plain words, no "Error:" prefix, no raw tool output; a log path only on failure (`printError`, `ErrorStep`). — The user needs the next move, not a stack trace.
- **One colour rule.** `lib/colour-level.ts` and install.sh detect alike: truecolor over SSH for `*-256color`, nothing under `NO_COLOR`, plain text when not a TTY. — The installer and the CLI are one screen.
- **Honest re-runs and exits.** A second run says what is already true ("GAIA is already running"); Ctrl-C prints "Cancelled" and exits 130; q / Esc leave interactive screens; never "press Enter to exit". — Re-running is how people check.
- **Library first.** `@inkjs/ui` components and Ink `<Static>` before hand-rolled ones, checked against Ink 6 / React 19. — Hand-rolled widgets drift from the rest of the screen.
- **Verify on a real machine.** `mise run cli:try` on a fresh VM over SSH, with timed snapshots of each command; unit tests alone do not show a frame. — Most screen bugs only show in a real terminal.

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
