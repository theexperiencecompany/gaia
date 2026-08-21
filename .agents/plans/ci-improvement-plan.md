# CI Improvement Plan — Gaia

## Context
Deep analysis of 100+ CI runs showed 31% cancelled, 16% failed, PR gate 11.5m (10m is test-python), 15-20x duplicated pnpm/uv installs, no .nx cache, no Docker layer cache, master cancel races, invisible Cloudflare deploy.

User wants: all 14 fixes in this run, Cloudflare via GitHub, master merges that coalesce + deploy final, charts comparing before/after, CLAUDE.md learnings, end-to-end verified manually.

## Goals
- PR gate 11.5m → 6.5m, master deploy 18m → 9m
- 30 runners/PR → 12, 0% lost deploys
- Cloudflare deploy visible in GitHub with timing/failure
- Zero regressions, verified by manual workflow runs

## Non-Goals
- Nx Cloud remote (cost). Use local `actions/cache` for .nx/cache.

## Decisions
- Master coalescing: QC/CQ keep `cancel-in-progress: true` on `refs/heads/master` so 5 rapid merges cancel to 1 final verification. Build.yml stays `cancel-in-progress: false` so a running deploy never dies. Final SHA's `nx-set-shas` base covers all 5 merges.
- Minimal CF token: `Workers Scripts Write + R2 Write/Read + Routes Write` on `d65fe47d...`, expires 2027-08-21, stored as `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID`. All-access token revoked intent but kept for now; don't log values.
- Workers Builds: already `version_upload` only (no git trigger found). Ensure dashboard Settings → Builds → Disconnected.

## Workstreams (10 agents, 3 waves)
Wave 1 (parallel, no deps): A1 caches, A2 Nx inputs, A4 Docker cache, A6 Cloudflare workflow, A7 DX summaries
Wave 2 (after A1+A2): A3 test sharding, A5 concurrency master, A8 mutation+trivy cron, A9 next cache
Wave 3: A10 verification + charts

### A1 — Caches (owns)
- Add `actions/cache@v4` for `.nx/cache` (key: `nx-${os}-${hashFiles(pnpm-lock.yaml,nx.json,**/project.json)}-${hashFiles(apps/**,libs/**)}`) restore at job start, save at end (if not hit).
- Collapse pnpm install: one `setup` job that does `pnpm install` + `uv sync`, saves `node_modules` via cache key `pnpm-store-${hashFiles(pnpm-lock.yaml)}`, downstreams `needs: setup`.
- Same for `~/.cache/uv` via `setup-uv` enable-cache (already) but ensure `prune-cache: true`.
- Files: .github/actions/setup-node-pnpm/action.yml, .github/actions/setup-python-test-env/action.yml, .github/workflows/main.yml, .github/workflows/code-quality.yml

### A2 — Nx correctness
- Unify affected: single `detect` job exports `affected` list, CQ's `changes` reuses it (or calls `nx show projects --affected` with same base). Remove `changed-files.sh` grep duplication.
- Convert CQ lanes to `nx affected -t lint type-check` where `cache: true`. Keep raw `ruff`/`biome` only if needed but wrap via `nx run-many`.
- Fix `nx.json` inputs: `api:build` should include `pyproject.toml, uv.lock, libs/shared/py/**`.
- Files: nx.json, .github/workflows/code-quality.yml, .github/workflows/main.yml

### A3 — Test sharding
- Split `test-python` into 2 shards using `pytest-split` or manual `--splits 2 --group`.
- Make `test-fast` depend on `test-python`? Or keep parallel but make `test-fast` a collect-only budget probe.
- Files: .github/workflows/main.yml, apps/api/pytest.ini or pyproject.toml

### A4 — Docker cache
- Add `cache-from: type=gha` + `cache-to: type=gha,mode=max` to every `build-push-action` and `docker build` via `nx docker:build`.
- Parallelize `api` vs `voice-agent` builds (matrix).
- Files: .github/workflows/build.yml, apps/api/Dockerfile, apps/web/Dockerfile, apps/voice-agent/Dockerfile

