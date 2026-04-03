# CI Pipeline Restructure

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the monolithic `quality-checks` job with focused, parallel, conditional jobs. Leverage Nx affected detection to skip irrelevant work. Add pytest-xdist for parallel test execution. Add a pre-built CI base image. Move coverage to a separate non-blocking check.

**Architecture:** A lightweight `detect` job runs `nx show projects --affected` on the GH Actions runner (same pattern as `build.yml`). All quality jobs run in parallel after detect, with no sequential gates. Dagger functions accept an optional `projects` parameter so Nx only runs affected projects inside the container. A `quality-gate` summary job gates branch protection and the downstream `trigger-build`.

**Tech Stack:** GitHub Actions, Dagger (Python SDK), Nx affected detection, pytest-xdist

---

## Flow

```
detect (ubuntu-latest, ~30s)
  │
  ├─► static-checks-backend   (if: has_backend, ~3 min)
  ├─► static-checks-frontend  (if: has_frontend, ~3 min)
  ├─► build                   (if: has_frontend, ~5 min)
  ├─► test-backend             (if: has_backend, ~5-7 min with xdist)
  ├─► test-frontend            (if: has_frontend, ~3 min)
  ├─► dead-code               (if: has_backend || has_frontend, ~2 min)
  ├─► release-validation      (always, ~30s)
  ├─► trivy-scan              (always, non-blocking, ~2 min)
  │
  └─► quality-gate            (summary, gates branch protection)
        │
        └─► trigger-build     (master only, calls build.yml)
```

All jobs after detect run in parallel. No sequential gates. Critical path: **detect (30s) + test-backend (~7 min) = ~8 min.**

---

## Affected detection

`.git` is in Dagger's `_IGNORE` list, so `nx affected` can't run inside the container. Detection runs on the GH Actions runner (cheap `ubuntu-latest`), passing affected project lists to Dagger functions.

| Scope | Projects |
|-------|----------|
| `has_backend` | `api`, `voice-agent`, `shared-python`, `bot-discord`, `bot-slack`, `bot-telegram`, `bot-whatsapp` |
| `has_frontend` | `web`, `desktop`, `mobile`, `shared-typescript`, `docs` |

`workflow_dispatch` forces both scopes.

Dagger functions accept an optional `projects` parameter. When provided, Nx uses `-p {projects}` to run only affected projects. When omitted (local use), Nx runs everything.

## Test naming

- `test_backend()` — all Python tests with live services (Postgres, Redis, Mongo, Chroma, RabbitMQ). Uses pytest-xdist (`-n auto`) for parallel execution.
- `test_frontend()` — JS/TS tests via Nx.
- `test()` — convenience, runs both (for local use).
- `integration_test()` and `service_test()` stay for targeted local use.

## Performance improvements

1. **pytest-xdist**: `-n auto` distributes tests across CPU cores. 4-vCPU runner = ~3x speedup. 12 min → 4-6 min.
2. **Pre-built CI base image**: `ghcr.io/theexperiencecompany/gaia-ci-base:latest` with Node, Python, pnpm, uv pre-installed. Saves ~30-40s per job.
3. **Coverage as separate non-blocking check**: `--cov` adds ~10-20% overhead. Move to informational-only. Enforce on master only via a separate `coverage` job.

## Branch protection

The `quality-gate` summary job is the single required check for branch protection. It passes when all sub-jobs pass or are skipped. No need to update branch protection rules when adding/removing jobs.

---

## Task 1: Create the CI base image Dockerfile

**Files:**
- Create: `infra/docker/ci-base.Dockerfile`

```dockerfile
FROM node:22.15.1-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 python3-pip python3-venv python3-dev \
       git curl build-essential libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable && corepack prepare pnpm@10.17.1 --activate

RUN pip install --break-system-packages uv
```

Build and push (one-time, then automated via a separate workflow or manual rebuild when tooling versions change):

