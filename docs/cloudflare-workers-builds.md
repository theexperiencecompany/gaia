# Cloudflare Workers Builds — Disable Auto-Deploy

> This repo deploys the hosted frontend (`apps/web`) **only** via GitHub Actions
> `.github/workflows/deploy-web.yml` → `cloudflare/wrangler-action@v3` → `wrangler deploy`.
> Cloudflare dashboard "Workers Builds" (git-connected auto-deploy) **must be disabled**
> or it will race/double-deploy on every `master` push and hide timing/failure from GitHub.

## Current state

- Worker name: `gaia` (`apps/web/wrangler.jsonc`)
- Account ID: `d65fe47d4d3b4f2725e87b91c772cbc3`
- Secrets: `CLOUDFLARE_API_TOKEN` (minimal: Workers Scripts Write + R2 Write/Read + Routes Write, expires 2027-08-21) + `CLOUDFLARE_ACCOUNT_ID`
- Workflow: `deploy-web.yml` builds `pnpm --filter ./apps/web cf:build`, uploads `.open-next`, deploys via `wrangler-action@v3` on `push: master` (paths `apps/web/**`), preview alias `pr-<n>` on PRs. Reports duration to `$GITHUB_STEP_SUMMARY`, fails visibly (`::error`), uses `environment: production` (requires approval if configured).

## Manual dashboard step (required, one-time)

1. Open https://dash.cloudflare.com → select account `d65fe47d…` → **Workers & Pages** → **gaia**.
2. Go to **Settings** → **Builds** (or **Settings → Build → Build configuration**, UI varies).
3. If a Git repository is shown as connected:
   - Click **Disconnect** / **Remove build integration**, **or**
   - Set **Build trigger** to **None** / toggle **Enable automatic builds** **OFF**.
4. **Save**. Worker should show **Builds: Disabled** or **No git repo connected**.
5. Verify: push to `master` should trigger only the GitHub `Deploy Web (Cloudflare)` workflow, not a dashboard build.

Docs: https://developers.cloudflare.com/workers/ci-cd/builds/

## API attempt (best-effort)

Dashboard Builds has no stable public API for all plans; the endpoint is often dashboard-only. The workflow's `preflight` step probes the API informationaly and never blocks the deploy. For a manual local attempt:

```bash
# Requires the same minimal token stored as CLOUDFLARE_API_TOKEN
export CLOUDFLARE_API_TOKEN="..."  # from 1Password / gh secret
export CLOUDFLARE_ACCOUNT_ID="d65fe47d4d3b4f2725e87b91c772cbc3"
bash scripts/ci/release.sh disable-cf-builds
```

The script tries known endpoints (`/workers/scripts/gaia`, `/workers/services/gaia`, etc.) and reports whether a Git connection is visible. If it reports a connected repo, perform the manual step above.

## Verification

```bash
# YAML validity
actionlint .github/workflows/deploy-web.yml
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-web.yml'))"

# Dry-run locally (requires token)
pnpm --filter ./apps/web cf:build
npx wrangler deploy --config apps/web/wrangler.jsonc --dry-run

# Trigger workflow
gh workflow run deploy-web.yml --ref improve-ci
gh run watch
```

## Why not dashboard Builds?

- Deploys are invisible in GitHub checks (no duration, no failure annotation, no `environment: production` gate).
- Double-deploy race on `master` pushes (dashboard + GitHub) can deploy different commits.
- This workflow makes deploys visible, timed, and auditable alongside backend Swarm deploys.
