# packages/cli

The `@heygaia/cli` package — a Node.js CLI tool (`gaia`) for self-hosting GAIA. Built with Commander + Ink (React-in-terminal) for interactive UI.

## Commands

| Command | Description |
|---|---|
| `gaia up [--yes] [--llm-provider/--llm-key/--llm-base-url/--llm-model] [--domain \| --no-domain] [--code-sandbox] [--no-local-name]` | One-command self-host install/resume; names it http://gaia.local on the LAN via portless (`lib/local-name.ts`; gaia-2.local and on when another GAIA on the network holds it, recorded in ~/.gaia/config.json) unless a domain is set. A rerun keeps the recorded domain; `--no-domain` drops it and puts the proxy back on its default ports (`pinnedPorts`, merged into infra/docker/.env by `writeDockerComposeEnv`) |
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
install.sh / install.ps1    - curl | sh installer (Node, the CLI, a PATH launcher); hands its screen to `gaia up` via GAIA_CONTINUES_INSTALLER
src/
  index.ts                  - Entry point; Commander program + command wiring
  commands/<cmd>/           - handler.ts (configures command-runner) + flow.ts (logic) + screen.tsx when it has one:
                              up, update, start, stop, status, doctor, logs (stream-logs), backup, restore,
                              uninstall, bots, init, setup, dev, connect, bridge (non-Ink daemon, see its README)
  commands/up/preflight.ts  - Memory/disk verdicts and a --domain's DNS warning before anything downloads
  lib/
    command-runner.ts       - runCommandUI: creates the store, renders <App>, handles signals, plain output when piped
    run-steps.ts            - Step rows every RunScreen command shows; non-tty.ts prints them as plain text
    start-steps.ts          - The download/start/answer rows every (re)start shows
    command-ending.ts       - A run's last lines: one next action, alternates dimmed
    config.ts               - ~/.gaia/config.json read/write (install path, bots, codeSandbox, localName)
    answers.ts / llm-flags.ts - `gaia up` flags and an earlier run's choices merged into one plan
    prerequisites.ts        - Docker/Git checks and port probes (ss / lsof for ports below 1024)
    prerequisite-install.ts - Installing Docker (get.docker.com on apt Linux) and the Compose version gate
    docker-access.ts / docker-group.ts - Daemon reachability, docker-group relaunch
    port-conflicts.ts       - Move / ask / fail a taken port; ports pinned by --domain or --web-port never move
    host-resources.ts       - Memory and disk thresholds shared by `gaia up` and `gaia doctor`
    domain-reachability.ts  - A --domain's DNS against this machine, and waiting for its HTTPS certificate
    local-name.ts / local-name-ipv6.ts - http://gaia.local via portless (gaia-2 … gaia-9.local when taken), avahi AAAA
    compose-run.ts / compose-progress.ts / compose-failure.ts - Running compose, its progress, its errors in plain words
    pull-size.ts / progress.ts / eta.ts - Image download totals, amount-done and time-left captions
    readiness.ts / healthcheck.ts - Waiting for GAIA to answer, per-dependency health
    selfhost-bundle.ts      - Self-host bundle: download/verify/swap, and moving an old git-checkout install to the bundle layout
    download.ts             - Download a release asset and verify its sha256 (shared with gaia connect)
    service-starter.ts      - Start/stop orchestration and install-root discovery
    env-parser.ts / env-setup.ts / env-writer.ts - Read, prompt for and write .env files
    machine-secrets.ts      - Secrets generated once per install
    version.ts              - CLI version and the image tag it pins
  ui/
    app.tsx / store.ts      - Root Ink component and the reactive store every flow mutates
    header/                 - The logo baked from apps/web/public/brand/gaia_logo.svg (scripts/bake-logo.mjs)
    components/             - Shared Ink components (RunScreen: the shared step-list screen, ResultCard, StepList)
    screens/                - init, setup and status (older commands not yet on RunScreen)
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
1. `handler.ts` — configures `runCommandUI` (`lib/command-runner.ts`), which creates the store, renders `<App>`, calls `flow.ts` and handles SIGINT/SIGTERM
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
- **Tests live in `__tests__/`** (vitest, `nx test cli`); installer tests are `scripts/ci/tests/test_cli_install.py`.
- **gaia.local needs Node 24+** (portless), although the CLI itself runs on Node 20.
- `--force-ports` on `gaia stop` kills processes on API/Web ports and may affect non-GAIA processes — note this in any UI copy.