```bash
docker build -f infra/docker/ci-base.Dockerfile -t ghcr.io/theexperiencecompany/gaia-ci-base:latest .
docker push ghcr.io/theexperiencecompany/gaia-ci-base:latest
```

---

## Task 2: Update Dagger pipeline

**Files:**
- Modify: `.dagger/src/gaia_ci/main.py`

### Step 1: Update `ci_env()` to use pre-built base image

Replace the `from_("node:22.15.1-bookworm-slim")` + apt-get + corepack + pip chain with:

```python
@function
def ci_env(self, source: Source) -> dagger.Container:
    """Create a full CI environment from pre-built base image."""
    pnpm_cache = dag.cache_volume("pnpm-store")
    uv_cache = dag.cache_volume("uv-cache")
    nx_cache = dag.cache_volume("nx-cache")
    next_cache = dag.cache_volume("next-cache")
    pip_cache = dag.cache_volume("pip-cache")
    return (
        dag.container()
        .from_("ghcr.io/theexperiencecompany/gaia-ci-base:latest")
        .with_mounted_cache("/root/.local/share/pnpm/store", pnpm_cache)
        .with_mounted_cache("/root/.cache/uv", uv_cache)
        .with_mounted_cache("/root/.cache/pip", pip_cache)
        .with_mounted_cache("/app/.nx/cache", nx_cache)
        .with_mounted_cache("/app/apps/web/.next/cache", next_cache)
        .with_directory("/app", source)
        .with_workdir("/app")
        .with_exec(["pnpm", "install", "--frozen-lockfile"])
        .with_exec(
            [
                "uv",
                "sync",
                "--frozen",
                "--package",
                "gaia",
                "--group",
                "backend",
                "--group",
                "dev",
            ]
        )
    )
```

### Step 2: Add `static_checks_backend()` and `static_checks_frontend()`

```python
@function
async def static_checks_backend(
    self,
    source: Source,
    projects: Annotated[str, Doc("Comma-separated Nx project names to check")] = "",
) -> str:
    """Run backend static analysis: Ruff linting + mypy type checking."""
    env = self.ci_env(source)
    lint_cmd = ["npx", "nx", "run-many", "-t", "lint", "--parallel=3"]
    tc_cmd = ["npx", "nx", "run-many", "-t", "type-check", "--parallel=3"]
    if projects:
        lint_cmd.extend(["-p", projects])
        tc_cmd.extend(["-p", projects])

    lint_task = env.with_exec(lint_cmd).stdout()
    type_check_task = (
        env.with_workdir("/app/apps/api")
        .with_exec(["uv", "run", "mypy", "--install-types", "--non-interactive"])
        .with_workdir("/app")
        .with_exec(tc_cmd)
        .stdout()
    )
    lint_out, tc_out = await asyncio.gather(lint_task, type_check_task)
    return f"{'=' * 60}\n LINT (backend)\n{'=' * 60}\n{lint_out}\n\n{'=' * 60}\n TYPE-CHECK (backend)\n{'=' * 60}\n{tc_out}"

@function
async def static_checks_frontend(
    self,
    source: Source,
    projects: Annotated[str, Doc("Comma-separated Nx project names to check")] = "",
) -> str:
    """Run frontend static analysis: Biome linting + TypeScript type checking."""
    env = self.ci_env(source)
    lint_cmd = ["npx", "nx", "run-many", "-t", "lint", "--parallel=3"]
    tc_cmd = ["npx", "nx", "run-many", "-t", "type-check", "--parallel=3"]
    if projects:
        lint_cmd.extend(["-p", projects])
        tc_cmd.extend(["-p", projects])

    lint_task = env.with_exec(lint_cmd).stdout()
    type_check_task = env.with_exec(tc_cmd).stdout()
    lint_out, tc_out = await asyncio.gather(lint_task, type_check_task)
    return f"{'=' * 60}\n LINT (frontend)\n{'=' * 60}\n{lint_out}\n\n{'=' * 60}\n TYPE-CHECK (frontend)\n{'=' * 60}\n{tc_out}"
```

