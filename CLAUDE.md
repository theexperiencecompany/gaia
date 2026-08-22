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
- **Name what the test did NOT exercise, as loudly as what it did.** A test of a simulation, translation, or proxy proves only that proxy — a fixture tests the fixture's assumptions, a unit test of extracted output proves the extraction, not the real engine. Before calling something verified, say exactly where the run stops being faithful to reality ("verified against a local webhook sink, not Slack"; "fired with synthetic series, not the real app's metrics"; "passed under `act`, not a real runner"). Then reach the highest-fidelity test that is feasible: run the real component, the real integration, the real delivery — first, not after being asked. Every silent-failure bug in a monitoring/alerting system survives precisely because its test stopped short of the real path.
- **A green test suite is not proof that the feature works.** Passing tests, lint, and type-check only prove the checks you happened to write did not fail. They do not prove the thing actually works — tests exercise the paths you already thought of, with fakes standing in for the parts most likely to break, in a process that never boots the way production does. Plenty of shipped bugs had a fully green suite. **After the work is done, drive it manually the way a real human user would**: boot the stack, hit the real endpoint, click through the real UI, send the real message, then go look at the real artifact it produced — the response body, the database row, the log file, the queue. Do this *in addition to* the suite, never instead of it, and never treat "all tests pass" as the finish line. If you cannot drive it manually, say so explicitly rather than implying it was verified.

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
- **Never defer cleanup to a "separate PR" — that PR never comes.** Scoping dead code, a duplicate implementation, or a known workaround out of the current change so some future PR can handle it is exactly how debt becomes permanent: the follow-up is never prioritized and the mess compounds. If your change touches an area that contains dead code, a duplicated implementation, or a stub, clean it up in the *same* PR — the context is loaded and the cost is never lower than right now. If a cleanup is genuinely too large to fold in, do not bury it in a commit message, a `# TODO`, or a PR description as "out of scope, follow-up later": announce it **loudly and explicitly to the user** and let them make the call out loud. Silent deferral is not a decision, it is how it never happens.

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
mise infisical <task>  # Team members: run any task with Infisical secrets injected (e.g. mise infisical dev:full)
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

### Agent System

The full agent architecture — comms → executor → subagents, bots, voice, skills, memory, notifications, workflows, todos, sandbox, MCP — is documented in **[`ARCHITECTURE.md`](./ARCHITECTURE.md)** at the repo root. **Read it before touching any agent code**; it lists every authoritative file path so you don't have to re-derive the system per session.

Quick map:
- **Comms agent** (user-facing, no work tools) → `apps/api/app/agents/core/graph_builder/build_graph.py` (`build_comms_*`)
- **Executor agent** (worker tier, all tools) → same file (`build_executor_*`) + `apps/api/app/agents/tools/executor_tool.py`
- **Subagents** (per-integration) → `apps/api/app/agents/core/subagents/` + `apps/api/app/config/oauth_config.py`
- **Bots** → `apps/bots/{telegram,whatsapp,discord,slack}/` + `libs/shared/ts/src/bots/`
- **Voice** → `apps/voice-agent/src/worker.py`
- **Skills** → `apps/api/app/agents/skills/`
- **Memory** → `apps/api/app/memory/` + `apps/api/app/agents/memory/`
- **Workflows / Notifications / Todos / Sandbox** → `apps/api/app/services/{workflow,notification,*,sandbox}/` + `apps/api/app/agents/tools/`

### Frontend (Web/Desktop)

**State Management**: Uses Zustand for global state. Each feature can have its own store in `src/stores/` or `src/features/{feature}/stores/`.

**Styling**: TailwindCSS with custom configuration. Uses Biome for linting/formatting instead of ESLint/Prettier.

**Desktop App**: The Electron app uses the Next.js standalone build output to bundle the web app for desktop.

### Backend (API)

**Database Setup**: The API depends on PostgreSQL, MongoDB, Redis, ChromaDB, and RabbitMQ. Use Docker Compose for local development.

**Background Tasks**: Uses ARQ (Redis-based task queue) for async job processing. Run with `nx worker api`.

**Dependency Management**: Uses `uv` for Python package management. Run `nx run api:sync` to install dependencies.

### Mobile App

Similar structure to web app with React Native components. Uses React Navigation for routing.

### Shared Libraries

