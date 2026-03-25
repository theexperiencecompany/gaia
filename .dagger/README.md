# Dagger CI — Local Testing Guide

The `gaia-ci` Dagger module provides containerized quality checks that run identically locally and in CI — same container, same steps, no surprises.

## Prerequisites

- **Dagger CLI v0.20.2** — matches the version pinned in CI:
  ```bash
  curl -fsSL https://dl.dagger.io/dagger/install.sh | DAGGER_VERSION=0.20.2 sh
  # Move the binary somewhere on your PATH, e.g. /usr/local/bin
  ```
- **Docker** running locally (Dagger uses it as the container runtime)
- Run all `dagger call` commands from the **repo root** — the module is auto-discovered via `dagger.json`

---

## Quality Checks

### Individual checks

```bash
# Lint (Biome for JS/TS, Ruff for Python)
dagger call lint

# Type-check (TypeScript tsc + mypy)
dagger call type-check

# Build all projects
dagger call build

# Test (JS/TS via Nx + Python via pytest, excluding integration/composio tests)
dagger call test
```

### Full quality gate (what CI runs on every PR)

Runs lint, type-check, build, and test in a single pipeline — the exact same gate as the `quality-checks` CI job:

```bash
dagger call quality-checks
```

---

## Caching

Dagger automatically persists named cache volumes across local runs — no manual setup required. The module uses three volumes:

| Volume | Contents |
|---|---|
| `pnpm-store` | pnpm package store |
| `uv-cache` | uv/pip download cache |
| `nx-cache` | Nx computation cache |

Subsequent runs of any function that calls `ci-env` internally (lint, type-check, build, test, quality-checks) will reuse these caches, making them significantly faster after the first run.

---

## CI Integration

`.github/workflows/main.yml` calls `dagger call quality-checks` as its quality gate for PRs and pushes. Docker image builds in `build.yml` use Blacksmith (not Dagger) for faster CI-optimized builds.

What passes locally will pass in CI.