### Step 3: Add `test_backend()` with pytest-xdist

```python
@function
async def test_backend(self, source: Source) -> str:
    """Run all backend Python tests with live service containers and parallel execution.

    Spins up PostgreSQL, Redis, MongoDB, ChromaDB, and RabbitMQ.
    Uses pytest-xdist (-n auto) for parallel test execution.
    """
    return await (
        self._service_test_container(source)
        .with_exec(["uv", "pip", "install", "pytest-xdist"])
        .with_exec(
            [
                "uv",
                "run",
                "pytest",
                "-n",
                "auto",
                "-m",
                "not composio",
                "--tb=short",
                "-q",
                "--override-ini=addopts=--strict-markers",
            ]
        )
        .stdout()
    )
```

### Step 4: Add `test_frontend()`

```python
@function
async def test_frontend(
    self,
    source: Source,
    projects: Annotated[str, Doc("Comma-separated Nx project names to test")] = "",
) -> str:
    """Run frontend tests (JS/TS via Nx)."""
    cmd = ["npx", "nx", "run-many", "-t", "test", "--parallel=3"]
    if projects:
        cmd.extend(["-p", projects])
    return await (
        self.ci_env(source)
        .with_env_variable("ENV", "test")
        .with_exec(cmd)
        .stdout()
    )
```

### Step 5: Add `trivy_scan()` as standalone function

```python
@function
async def trivy_scan(self, source: Source) -> str:
    """Run Trivy security scan for CRITICAL and HIGH vulnerabilities (informational)."""
    return await (
        dag.container()
        .from_("ghcr.io/aquasecurity/trivy:latest")
        .with_directory("/src", source)
        .with_exec(
            [
                "filesystem",
                "--severity",
                "CRITICAL,HIGH",
                "--format",
                "table",
                "--skip-dirs",
                "node_modules,.venv,dist,.next,out",
                "/src",
            ],
            expect=dagger.ReturnType.ANY,
        )
        .stdout()
    )
```

### Step 6: Add `coverage()` as a separate check

```python
@function
async def coverage(self, source: Source) -> str:
    """Run backend test coverage report (informational, does not fail CI)."""
    return await (
        self._service_test_container(source)
        .with_exec(["uv", "pip", "install", "pytest-xdist"])
        .with_exec(
            [
                "uv",
                "run",
                "pytest",
                "-n",
                "auto",
                "-m",
                "not composio",
                "--tb=short",
                "-q",
                "--cov=app",
                "--cov-report=term-missing",
                "--override-ini=addopts=--strict-markers",
            ],
            expect=dagger.ReturnType.ANY,
        )
        .stdout()
    )
```

### Step 7: Update `quality_checks()` to use new functions

```python
@function
async def quality_checks(self, source: Source) -> str:
    """Run the full quality gate in parallel (convenience for local use)."""
    results = await asyncio.gather(
        self.static_checks_backend(source),
        self.static_checks_frontend(source),
        self.build(source),
        self.test_backend(source),
        self.test_frontend(source),
        self.dead_code(source),
        self.validate_release(source),
        self.trivy_scan(source),
    )
    labels = [
        "STATIC-CHECKS (backend)",
        "STATIC-CHECKS (frontend)",
        "BUILD",
        "TESTS (backend)",
        "TESTS (frontend)",
        "DEAD-CODE",
        "RELEASE-VALIDATION",
        "TRIVY-SCAN",
    ]
    sections = []
    for label, output in zip(labels, results):
        sections.append(f"{'=' * 60}\n {label}\n{'=' * 60}\n{output}")
    return "\n\n".join(sections)
```

### Step 8: Add pytest-xdist to dev dependencies

**Files:**
- Modify: `apps/api/pyproject.toml`

Add `pytest-xdist` to the dev dependency group so it's available in the uv sync.

---

