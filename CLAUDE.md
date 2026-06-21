# CLAUDE.md

GAIA is a proactive personal AI assistant — full-stack Nx monorepo with a Next.js frontend, FastAPI/LangGraph backend, React Native mobile app, Electron desktop app, and Discord/Slack/Telegram bots.

## Engineering Discipline

- Use best practices and write clean, idiomatic code every time. No shortcuts, no half-measures.
- **Never ship workarounds, patches, or band-aid fixes. Always choose the cleanest, most correct approach — every single time.** When you find a bug, fix it at the root, not at the symptom. If two code paths diverge and one is broken, unify them rather than patching the broken one in place. Surgical-but-duplicative is not "safer" — it is how the bug got there. Surface the tradeoff, then take the clean path.
- Do not override or work around the architecture. Never disable lint rules, add blanket `# noqa` / `// biome-ignore` / `# type: ignore`, or bypass CI to force something through. Linting, type-checking, and CI are guardrails that exist for a reason. Fix the cause, not the symptom.
- Match the conventions of the surrounding code. Prefer the existing pattern over inventing a new one.
- **Fail loud — never swallow errors or add silent fallbacks.** No `try: ... except: return None`, no broad `except` that hides the failure, no default value slipped in to make a symptom disappear. A masked error is a bug that resurfaces somewhere worse, later. Let errors propagate to where they can be handled meaningfully; only catch what you can genuinely recover from.
- **No fake, stub, or placeholder implementations.** Don't write code that *looks* done but isn't — hardcoded "sample" responses, mock data left in a real path, `# TODO: implement` stubs that return a fake success, functions that pretend to work. If something genuinely can't be finished now, say so explicitly instead of shipping a hollow shell.

### Verify, Never Assume

This applies to **everything** — coding, debugging, answering questions, deciding what to do next. Not just while writing code. Any claim you make or act on must be grounded in evidence, not assumption.