### A5 — Concurrency master
- Set QC/CQ: `concurrency: group: ci-${workflow}-${ref}, cancel-in-progress: ${{ github.event_name == 'pull_request' || github.ref == 'refs/heads/master' }}` → true for PR and master push, false for deploy jobs.
- Ensure `build.yml` stays `cancel-in-progress: false`.
- Document tradeoff in CLAUDE.md.

### A6 — Cloudflare CI
- New `.github/workflows/deploy-web.yml`: build `pnpm --filter web cf:build`, deploy via `cloudflare/wrangler-action@v3` with `CLOUDFLARE_API_TOKEN/ACCOUNT_ID`, environments.
- PR preview `pr-${number}`.
- Disable dashboard auto-build (manual note + API attempt).

### A7 — DX / logs
- Add `::error file=..,line=` annotations, `>> $GITHUB_STEP_SUMMARY` per lane, collapse pnpm install logs via `::group::`.
- Files: .github/workflows/code-quality.yml, .github/workflows/main.yml, tools/lints/run.py

### A8 — Mutation + trivy
- Restore mutation matrix to 2-3 runners, skip `<5 lines` modules.
- Move trivy/pip-audit to `.github/workflows/security-cron.yml` weekly.
- Files: .github/workflows/code-quality.yml, .github/workflows/security-cron.yml, scripts/ci/mutation-check.sh

### A9 — Next cache
- Fix `restore-nextjs-cache` key to hash only `pnpm-lock.yaml + next.config.*`, not all src.
- Files: .github/actions/restore-nextjs-cache/action.yml

### A10 — Verify + charts
- Run 3 manual `gh workflow run` on feature branch, capture timings, generate charts (Mermaid + PNG via chart.js or simple HTML).
- PR includes `docs/ci-metrics.md` or `.agents/ci-report.html` with before/after bars.
- Verify CF deploy via wrangler dry-run.

## Cloudflare Workflow Sketch
```yaml
name: Deploy Web (Cloudflare)
on:
  push:
    branches: [master]
    paths: ['apps/web/**','libs/shared/ts/**','apps/web/wrangler.jsonc','apps/web/open-next.config.ts']
  pull_request:
    paths: ['apps/web/**']
  workflow_dispatch:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: ./.github/actions/setup-node-pnpm
      - uses: ./.github/actions/restore-nextjs-cache
      - run: pnpm --filter web cf:build
      - uses: actions/upload-artifact@v4
        with: {name: open-next, path: apps/web/.open-next}
  deploy-prod:
    needs: build
    if: github.ref == 'refs/heads/master'
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v7
      - uses: actions/download-artifact@v4
      - uses: cloudflare/wrangler-action@v3
        with: {apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}, accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}, command: deploy --config apps/web/wrangler.jsonc}
```

## Risks
- Cache poisoning: use `hashFiles` keys, never `restore-keys` without hash.
- Token scope too narrow → deploy fails with 403; we included R2+Routes, verify with dry run.
- Master coalescing hides intermediate failures; mitigate by ensuring final SHA verifies union (+ `nx-set-shas` base = last successful master).
- Docker gha cache 10GB limit; use `mode=max` + registry fallback.

## Verification Plan
1. `gh workflow run main.yml --ref fix/ci-improve` → check timings vs baseline (11.5m → 6.5m)
2. `gh workflow run deploy-web.yml --ref fix/ci-improve` → check CF deploy log + timing
3. `gh run list --limit 20` → no lost deploys, cancelled only on master coalesce
4. Manual `wrangler deploy --dry-run` with minimal token.

## Rollout
- Branch `fix/ci-improve-all-14` from master, 10 agents push in 3 waves, open PR with charts, merge after green.