## Task 3: Rewrite main.yml

**Files:**
- Modify: `.github/workflows/main.yml`

```yaml
name: Quality Checks

on:
  pull_request:
    branches: [develop, master]
  push:
    branches: [master]
  workflow_dispatch:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  # ── Policy: master promotion guard ─────────────────────────
  policy:
    if: github.event_name == 'pull_request' && github.base_ref == 'master'
    runs-on: ubuntu-latest
    steps:
      - name: Enforce master promotion policy
        uses: actions/github-script@v7
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          script: |
            const pr = context.payload.pull_request;
            const allowed = pr.head.ref === "develop" || pr.head.ref.startsWith("release-please--");
            if (!allowed) {
              core.setFailed(`PRs to master must come from develop or release-please branches. Got '${pr.head.ref}'.`);
            }

  # ── Detect: Nx affected scopes ─────────────────────────────
  detect:
    runs-on: ubuntu-latest
    outputs:
      has_backend: ${{ steps.scope.outputs.has_backend }}
      has_frontend: ${{ steps.scope.outputs.has_frontend }}
      backend_projects: ${{ steps.scope.outputs.backend_projects }}
      frontend_projects: ${{ steps.scope.outputs.frontend_projects }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: nrwl/nx-set-shas@v4
        with:
          main-branch-name: master
      - uses: pnpm/action-setup@v4
        with:
          version: 10.17.1
      - uses: actions/setup-node@v4
        with:
          node-version: "22.15.1"
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - name: Detect affected scopes
        id: scope
        run: |
          AFFECTED_RAW="$(npx nx show projects --affected 2>/dev/null || true)"
          AFFECTED="$(printf '%s\n' "$AFFECTED_RAW" | tr ' ' '\n' | sed '/^$/d')"
          echo "Affected projects: $AFFECTED"

          BACKEND_PROJS=""
          FRONTEND_PROJS=""

          for proj in api voice-agent shared-python bot-discord bot-slack bot-telegram bot-whatsapp; do
            if echo "$AFFECTED" | grep -qx "$proj"; then
              BACKEND_PROJS="${BACKEND_PROJS:+$BACKEND_PROJS,}$proj"
            fi
          done

          for proj in web desktop mobile shared-typescript docs; do
            if echo "$AFFECTED" | grep -qx "$proj"; then
              FRONTEND_PROJS="${FRONTEND_PROJS:+$FRONTEND_PROJS,}$proj"
            fi
          done

          # Force all on workflow_dispatch
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            BACKEND_PROJS="api,voice-agent,shared-python,bot-discord,bot-slack,bot-telegram,bot-whatsapp"
            FRONTEND_PROJS="web,desktop,mobile,shared-typescript,docs"
          fi

          has_backend=$( [ -n "$BACKEND_PROJS" ] && echo true || echo false )
          has_frontend=$( [ -n "$FRONTEND_PROJS" ] && echo true || echo false )

          echo "has_backend=$has_backend" >> "$GITHUB_OUTPUT"
          echo "has_frontend=$has_frontend" >> "$GITHUB_OUTPUT"
          echo "backend_projects=$BACKEND_PROJS" >> "$GITHUB_OUTPUT"
          echo "frontend_projects=$FRONTEND_PROJS" >> "$GITHUB_OUTPUT"
          echo "Scopes => backend: $has_backend ($BACKEND_PROJS), frontend: $has_frontend ($FRONTEND_PROJS)"

  # ── Warm: pre-pull Dagger engine image ─────────────────────
  warm-engine:
    runs-on: blacksmith-4vcpu-ubuntu-2404
    steps:
      - name: Warm Dagger engine image
        run: |
          for i in 1 2 3; do
            docker pull registry.dagger.io/engine:v0.20.3 && break
            echo "Pull attempt $i failed, retrying in 15s..."
            sleep 15
          done
        timeout-minutes: 20

  # ── All checks run in parallel after detect + warm ─────────

  static-checks-backend:
    needs: [detect, warm-engine]
    if: needs.detect.outputs.has_backend == 'true'
    runs-on: blacksmith-4vcpu-ubuntu-2404
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Backend lint + type-check
        uses: dagger/dagger-for-github@v8.4.1
        with:
          version: "0.20.3"
          dagger-flags: "--silent"
          call: static-checks-backend --projects=${{ needs.detect.outputs.backend_projects }}
        timeout-minutes: 15

  static-checks-frontend:
    needs: [detect, warm-engine]
    if: needs.detect.outputs.has_frontend == 'true'
    runs-on: blacksmith-4vcpu-ubuntu-2404
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Frontend lint + type-check
        uses: dagger/dagger-for-github@v8.4.1
        with:
          version: "0.20.3"
          dagger-flags: "--silent"
          call: static-checks-frontend --projects=${{ needs.detect.outputs.frontend_projects }}
        timeout-minutes: 15

  build:
    needs: [detect, warm-engine]
    if: needs.detect.outputs.has_frontend == 'true'
    runs-on: blacksmith-4vcpu-ubuntu-2404
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Build
        uses: dagger/dagger-for-github@v8.4.1
        with:
          version: "0.20.3"
          dagger-flags: "--silent"
          call: build
        timeout-minutes: 15

  test-backend:
    needs: [detect, warm-engine]
    if: needs.detect.outputs.has_backend == 'true'
    runs-on: blacksmith-4vcpu-ubuntu-2404
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Backend tests (with services + xdist)
        uses: dagger/dagger-for-github@v8.4.1
        with:
          version: "0.20.3"
          dagger-flags: "--silent"
          call: test-backend
        timeout-minutes: 25

  test-frontend:
    needs: [detect, warm-engine]
    if: needs.detect.outputs.has_frontend == 'true'
    runs-on: blacksmith-4vcpu-ubuntu-2404
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Frontend tests
        uses: dagger/dagger-for-github@v8.4.1
        with:
          version: "0.20.3"
          dagger-flags: "--silent"
          call: test-frontend --projects=${{ needs.detect.outputs.frontend_projects }}
        timeout-minutes: 15

  dead-code:
    needs: [detect, warm-engine]
    if: needs.detect.outputs.has_backend == 'true' || needs.detect.outputs.has_frontend == 'true'
    runs-on: blacksmith-4vcpu-ubuntu-2404
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Dead code detection
        uses: dagger/dagger-for-github@v8.4.1
        with:
          version: "0.20.3"
          dagger-flags: "--silent"
          call: dead-code
        timeout-minutes: 10

  release-validation:
    needs: [warm-engine]
    runs-on: blacksmith-4vcpu-ubuntu-2404
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Validate release manifest
        uses: dagger/dagger-for-github@v8.4.1
        with:
          version: "0.20.3"
          dagger-flags: "--silent"
          call: validate-release
        timeout-minutes: 5

  trivy-scan:
    needs: [warm-engine]
    runs-on: blacksmith-4vcpu-ubuntu-2404
    permissions:
      contents: read
    continue-on-error: true
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Trivy security scan
        uses: dagger/dagger-for-github@v8.4.1
        with:
          version: "0.20.3"
          dagger-flags: "--silent"
          call: trivy-scan
        timeout-minutes: 10

  coverage:
    needs: [detect, warm-engine]
    if: needs.detect.outputs.has_backend == 'true'
    runs-on: blacksmith-4vcpu-ubuntu-2404
    permissions:
      contents: read
    continue-on-error: true
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Coverage report
        uses: dagger/dagger-for-github@v8.4.1
        with:
          version: "0.20.3"
          dagger-flags: "--silent"
          call: coverage
        timeout-minutes: 25

  # ── Quality gate: single required check for branch protection
  quality-gate:
    needs: [static-checks-backend, static-checks-frontend, build, test-backend, test-frontend, dead-code, release-validation]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Check all gates
        run: |
          results='${{ toJSON(needs.*.result) }}'
          if echo "$results" | grep -qE '"failure"|"cancelled"'; then
            echo "Quality gate failed"
            echo "$results"
            exit 1
          fi
          echo "All quality gates passed"

  # ── Trigger downstream build/deploy on master ──────────────
  trigger-build:
    needs: [quality-gate]
    if: github.ref == 'refs/heads/master'
    uses: ./.github/workflows/build.yml
    secrets: inherit
```