**Python Shared (`libs/shared/`)**: Common utilities used across Python apps (API, voice-agent, bots). Includes logging, config, and Pydantic models.

**Install**: The `gaia-shared` package is automatically available to Python apps via workspace dependencies.

## Product Analytics (PostHog)

**Every user-facing feature ships an event.** A feature nobody can measure is a feature nobody can tell is working — treat a missing capture the same as a missing log line, not as a nice-to-have. Add it in the same change as the feature.

**Naming is `domain:action`**, lowercase, snake_case within each half — `chat:message_submitted`, `workflow:created`, `bot:file_uploaded`. Never invent a name inline: add it to the event enum for your surface, which is the single source of truth and what keeps the four surfaces from drifting.

| Surface | Helper | Event names |
|---|---|---|
| API (Python) | `capture_event(user_id, ...)` / `capture_context_event(...)` — `app/services/analytics_service.py` | `AnalyticsEvents` (same file) |
| Web (React) | `trackEvent(...)` — `apps/web/src/lib/analytics.ts` | `ANALYTICS_EVENTS` (same file) |
| Bots (Node) | `Analytics` — `libs/shared/ts/src/analytics/` | `BOT_EVENTS` (`analytics/events/bots.ts`) |
| Voice / other Python services | `PostHogAnalytics` — `libs/shared/py/analytics.py` | `VoiceAnalyticsEvents` (same file) |

### Identity — one person, one profile

`distinct_id` is **always GAIA's stable user id** (the Mongo user id). Never an email, never a platform handle, never a WorkOS id. Any other key creates a second profile for the same human, and cross-surface funnels silently stop joining — the failure is invisible in code review and only shows up as wrong numbers.

- Authenticated API requests get this for free: `PostHogRequestContextMiddleware` identifies the context, and `capture_context_event` inherits it.
- **A route excluded from auth MUST pass the id explicitly with `capture_event(user_id, ...)`.** OAuth callbacks, platform-link callbacks, bot routes and webhooks all resolve their user from state or a link record rather than a session cookie, so the request context has nobody to attribute to and the event lands on an anonymous profile. This is a real bug that shipped — see `oauth.py::composio_callback` and `platform_auth.py`.
- Bots resolve the linked GAIA id via `BaseBotAdapter.resolveDistinctId` and fall back to `"<platform>:<platformUserId>"` only while the account is unlinked; linking emits an `alias` so the pre-link history merges rather than stranding a ghost profile.

### Properties — no PII

Event properties are counts, enums, durations, booleans and ids — never message text, filenames, email addresses, transcripts, or raw platform identifiers. Log the *shape* of what happened, not its content. Bot logs additionally hash identifiers via `hashLogIdentifier`; PostHog gets neither the raw nor the hash.

### Where to capture

Capture **after the operation succeeds**, not before it starts — an event emitted on entry counts attempts as successes. Failure is its own event with a `reason`, not a missing one. Prefer the server: a client-side capture is lost to ad blockers, so anything the backend already sees belongs there.

**One user action, one event name, emitted from exactly one place — and that place is the server.** No exceptions. If the backend sees the action at all, the backend owns the event: it fires after the work actually succeeded, it sees the authoritative result, and no ad blocker can drop it. A client emitter for the same action fires on click — before the request resolves — so it counts attempts, failures and abandoned actions as successes, and it double-counts everything it *does* get right.

This was learned the expensive way. Twenty-four event names were being emitted from both the web app and the API at once, so twenty-four metrics read roughly double, and nothing failed to make that visible. `chat:message_sent` was the same mistake with a second name on it: every field it carried — tool, workflow, calendar event, reply, file count — already arrives in the request the server handles, so it was one message counted twice.

The client only emits what the server genuinely cannot see: UI interactions that never reach the backend at all. When you find yourself wanting a client event for something the server also handles, add the property to the server's event instead.

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
- **Observability** (Prometheus scrape config, Grafana alert rules, Slack/email alerting, runbooks): `infra/docker/observability/CLAUDE.md`
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

Tests are first-class: every new feature/refactor ships a test at the right tier; every bug ships a failing-then-passing test (see `apps/api/tests/CLAUDE.md` for which tier).

**The bug loop — every bug ships a failing-then-passing test, no exceptions.** The moment a real issue is found (by you, by the user, in review, or in production), stop and run this loop before fixing anything:

1. **Ask why the suite missed it.** Name the specific gap — no test covered this path at all, a test covered it but asserted too weakly, the boundary was never exercised, or the test mocked away the very code that broke. That answer determines what to write and often exposes neighbouring blind spots.
2. **Write the test that reproduces it, and watch it FAIL.** A test written after the fix, never observed red, proves nothing — it only asserts what the code now happens to do. Red first is the whole point.
3. **Pick the tier that actually catches it** — unit for logic and boundaries, integration for wiring between layers, e2e for user-visible behaviour through the real stack. When a bug spans layers, add one at each tier: the unit test pins the logic, the e2e test proves the user-facing symptom is gone. Prefer more tiers over fewer.
4. **Fix the root cause**, then confirm the test goes green.
5. **Never weaken the test to get green.** If it still fails, the fix is wrong or incomplete. Softening an assertion, `skip`ping, or `xfail`ing a real failure suppresses the bug instead of fixing it.

A bug that ships without a failing-then-passing test is a bug that will come back, and the second time nobody will remember why the code looked like that. See the `accurate-testing` skill for the mutation check that proves a test can actually fail.

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

## Agent-Driven E2E Testing

To verify a change in the real running app (not just lint/type-check), operate the live stack instead of trusting stdout — use the `driving-gaia` skill (boot the stack, dev-bypass auth, drive API/browser/bots, verify in Mongo), `reading-gaia-logs` to debug a failing run, and `parallel-worktrees` to run branches in parallel.

**On a machine with no Docker daemon** (cloud sandbox, CI runner, dev container), `mise dev` cannot start infra. Use `scripts/dev/sandbox-services.sh` + `scripts/dev/sandbox-env.sh` to run the same backing services natively — see the "No Docker daemon?" section of `driving-gaia`. Never conclude a change works because the test suite passed; boot it and drive it.

## Docker

Dockerfiles are located in each app directory. Docker Compose configuration is in `infra/docker/`.

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

## Markdown Files

**Never create `.md` files** outside of `.agents/plans/` (gitignored) unless explicitly asked. Do not create `REVIEW.md`, `CONSISTENCY_REPORT.md`, `ANALYSIS.md`, spec files, or any other agent-generated documentation in the source tree. Planning and review artifacts belong only in `.agents/plans/` and only when absolutely necessary.

## Git Conventions

