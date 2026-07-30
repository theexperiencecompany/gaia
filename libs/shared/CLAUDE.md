# libs/shared

Shared utilities consumed by all GAIA Python apps (API, voice-agent, bots) and TypeScript apps (bots, CLI).

## Structure

```
py/                  - gaia-shared Python package
  logging.py         - Loguru-based logging (auto-configured on import)
  wide_events.py     - Wide event logger (one structured event per request)
  secrets.py         - Infisical secrets injection
  settings/
    base.py          - BaseAppSettings, CommonSettings (Pydantic)
    validator.py     - SettingsValidator for grouped missing-key warnings
  __init__.py        - Re-exports: get_contextual_logger, log, wide_task

ts/                  - @gaia/shared TypeScript package
  src/
    bots/            - Bot adapter, commands, GaiaClient, streaming utilities
    cli/             - CLI command manifest (descriptions shared with packages/cli)
  package.json       - private, ESM, no build step (imported directly from src/)
```

## Key Commands

```bash
# Lint Python
nx lint shared-python          # runs: uvx ruff check .

# Format Python
nx format shared-python        # runs: uvx ruff format .

# TypeScript has no separate build — imported directly via path alias
```

## How Shared Works in the Monorepo

### Python (`libs/shared/py/` → `gaia-shared`)

The Python shared package is a local `uv` workspace package named `gaia-shared`. Apps (`apps/api`, `apps/voice-agent`, `apps/bots`) declare it as a workspace dependency in their `pyproject.toml`:

```toml
dependencies = ["gaia-shared"]
```

`uv` resolves it via the workspace `[tool.uv.workspace]` config at the repo root. After adding or modifying `libs/shared/py/`, run `nx run api:sync` (or the relevant app's sync target) to refresh the lockfile.

**When to add Python code here:**
- Logging, secrets, settings — anything two or more Python apps need
- Do not add app-specific business logic; keep this package lean and generic

### TypeScript (`libs/shared/ts/` → `@gaia/shared`)

The TypeScript package is a private workspace package. It has **no build step** — apps import directly from source via the `@gaia/shared` path alias resolved by the Nx workspace. No compilation is needed after editing.

**When to add TypeScript code here:**
- Bot adapters, CLI manifest, streaming utilities, or any logic shared across `apps/bots`, `packages/cli`, or future consumers
- React/RN hooks and utilities shared between `web`, `desktop`, and `mobile`

### DRY Enforcement

If you find duplicated logic across apps, consolidate it here. Update all import sites. Do not leave dead copies behind.

## Gotchas

- **Console logging is configured on import** — just importing `shared.py.logging` activates loguru. Apps that need file logging must call `configure_file_logging(log_dir)` explicitly (the API does this; do not add it to shared itself).
- **`LOG_FORMAT=json`** must be set in Docker environments so Promtail can parse NDJSON. Console mode (`LOG_FORMAT=console`) is the default for local development.
- **Wide events use `ContextVar`** — each async task/request gets its own isolated event. HTTP middleware calls `log.reset()` at request start; ARQ workers must use the `wide_task()` context manager instead.
- **Custom log levels**: `PERFORMANCE` (3), `AUDIT` (28), `SECURITY` (38). App code emits AUDIT via `log.audit(...)` (the wide-event facade). PERFORMANCE-file routing and SECURITY require raw loguru (`logger.bind(performance=True)` / `logger.log("SECURITY", ...)`), which the `wide-events-logging` lint bans in `app/` — they are reachable only from shared/infra code. `log.bind(...)` on the wide-event facade merges into the event and does NOT tag subsequent real-time lines.
- **Infisical is not required for local dev** — missing Infisical env vars log a warning and return in non-production. In production (`ENV=production`) they raise `InfisicalConfigError`.
- **Local env vars take precedence** over Infisical secrets — Infisical only injects keys that are not already set in `os.environ`.
- **TypeScript package has no build step** — `main` and `types` both point to `src/index.ts`. It is consumed directly from source via workspace resolution.
- No inline imports. All Python code must have full type annotations enforced by mypy + ruff.
