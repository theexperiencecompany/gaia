# CLAUDE.md

GAIA is a proactive personal AI assistant — full-stack Nx monorepo with a Next.js frontend, FastAPI/LangGraph backend, React Native mobile app, Electron desktop app, and Discord/Slack/Telegram bots.

## mise

`mise` is the task runner and tool version manager for this repo. It manages Node, Python, uv, and nx versions, and defines all development tasks.

```bash
mise tasks          # List all available tasks with descriptions
mise run <task>     # Run a task (e.g. mise run lint, mise run dev)
mise //apps/api:lint  # Run a task in a sub-project from the root
```

Pre-commit hooks are managed via **prek** (installed by mise). Install once with `mise run pre-commit:install`. Hooks run automatically on `git commit` — to run manually: `mise run pre-commit`.

## Key Commands

```bash
# Install JS dependencies
pnpm install

# Sync Python dependencies
nx run api:sync
nx run voice-agent:sync

# Run apps
nx dev web          # Next.js (Turbopack)
nx dev api          # FastAPI (hot reload, port 8000)
nx worker api       # ARQ background worker
nx dev desktop      # Electron + Next.js
nx dev mobile       # React Native (Expo)
nx dev voice-agent  # LiveKit voice worker

# Docker (from infra/docker/)
docker compose up -d                       # infra only
docker compose --profile backend up -d    # + API
docker compose --profile all up -d        # everything

# Quality (run after changes — see After Major Changes below)
nx run-many -t lint
nx run-many -t type-check
nx run-many -t format

# Build
nx build web
nx build api

# API tests
cd apps/api && uv run pytest
```

## Code Style

### TypeScript/JavaScript

- Package manager is **pnpm** — never use npm or yarn
- **Biome** for linting/formatting — not ESLint/Prettier
- **No inline imports** — all imports at the top of the file
- **Never use `any`** — always provide proper type definitions
- **Before creating a new type, search `src/types/` first** — do not duplicate existing types
- Path alias `@/` maps to `src/` in web/desktop

### Python

- **No inline imports** — all imports at the top of the file
- **Full type annotations required** on all functions and methods (enforced by mypy)
- **Ruff** for linting/formatting — not black/flake8/isort

## DRY Principles

**Never duplicate logic across the monorepo.** Before writing new code, search for existing utilities, types, hooks, or services that already solve the problem.

- **Shared Python logic** belongs in `libs/shared/py/` — import it in `apps/api`, `apps/voice-agent`, and `apps/bots` via the `gaia-shared` package.
- **Shared TypeScript logic** belongs in `libs/shared/ts/` — consumed as `@gaia/shared` workspace package.
- **Shared React/RN components or hooks** that are used across `web`, `desktop`, and `mobile` should live in `libs/shared/ts/src/` or a dedicated lib, not duplicated in each app.
- When extracting shared code, update all call sites — do not leave dead duplicates behind.
- If you find duplicated logic while working, flag it and consolidate it before adding more.

## No Dead Code

**After every refactor or change, clean up before considering work complete.**

- Remove unused imports, variables, functions, types, and files — do not leave them commented out or with `_` prefixes
- When moving logic to shared libs, delete the original copies from all previous locations
- When replacing an implementation, remove the old one entirely — do not keep it "just in case"
- When renaming or restructuring, hunt down all references and update or remove them
- If unsure whether something is still used, **grep for it** — do not assume it's dead or alive

## Working Style

### Subagents & Parallelism

**Always spawn subagents wherever possible** — for research, exploration, or independent tasks, use the Agent tool with specialized subagents in parallel. Don't do sequentially what can be done concurrently.

### Deep Exploration

When investigating a bug, feature, or unfamiliar area of the codebase:

- **Never assume the root cause** — trace the actual code path. Read the relevant files, follow imports, and verify your hypothesis before proposing a fix.
- **Explore deeply** — use the `Explore` subagent for broad codebase discovery. For complex multi-file investigations, spawn multiple subagents to explore different layers in parallel.
- **Explore the intricacies** — check edge cases, related config, middleware, environment variables, and cross-app interactions. Do not stop at the surface.
- **Use relevant skills** — before starting any significant task, check if a skill applies (`writing-plans`, `accurate-testing`, `logging-best-practices`, `copywriting`, etc.) and invoke it via the `Skill` tool.

### Task Tracking

**Always create todos for multi-step work** — use TaskCreate at the start of any non-trivial task. Update status (`in_progress` → `completed`) as you go. Never leave tasks stale.

### Planning

- **Plans must go in `.agents/plans/`** — never create plan files anywhere else. This directory is gitignored.
- **Plans must be comprehensive** — include architecture decisions, step-by-step implementation, edge cases, and rollback considerations before writing any code.
- Use the `writing-plans` skill before starting any significant implementation.

### Testing

**Do NOT create test cases unless explicitly asked.** Do not add tests when fixing bugs or adding features unless the user specifically requests it.

### After Major Changes

Always run type-check and lint for every affected layer before considering work complete:

```bash
# Backend
nx type-check api
nx lint api

# Frontend
nx run-many -t type-check --projects=web,desktop
nx run-many -t lint --projects=web,desktop
```

## Git Conventions

- **Never add Claude as a co-author in commits.** Do not include `Co-Authored-By: Claude` or any similar line in commit messages.

## Common Issues

- Python deps not resolving → `nx run api:sync` or `nx run voice-agent:sync`
- Nx daemon issues → daemon is disabled (`useDaemonProcess: false` in `nx.json`)
- Web app uses `output: "standalone"` — required for Electron bundling, do not remove
- Console logs are stripped in production builds (except `console.error`)