- **Never make things up.** Do not invent file paths, function names, API signatures, config keys, env vars, library behavior, return shapes, or facts about how the system behaves. If you have not seen it in this codebase or confirmed it from docs, you do not know it — go find it.
- **Reading code is not validation.** This code is intricate — control flow, async timing, middleware, config, env, and cross-app interactions mean the static text rarely tells the whole story. Reading tells you what the code *looks like* it does; only **running it** tells you what it *actually* does. To truly confirm behavior, execute it: run the function/endpoint, write a throwaway script, add a log and trigger the path, check the real DB/response. Treat "I read it and it should work" as a hypothesis, not a conclusion.
- **Don't generalize from a small sample.** Seeing one usage does not tell you the pattern; seeing one caller does not tell you all callers. Before changing shared code, find *every* call site, *every* implementation of an interface, and the *actual* runtime path — don't assume the first example is representative.
- **When debugging, prove the root cause before fixing.** Don't assume what's broken from a symptom or a guess — reproduce it, instrument it, observe the actual failure. A fix built on an unverified theory usually just moves the bug.
- **State confidence honestly.** If something is unverified, say so and verify it before relying on it. Never present an assumption as a fact. A confident wrong answer is worse than "let me check."
- **Understand before you change or delete.** Don't modify, refactor, or remove code whose purpose you haven't confirmed (Chesterton's fence) — the weird-looking line is often load-bearing. If you don't know why it's there, find out before touching it.
- **Don't claim done without proof.** Never say "it works," "tests pass," or "this is fixed" unless you actually ran it and saw the result. Report outcomes faithfully — if a step was skipped or something failed, say so with the output. "Done" means verified, not "should be done."
- If after genuine investigation something is still ambiguous, stop and ask — do not paper over the gap with a guess.

### Maintainability & Tech Debt

Optimize for the next engineer who has to read, extend, or debug this code six months from now — not for getting it working today. Code is read far more often than it is written. The "best approach" is the one that is easiest to understand, change, and delete later, not the one that is fastest to type now.

- **Debt is not a shipping option.** We do not knowingly add debt to get something out the door — shortcuts taken to ship are exactly the ones that never get paid back. Every change should leave the area as clean as or cleaner than you found it. Do the correct thing now; there is no "fix it later."
- **Never use workarounds.** A workaround is debt that pays off horribly in the future — it hides the real problem, drifts out of sync, and turns one bug into three. Fix the root cause, not the symptom. If the clean fix is bigger than expected, surface that and do it properly rather than band-aiding around it.
- **Never write the same code twice — and "same" means similar, not identical.** This is about intent, not matching lines. Copy-pasted logic drifts (one copy gets fixed, the other rots into a bug), but the deeper rule is that there should be **one canonical way to do a thing** in this codebase. Two functions that solve the same problem differently, three slightly different date formatters, parallel helpers that overlap — that is duplication even when no two lines match, and it forces every reader to learn which variant to trust. Before writing a utility/type/hook/service, search for one that already does it (see `.claude/rules/general.md` DRY); if you find a near-equivalent, use or extend it instead of adding a rival. If you spot two ways to do one thing while working, converge them on the best one. Surgical-but-duplicative is how the bug got there.
- **Abstractions are also debt.** A premature or wrong abstraction is more expensive than duplication, because everyone is forced to route through it. Don't abstract single-use code or speculative "flexibility." Abstract only when the third real case appears and the shape is clear.
- **Don't create functions you don't need — and don't inline logic that needs a name.** This cuts both ways. A one-liner wrapped in its own function, called once, just adds indirection and complexity for no benefit — inline it. But when a block is complex, repeated, or doing something whose intent isn't obvious from the code, pull it into a well-named function — the name *is* the documentation and the seam for testing. The test is value, not line count: extract when it removes complexity or duplication, not as a reflex.
- **Name the future cost of the approach you pick.** When choosing between approaches, weigh: How hard is this to scan and understand cold? How many places change when requirements shift? How coupled is it to things that will move? How hard is it to test and to delete? Prefer the option that is boring, local, and obvious over the one that is clever, sprawling, or magical.
- **Smaller blast radius, clearer boundaries.** Keep modules single-responsibility, keep functions small enough to hold in your head, keep coupling low. A file that does two things is two files. High cohesion + low coupling is what keeps the codebase changeable as it grows.
- **Tech debt compounds silently.** Each shortcut makes the next change a little harder, until a feature that should take a day takes a week. Treat "it works but it's ugly/duplicated/hacky" as unfinished, not done. Working and maintainable are different bars — we hold the second one.
- **Keep diffs minimal and reviewable.** No drive-by reformatting, no reordering imports the formatter didn't ask for, no unrelated "while I'm here" changes. Every line in the diff should trace to the task — noise hides the real change from reviewers and pollutes the history.
- **When you spot debt adjacent to your change, surface it.** Fix it if it's in scope and cheap; otherwise call it out explicitly so it's a decision, not an accident.

### Agent Guidelines (Karpathy-inspired)

Behavioral guidelines to reduce common LLM coding mistakes. Bias toward caution over speed; for trivial tasks, use judgment. Source: https://github.com/multica-ai/andrej-karpathy-skills

**1. Think Before Coding.** Don't assume. Don't hide confusion. Surface tradeoffs.
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them, don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

**2. Simplicity First.** Minimum code that solves the problem, nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it. Ask: "Would a senior engineer say this is overcomplicated?"

**3. Surgical Changes.** Touch only what you must. Clean up only your own mess.
- Don't "improve" adjacent code, comments, or formatting. Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- Remove imports/variables/functions that YOUR changes made unused. Delete pre-existing dead code when you spot it.
- The test: every changed line should trace directly to the user's request.

**4. Goal-Driven Execution.** Define success criteria. Loop until verified.
- Turn vague tasks into verifiable goals before starting.
- For multi-step tasks, state a brief plan with a verify check per step.
- Strong success criteria let you loop independently; weak criteria ("make it work") require constant clarification.
- GAIA caveat: do not write tests as the verification unless explicitly asked (see Testing). Use `nx lint` / `nx type-check` or a manual run as the verify step instead.

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

## Design System

The full design system is documented in **[`DESIGN.md`](./DESIGN.md)** at the repo root. It covers:
- Color tokens, zinc scale, semantic status colors, dark/light CSS variables
- Typography (Inter, PP Editorial New, Anonymous Pro) and heading scale
- Spacing, border radius decision table, shadows
- Icon library usage (`@icons` — never raw SVGs)
- Animation tokens, Framer Motion conventions, easing functions
- Toast/notification system (Sileo — never sonner or react-hot-toast)
- Chat bubble architecture and the TextBubble/TOOL_RENDERERS system
- **Chat tool card styling contract** (outer `rounded-2xl bg-zinc-800 p-4`, inner `rounded-2xl bg-zinc-900 p-3`, no borders)
- Adding new tool cards vs OpenUI primitives (decision tree)
- Copy-paste card template and pre-commit checklist

**Design rules** are in `apps/web/CLAUDE.md` (behavioral, loads when working in web) and `DESIGN.md` (tokens + full system).
**Chat bubble & tool-card design rules** are in `apps/web/src/features/chat/components/bubbles/bot/CLAUDE.md`.
**OpenUI system guide** (generic LLM-emitted components) is in `apps/web/src/config/openui/CLAUDE.md`.
**Visual style guide** (rendered as interactive docs) is in `docs/design-system.mdx` — sourced from `DESIGN.md`.

### Component Library — Never Build From Scratch

**Never create custom button, input, spinner, tooltip, modal, or other UI primitive components from scratch.** Always use HeroUI first:

- `<Button>` — never `<button>`. Use `color`, `variant`, `radius`, `size`, `endContent`, `startContent`, `isLoading`, `isIconOnly` props.
- `<Input>` / `<Textarea>` — never raw `<input>` / `<textarea>`
- `<Spinner>` / `<Skeleton>` — never custom loaders or icon-based spinners
- `<Tooltip>`, `<Popover>`, `<Modal>`, `<Dropdown>` — never custom implementations
- `<Link>` — never `<a>` tags (use HeroUI or Next.js Link)
- `<Chip>` — for status badges and tags
- `<Divider>` — never `<hr>`

If HeroUI doesn't cover the use case, reach for Shadcn/Radix. Only build a custom component when no library equivalent exists.

## Code Style

### TypeScript/JavaScript

- Package manager is **pnpm** — never use npm or yarn
- **Biome** for linting/formatting — not ESLint/Prettier
- **No inline imports** — all imports at the top of the file
- **Never use `any`** — always provide proper type definitions
- **Before creating a new type, search `src/types/` first** — do not duplicate existing types
- Path alias `@/` maps to `src/` in web/desktop
- **Never use Unicode/text symbols as UI elements** — no `→`, `↗`, `←`, `↑`, `↓`, `•`, `✓`, `×`, or any other Unicode symbol characters in rendered JSX. Always use icon components from `@icons` instead. This applies everywhere: demo components, cards, labels, badges, list items.

### Python

- **No inline imports** — all imports at the top of the file
- **Full type annotations required** on all functions and methods (enforced by mypy)
- **Ruff** for linting/formatting — not black/flake8/isort

Monorepo-wide rules live in `.claude/rules/general.md` (DRY, dead code, constants, feature-based org) and load every session.

Area-specific rules live in nested `CLAUDE.md` files that load automatically when you work in that part of the tree (path-scoped `.claude/rules` frontmatter does NOT auto-attach in this setup — nested CLAUDE.md does):
- **Frontend** (TS/React, Zustand, HeroUI, API layer, design): `apps/web/CLAUDE.md`
- **Backend** (Python, FastAPI route contract, services, Pydantic): `apps/api/CLAUDE.md`
- **Voice agent** (Python, LiveKit worker): `apps/voice-agent/CLAUDE.md`
- **Bots** (TypeScript): `apps/bots/CLAUDE.md`
- **SEO** (marketing pages, metadata, schemas, sitemaps): `apps/web/src/app/[locale]/(landing)/CLAUDE.md`
- **OpenUI system** (LLM-emitted generic components): `apps/web/src/config/openui/CLAUDE.md`
- **Chat bubbles & tool cards**: `apps/web/src/features/chat/components/bubbles/bot/CLAUDE.md`
- **Design tokens & system**: `DESIGN.md`

## Working Style

### Subagents & Parallelism

**Always spawn subagents wherever possible** — for research, exploration, or independent tasks, use the Agent tool with specialized subagents in parallel. Don't do sequentially what can be done concurrently.

### Deep Exploration

When investigating a bug, feature, or unfamiliar area of the codebase:

- **Never assume the root cause** — trace the actual code path. Read the relevant files, follow imports, and verify your hypothesis before proposing a fix.
- **Explore deeply** — use the `Explore` subagent for broad codebase discovery. For complex multi-file investigations, spawn multiple subagents to explore different layers in parallel.
- **Explore the intricacies** — check edge cases, related config, middleware, environment variables, and cross-app interactions. Do not stop at the surface.
- **Use relevant skills** — before starting any significant task, check if a skill applies (`writing-plans`, `accurate-testing`, `logging-best-practices`, `copywriting`, etc.) and invoke it via the `Skill` tool.

### Reporting Issues

When asked to find bugs or issues in the code, **only report problems that a real user would actually encounter**:

- Focus on broken UI, wrong data, missing functionality, bad UX flows, and visual bugs.
- **Do NOT flag theoretical race conditions or extreme timing edge cases.** If an issue requires contriving a microsecond-level timing scenario to reproduce, it is not a real issue.
- Ask yourself: "Would a QA tester find this bug in normal usage?" If not, don't report it.
- Prioritize: functional bugs > UX issues > visual inconsistencies > code quality. Skip hypothetical concerns.

### Task Tracking

**Always create todos for multi-step work** — use TaskCreate at the start of any non-trivial task. Update status (`in_progress` → `completed`) as you go. Never leave tasks stale.

### Planning

- **Plans must go in `.agents/plans/`** — never create plan files anywhere else. This directory is gitignored.
- **Plans must be comprehensive** — include architecture decisions, step-by-step implementation, edge cases, and rollback considerations before writing any code.
- **Plans contain only final decisions** — never include thought process, reasoning, pros/cons debates, or "why I chose X over Y" commentary. A plan is a spec, not a journal. If it reads like someone thinking out loud, rewrite it.
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

## Task Tracking

Only use the `bd` CLI when the user explicitly asks for it. `bd` is a project-internal CLI for task tracking and dolt database sync — **never invoke it automatically**. Otherwise, use built-in TodoWrite/TaskCreate tools.

## Implementation Plans

When creating implementation plans, store them in `.agents/plans/` directory. This folder is gitignored and used for planning documents before execution.

## Markdown Files

**Never create `.md` files** outside of `.agents/plans/` (gitignored) unless explicitly asked. Do not create `REVIEW.md`, `CONSISTENCY_REPORT.md`, `ANALYSIS.md`, spec files, or any other agent-generated documentation in the source tree. Planning and review artifacts belong only in `.agents/plans/` and only when absolutely necessary.

## Git Conventions

- **Never add Claude as a co-author in commits.** Do not include `Co-Authored-By: Claude` or any similar line in commit messages.
- **`develop` is the base branch, not `master`.** All feature branches are created from and merged into `develop`. When comparing branches, analyzing diffs, or creating PRs, always use `develop` as the base — not `master` or `main`.
- **NEVER merge pull requests.** Do not run `gh pr merge`, do not call any GitHub API merge endpoint, and do not take any action that merges a PR into any branch. PRs are merged by the team — not by Claude. This is an absolute rule with no exceptions.
- Work is **not complete until `git push` succeeds.** Always push before ending a session.
- **Never use `git pull --rebase` or `git rebase` when pulling/merging `origin/develop`.** Always use plain `git merge` — rebase inverts conflict markers (HEAD vs incoming) and causes confusion. Session close sequence (mandatory when code changed):
  ```bash
  git fetch origin
  git merge origin/develop  # if syncing with develop; plain merge, no rebase
  git push
  git status  # must show "up to date with origin"
  ```

## Shell Commands

Always use non-interactive flags to avoid hanging on prompts (shell aliases may add `-i` by default):

```bash
cp -f source dest      # NOT: cp source dest
mv -f source dest      # NOT: mv source dest
rm -f file             # NOT: rm file
rm -rf directory       # NOT: rm -r directory
```

## Common Issues

- Python deps not resolving → `nx run api:sync` or `nx run voice-agent:sync`
- Nx daemon issues → daemon is disabled (`useDaemonProcess: false` in `nx.json`)
- Web app uses `output: "standalone"` — required for Electron bundling, do not remove
- Console logs are stripped in production builds (except `console.error`)


<!-- nx configuration start-->
<!-- Leave the start & end comments to automatically receive updates. -->

## General Guidelines for working with Nx

- For navigating/exploring the workspace, invoke the `nx-workspace` skill first - it has patterns for querying projects, targets, and dependencies
- When running tasks (for example build, lint, test, e2e, etc.), always prefer running the task through `nx` (i.e. `nx run`, `nx run-many`, `nx affected`) instead of using the underlying tooling directly
- Prefix nx commands with the workspace's package manager (e.g., `pnpm nx build`, `npm exec nx test`) - avoids using globally installed CLI
- You have access to the Nx MCP server and its tools, use them to help the user
- For Nx plugin best practices, check `node_modules/@nx/<plugin>/PLUGIN.md`. Not all plugins have this file - proceed without it if unavailable.
- NEVER guess CLI flags - always check nx_docs or `--help` first when unsure

## Scaffolding & Generators

- For scaffolding tasks (creating apps, libs, project structure, setup), ALWAYS invoke the `nx-generate` skill FIRST before exploring or calling MCP tools

## When to use nx_docs

- USE for: advanced config options, unfamiliar flags, migration guides, plugin configuration, edge cases
- DON'T USE for: basic generator syntax (`nx g @nx/react:app`), standard commands, things you already know
- The `nx-generate` skill handles generator discovery internally - don't call nx_docs just to look up generator syntax


<!-- nx configuration end-->

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