---

## Task 4: Update mise.toml CI tasks

**Files:**
- Modify: `mise.toml`

Replace the CI dagger task block. Add new tasks, remove `ci:dagger:test-matrix`:

```toml
[tasks."ci:dagger"]
description = "Run full quality gate via Dagger (same as CI)"
run = "dagger call -s quality-checks"

[tasks."ci:dagger:static:backend"]
description = "Run backend lint + type-check via Dagger"
run = "dagger call -s static-checks-backend"

[tasks."ci:dagger:static:frontend"]
description = "Run frontend lint + type-check via Dagger"
run = "dagger call -s static-checks-frontend"

[tasks."ci:dagger:lint"]
description = "Run lint checks via Dagger"
run = "dagger call -s lint"

[tasks."ci:dagger:type-check"]
description = "Run type-check via Dagger"
run = "dagger call -s type-check"

[tasks."ci:dagger:build"]
description = "Run build via Dagger"
run = "dagger call -s build"

[tasks."ci:dagger:test"]
description = "Run all tests via Dagger"
run = "dagger call -s test"

[tasks."ci:dagger:test:backend"]
description = "Run backend tests via Dagger (with live services + xdist)"
run = "dagger call -s test-backend"

[tasks."ci:dagger:test:frontend"]
description = "Run frontend tests via Dagger"
run = "dagger call -s test-frontend"

[tasks."ci:dagger:dead-code"]
description = "Run dead code detection via Dagger"
run = "dagger call -s dead-code"

[tasks."ci:dagger:trivy"]
description = "Run Trivy security scan via Dagger"
run = "dagger call -s trivy-scan"

[tasks."ci:dagger:coverage"]
description = "Run backend test coverage report via Dagger"
run = "dagger call -s coverage"

[tasks."ci:dagger:integration"]
description = "Run integration tests via Dagger (with live services)"
run = "dagger call -s integration-test"

[tasks."ci:dagger:service"]
description = "Run service-marked tests via Dagger (verbose)"
run = "dagger call -s service-test"

[tasks."ci:dagger:debug"]
description = "Run full quality gate with interactive debugging on failure"
run = "dagger call quality-checks --interactive"

[tasks."ci:dagger:verbose"]
description = "Run full quality gate with full TUI and debug logs"
run = "dagger call -vv quality-checks"
```

---

## Task 5: Add pytest-xdist dependency

**Files:**
- Modify: `apps/api/pyproject.toml`

Add `pytest-xdist` to the `[dependency-groups] dev` section.

---

## Task 6: Update workflows README

**Files:**
- Modify: `.github/workflows/README.md`

Update the mermaid diagram and per-workflow steps to reflect:
- `detect` → all jobs parallel → `quality-gate` → `trigger-build`
- Affected detection scopes and project list passthrough
- Coverage as non-blocking informational check

---

## Task 7: Verify

1. `dagger functions` — all new functions listed
2. `dagger call -s static-checks-backend` — runs successfully
3. `dagger call -s test-backend` — runs with xdist
4. `dagger call -s trivy-scan` — runs standalone
5. `dagger call -s quality-checks` — full gate still works

---

## Future: parallel Docker builds on master

On master push, `build.yml` waits for the full quality gate before starting Docker builds. These could run in parallel (Docker builds don't need test results). Add `push: branches: [master]` to `build.yml` triggers, with deploy gated on both quality-gate and Docker build completion via status checks. Separate PR.