- **Never add Claude as a co-author in commits.** Do not include `Co-Authored-By: Claude` or any similar line in commit messages.
- **`master` is the single base branch.** All feature branches are created from and merged into `master`. There is no `develop`. When comparing branches, analyzing diffs, or creating PRs, always use `master` as the base.
- **NEVER merge pull requests.** Do not run `gh pr merge`, do not call any GitHub API merge endpoint, and do not take any action that merges a PR into any branch. PRs are merged by the team — not by Claude. This is an absolute rule with no exceptions.
- Work is **not complete until `git push` succeeds.** Always push before ending a session.
- **Never use `git pull --rebase` or `git rebase` when pulling/merging `origin/master`.** Always use plain `git merge` — rebase inverts conflict markers (HEAD vs incoming) and causes confusion. Session close sequence (mandatory when code changed):
  ```bash
  git fetch origin
  git merge origin/master  # if syncing with master; plain merge, no rebase
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

## CI Parallelism & Caching — Rules

Rules for GitHub Actions, Nx affected, and Cloudflare deploys. Follow exactly — CI is the gate.

- **Use local `.nx/cache` via `actions/cache@v4`, not Nx Cloud.** Restore at job start, save if miss. Key: `nx-${os}-${hashFiles(pnpm-lock.yaml,nx.json,**/project.json)}-${hashFiles(apps/**,libs/**)}`. Never use `restore-keys` without a hash — prevents cache poisoning.
- **Single `pnpm install` / `uv sync` per workflow.** One `setup` job installs and caches (`pnpm-store-${hashFiles(pnpm-lock.yaml)}` + `~/.cache/uv` via `setup-uv` with `enable-cache` + `prune-cache: true`). Downstream jobs `needs: setup` — never reinstall per lane/job.
- **Docker layer cache lives in GHCR (`type=registry`), per-image `:buildcache` tag.** Every `docker/build-push-action` and `nx docker:build` uses `cache-from/cache-to: type=registry,ref=ghcr.io/theexperiencecompany/<repo>:buildcache,mode=max,image-manifest=true,oci-mediatypes=true,compression=zstd`. The GHA cache service was the bottleneck, not the network: `type=gha,mode=max` export measured 449s of a 951s docker-web build (~10MB/s writes) while the actual GHCR image push was ~40s. Free on a public repo, no 10 GB eviction pressure. Never `mode=min` alone. All images (web, grafana, api, voice-agent, all five bots) use this scheme — no `type=gha` remains.
- **Parallelize Docker builds.** `api` and `voice-agent` build in a matrix, not serially.
- **Coalesce master merges — final deploy wins.** `code-quality.yml` / `main.yml` use `cancel-in-progress: true` on `refs/heads/master` so 5 rapid merges cancel to 1 final verification. `build.yml` keeps `cancel-in-progress: false` so a running deploy never dies. Final SHA via `nrwl/nx-set-shas` with base = last successful master verifies the union of all 5.
- **Single affected detection.** One `detect` job runs `nrwl/nx-set-shas` and exports `base`/`head`; all lanes reuse it via `nx show projects --affected` / `nx affected`. Never duplicate `changed-files.sh` greps.
- **Use `nx affected -t <target>` with `cache: true`, not raw tools.** Lanes run `nx affected -t lint type-check build` so unaffected projects hit cache and skip. Do not call `biome`, `ruff`, or `tsc` directly outside Nx unless wrapped via `nx run-many`.
- **Keep `nx.json` inputs correct.** `api:build` (and similar) must list `pyproject.toml`, `uv.lock`, `libs/shared/py/**` etc. A missing input causes false cache hits that hide real changes.
- **Shard the bottleneck.** `test-python` (~10 m) is sharded into 2 via `pytest-split` (`--splits 2 --group N`). `test-fast` stays a non-blocking budget probe — never gate the PR on it alone.
- **Next.js cache key is minimal.** `restore-nextjs-cache` hashes only `pnpm-lock.yaml` + `next.config.*` + `open-next.config.ts` + `wrangler.jsonc`, never `apps/web/src/**`. Hashing sources thrashes the cache every commit.
- **Emit timing summaries every lane.** Each job appends duration + cache hit/miss to `$GITHUB_STEP_SUMMARY` and uses `::group::` for install logs plus `::error file=,line=` / `::warning` annotations. No lane fails silently.
- **Cloudflare deploys only via GitHub.** `deploy-web.yml` builds `pnpm --filter web cf:build`, uploads `apps/web/.open-next`, then deploys with `cloudflare/wrangler-action@v3` using `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` (minimal scope: Workers Scripts Write + R2 Write/Read + Routes Write). Workers Dashboard → Settings → Builds must stay Disconnected (`version_upload` only). PR previews deploy as `pr-<number>`; prod only on `refs/heads/master`.
- **Move heavy scans to cron.** `trivy`, `pip-audit`, and mutation testing (2–3 runners, skip modules <5 lines) run weekly in `security-cron.yml`, not on every PR.
- **Verify with real workflow runs + charts.** After CI changes, trigger `gh workflow run <workflow> --ref <branch>` on the branch, collect `gh run list` timings, and publish before/after bars in the PR body (images on the `pr-assets` branch) or `.agents/ci-report.html` (gitignored) — never commit metrics files into the source tree. Never claim CI is faster without measured runs.

## CI Discrepancies & Conventions — What Was Fixed and How To Keep It Fixed

Audits of all 12 workflows + 4 composites (`audit-*.md` in `.agents/plans/`) found **20 discrepancies** (8 P1 pinning/caching + 12 correctness/readability drifts). Every fix below is now the convention — **follow it for every new workflow, composite, or package bump**. If you diverge, the PR must explain why.

### 1. Pinning Policy — All `uses:` Pinned to SHA

- **Every external `uses:` is SHA-pinned with a trailing `# vX.Y.Z` comment.** Tags are mutable — a moved tag changes CI without a commit (supply-chain risk, zizmor `unpinned-uses` / `artipacked`).
- Pinned examples: `docker/login-action@dbcb813823bdd20940b903addbd779551569679f # v4.6.0`, `astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0`, `pnpm/action-setup@0977fd99725f1db4007ccb2928dbb4e90d06cc86 # v6.0.10`, `gitleaks/gitleaks-action@e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e # v3.0.0`, `amannn/action-semantic-pull-request@48f256284bd46cdaab1048c3721360e808335d50 # v6.1.1`.
- **Also pin inside composites** — `setup-node-pnpm` (`pnpm/action-setup` is pinned, `actions/setup-node@v7` must also be pinned), `restore-nextjs-cache` (`actions/cache@v6`), `setup-python-test-env` (`actions/cache/restore@v6` / `save@v6`). A pinned workflow that calls an unpinned composite is still unpinned.
- Exception: **local composites** (`./.github/actions/*`) are referenced by path, not SHA — intentional, not a gap.
- **How to bump:** resolve the SHA for the tag (`gh api repos/<owner>/<repo>/git/refs/tags/<tag>` or `git ls-remote`), update SHA + comment together. Renovate/Dependabot bumps SHA+comment atomically — do not bump comment alone.

### 2. Caching Strategy — Single `hashFiles` Convention

- **One cache key fragment reused everywhere:** `hashFiles('pnpm-lock.yaml','nx.json','**/project.json')` for the infra shape. Secondary hash is source-scoped: `hashFiles('apps/**','libs/**')` (repo-wide) or `hashFiles('apps/web/**','libs/shared/ts/**')` (web-only jobs like `deploy-web.yml`). Never invent a third hashing scheme.
- **Next.js cache is minimal** — `restore-nextjs-cache` hashes only `pnpm-lock.yaml` + `next.config.*` + `open-next.config.ts` + `wrangler.jsonc`, never `apps/web/src/**`. Hashing sources thrashes the cache every commit.
- **Use local `.nx/cache` via `actions/cache@v4`, not Nx Cloud.** Restore at job start, save if miss. Key: `nx-${os}-${hashFiles(pnpm-lock.yaml,nx.json,**/project.json)}-${hashFiles(apps/**,libs/**)}`. Never use `restore-keys` without a hash — prevents cache poisoning.
- **Single `pnpm install` / `uv sync` per workflow.** One `setup` job installs and caches (`pnpm-store-${hashFiles(pnpm-lock.yaml)}` + `~/.cache/uv` via `setup-uv` with `enable-cache: true` + `prune-cache: true`). Downstream jobs `needs: setup` — never reinstall per lane/job.
- **Docker layer cache is `type=registry` per image (`<repo>:buildcache` in GHCR), zstd-compressed.** Superseded the `type=gha,scope=<image>` scheme: the GHA cache API wrote large layers at ~10MB/s (449s of the 951s docker-web build, measured run 32599902431) while GHCR pushes the same layers in ~40s. `mode=max` preserves intermediate layers; `image-manifest=true,oci-mediatypes=true` keeps GHCR compatible; one `:buildcache` tag per image repo so parallel builds never clobber each other.
- **Do not mix `actions/cache` majors.** All workflows + composites use the same major (now `v5`/`v6` on `node24`; legacy `v4` was `node20`). Mixing `v5` vs `v6` creates separate namespaces and audit drift.

### 3. Node24 Policy — All Actions on `node24`

- **Every external action runs `node24` (verified via `action.yml` `runs.using: node24`).** No `node20`/`node16` remains.
- Upgrades that already landed: `nrwl/nx-set-shas@v4→v5`, `astral-sh/setup-uv@v5.4.2→v9.0.0` (12 occurrences), `gitleaks-action@v2→v3`, `docker/login-action@v3→v4`, `aquasecurity/trivy-action@0.35→0.36`, `actions/cache@v4→v5/v6`, `actions/upload-artifact@v4→v6/v7`, `actions/download-artifact@v4→v7`. `actions/github-script@v7→v8` where used.
- **When adding a new `uses:`:** fetch its `action.yml` via `raw.githubusercontent.com/<owner>/<repo>/<tag>/action.yml` and verify `runs.using: node24`. If it is `node20`, bump the tag until it is `node24` before merging. Pin the SHA at that tag.

### 4. Coverage — 70% Temporary, Target 80%

- `main.yml: test-python-coverage` enforces `--cov-fail-under=70` on the **merged** shard coverage (not per-shard). Per-shard runs use `--cov-fail-under=0` — a single shard covers a subset and must not gate.
- **Why 70:** repo TOTAL is 78% today; the long-standing gate is 80%. `da968e1ca` relaxed 80→70 to unblock PRs (TOTAL 78% < 80 would red every PR for pre-existing debt, not the PR's change). The gate header and `quality-gate` job both carry `TODO: bump to 80% when coverage improves`.
- **Do not raise to 80** until TOTAL is ≥80 and stays there. When you do, update both the `coverage report --fail-under` line and the `quality-gate` comment in the same PR. Diff-cover (`--fail-under=90` on changed lines) stays at 90 regardless.

### 5. Trivy — Blocking (Was Advisory)

- `main.yml: trivy-scan` is now **blocking**: `scan-type: fs`, `severity: CRITICAL,HIGH`, `scan-ref: .`, `exit-code: 1`, `ignore-unfixed: false`, `format: table`. `continue-on-error: false` (no silent pass). The job is in `quality-gate.needs` — a HIGH/CRITICAL fails the gate.
- **Was advisory:** `continue-on-error: true` with 12 known HIGH in `pnpm-lock.yaml` (axios, brace-expansion, fast-uri, next CVEs, postcss, sharp) — flipping to blocking then would red every PR for pre-existing findings.
- **Now:** lock already has overrides for those 12; trivy currently reports ~25 HIGH (axios 1.19.0, undici 6.28/7.29, tar 7.5.22, adm-zip 0.5.18, brace-expansion 5.0.9, etc.) — those must be fixed via `pnpm.overrides` before trivy goes green. **Do not set `ignore-unfixed: true`** to hide them; fix the package or add a per-finding allowlist with a linked CVE and expiry, reviewed in the same PR.

### 6. Dead-Code — `wrangler` Is an Ignored Binary (Not Dead Code)

- `deploy-web.yml` switched from `cloudflare/wrangler-action@v3` to `pnpm exec wrangler deploy` / `versions upload` (wrangler is already in `pnpm-lock.yaml` at 4.110.0; `wrangler-action` tried `npm i wrangler@3.90.0`/`pnpm add` without `-w` and failed with `ERESOLVE` / `ERR_PNPM_ADDING_TO_ROOT` in the pnpm workspace).
- `knip` then flagged `wrangler` as an unlisted binary. Fix: `config/knip.config.ts: ignoreBinaries: ["wrangler", ...]` — correct, because wrangler is provided by the monorepo root `pnpm-lock.yaml` and invoked via `pnpm exec`, not listed per `apps/web/package.json`. `wrangler` is already in the root-deps allowlist comment ("Binaries provided by monorepo root, mise, Nx, or pnpm scripts").
- **Do not remove `wrangler` from `ignoreBinaries`** and do not add it to `apps/web` `dependencies` to silence knip — it is a CLI invoked from CI, not a runtime import. Same rule applies to `biome`, `nx`, `uv`, `tsx`, `playwright` etc. already listed.

### 7. Preview Deploy — `pnpm exec wrangler` (Not `wrangler-action`)

- **Build:** `pnpm --filter ./apps/web cf:build` (path filter; `pnpm-workspace.yaml` globs resolve `./apps/web` — package name is `gaia` but path filter is canonical in this repo). Keep the `--filter ./apps/web` form; `pnpm --filter gaia` also works but is not the convention here.
- **Prod deploy:** `pnpm exec wrangler deploy --config apps/web/wrangler.jsonc` with `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` in `env:` (not inline `${{ }}`). Minimal token scopes: `Workers Scripts Write + R2 Write/Read + Routes Write` on `d65fe47d…`, expires 2027-08-21.
- **Preview deploy:** `pnpm exec wrangler versions upload --preview-alias pr-${{ github.event.number }} --config apps/web/wrangler.jsonc` — not `wrangler-action` `packageManager: npm` workaround (removed in `45632ba66`). Preview reuses `setup-node-pnpm` + built `.open-next` artifact (`path: apps/web/.open-next`, `include-hidden-files: true`).
- **Why not `wrangler-action`:** it auto-detects `pnpm` and runs `pnpm add wrangler` without `-w` in a workspace root, which fails; forcing `packageManager: npm` then fails with peer `react@19.1.0 vs 19.2.3` `ERESOLVE`. `pnpm exec wrangler` avoids both by using the already-installed binary.

### 8. Skipped / Non-Gated Lanes — Intentional, Not Forgotten

- **`main.yml: quality-gate` deliberately excludes `changelog-sync`.** That job auto-opens a fix PR (`fix/changelog-sync-<branch>`) when `docs/release-notes/` is stale — it is non-blocking by design and must not red the gate.
- **`main.yml: trivy-scan` is now included** (was excluded when advisory). Keep it in `quality-gate.needs` while blocking.
- **`code-quality.yml: quality-gate` enforces 20 lanes** (biome, deps, circular, file-size, types-location, components-per-file, duplicates, package-hygiene, type-check, python-static (ruff + custom lints + xenon + interrogate + bandit + pip-audit, each step `continue-on-error` behind an aggregating verdict), python-mypy, observability, wide-event-conformance, dead-code, alert-rules, suppression-ratchet, gitleaks, semgrep, `test-mutation`). `test-mutation-plan` is the planner; `test-mutation` (sharded, `max-parallel: 12`, per-module `timeout-minutes: 20`) is the gated lane.
- **`build.yml: docker-grafana` is not a quality gate gate** — it publishes `gaia-grafana:latest` unconditionally; the Swarm deploy pins `grafana_image_tag` only when that lane succeeded. Do not add it to `main.yml:quality-gate`.
- **`main.yml: trigger-build` is `always() && quality-gate == success && github.ref == refs/heads/master`** — `always()` suppresses the implicit `success()` that would false-negative on skipped ancestors (e.g. `build` skips on Python-only changes but `quality-gate` is still success). `build.yml` uses `cancel-in-progress: false` (deploys must queue, never cancel); `main.yml`/`code-quality.yml` use `cancel-in-progress: true` on `refs/heads/master` (5 rapid merges coalesce to 1 final verification via `nrwl/nx-set-shas` base = last successful master).

### 9. How To Bump Packages Safely — The `chore/pip-audit-aiohttp` Pattern

- **Python and JS bumps ship in separate PRs.** `chore/pip-audit-aiohttp` (`db481e245` → merged as `a97cfd731` into both `master` and `fix/ci-improve-all-14`) bumped `aiohttp 3.14.1→3.14.3`, `cryptography 49→50`, `pyasn1 0.6.3→0.6.4`, plus transitive `pyopenssl 26.3→26.4` and `pillow 12.2→12.3` / `click 8.3.3→8.4.2` / `json-repair 0.60.1` via `da968e1ca`. Do not re-bump Python in a JS fix PR and vice versa — mixed bumps hide the real blame and break `uv.lock` vs `pnpm-lock.yaml` bisect.
- **Python:** bump `constraint-dependencies` in root `pyproject.toml` (`aiohttp>=3.14.3`, `cryptography>=50.0.0`, `pyasn1>=0.6.4`, `pillow>=12.3.0`, etc.) **and** `apps/api/pyproject.toml` / `apps/voice-agent/pyproject.toml` in the same commit, then `uv lock` (or `uv sync`) to regenerate `uv.lock`. Verify with `uv run --frozen pytest` and `pip-audit` locally; trivy `fs` on `uv.lock` should be clean. `ecdsa` `GHSA-wj6h-64fc/PYSEC-2026-1325` has no upstream fix (side-channel out of scope) — it is allowlisted via `pip-audit --ignore-vuln` with a comment, not by raising `ignore-unfixed`.
- **JS (npm):** fix via `pnpm.overrides` in root `package.json` (e.g. `axios@<1.19.0: 1.19.0`, `undici@>=6<6.28: 6.28.0` + `>=7<7.29: 7.29.0`, `tar@<7.5.22: 7.5.22`, `adm-zip@<0.5.18: 0.5.18`, `brace-expansion@<5.0.9: 5.0.9`), then `pnpm install --frozen-lockfile` to update `pnpm-lock.yaml`. Prefer same-major patches (`axios 1.16→1.19` is still `1.x`, `undici` 6.27→6.28 / 7.24→7.29 are within-major, `adm-zip 0.5.10→0.5.18` is within `0.5` — do not jump `adm-zip 0.5→0.6` or `undici 7→8` in a CVE fix PR). Verify with `pnpm audit` / `trivy fs .` locally; CI `trivy-scan` must be green before merge. Open as `chore/trivy-npm-audit`, not mixed with Python.
- **After bumping:** trigger `gh workflow run main.yml --ref <branch>` and `gh workflow run deploy-web.yml --ref <branch>`, collect `gh run list` timings, and publish before/after in the PR. Never claim "CI is faster / fixed" without measured runs.

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

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.
