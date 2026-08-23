# CI and Deployment Flow

> IMPORTANT FOR AGENTS: If any workflow trigger, job dependency, deploy condition, workflow dispatch wiring, or release path changes in `.github/workflows/`, update this file in the same PR.

## End-to-End Flow Diagram
```mermaid
flowchart TD
  classDef event fill:#F8FAFC,stroke:#64748B,color:#0F172A,stroke-width:1px;
  classDef ci fill:#E0F2FE,stroke:#0284C7,color:#0C4A6E,stroke-width:1.2px;
  classDef build fill:#ECFDF5,stroke:#10B981,color:#064E3B,stroke-width:1.2px;
  classDef decision fill:#FEF3C7,stroke:#D97706,color:#78350F,stroke-width:1.2px;
  classDef deploy fill:#EEF2FF,stroke:#6366F1,color:#312E81,stroke-width:1.2px;
  classDef release fill:#FFF7ED,stroke:#F97316,color:#7C2D12,stroke-width:1.2px;
  classDef external fill:#F0FDF4,stroke:#22C55E,color:#14532D,stroke-width:1.2px;
  classDef terminal fill:#F8FAFC,stroke:#94A3B8,color:#334155,stroke-width:1px;

  START["Feature branch changes<br/>(humans, contributors, bots)"]:::event --> PR_MASTER["PR to master"]:::event
  PR_MASTER --> PR_TITLE["pr-naming-conventions.yml<br/>Validate PR title"]:::ci
  PR_MASTER --> MAIN_PR["main.yml + code-quality.yml<br/>quality gates (PR)"]:::ci
  MAIN_PR --> MASTER_MERGED{"Merged to master?"}:::decision
  MASTER_MERGED -- "No" --> STOP2["Stop"]:::terminal
  MASTER_MERGED -- "Yes" --> PUSH_MASTER["push -> master"]:::event

  PUSH_MASTER --> MAIN_PUSH["main.yml<br/>quality-checks (push)"]:::ci
  PUSH_MASTER --> RP["release-please.yml<br/>master-ref guard + run release-please"]:::release

  PUSH_MASTER --> BUILD_CALL["build-images -> build.yml phase=build<br/>(images build+publish, parallel to the checks;<br/>immutable :sha tags only — never :latest)"]:::build
  MAIN_PUSH --> MAIN_GATE{"quality-gate result"}:::decision
  MAIN_GATE -- "any result" --> DEPLOY_PHASE["trigger-build -> build.yml phase=deploy<br/>(gate_result + build phase outputs)"]:::build
  DEPLOY_PHASE --> PLAN
  DEPLOY_PHASE --> PROMOTE["promote-latest (gate passed):<br/>re-point gaia-web / gaia-grafana :latest"]:::build

  subgraph BUILD_PIPELINE["build.yml"]
    direction TB
    BUILD_CALL --> B_REL["docker-release<br/>detect api/bots affected"]:::build
    B_REL --> B_REL_GATE{"api/bots affected?"}:::decision
    B_REL_GATE -- "Yes" --> B_REL_PUB["Release API/Bot images to GHCR"]:::build
    B_REL_GATE -- "No" --> B_REL_SKIP["Skip API/Bot image release"]:::terminal
    B_REL_PUB --> B_REL_DONE["docker-release complete"]:::build
    B_REL_SKIP --> B_REL_DONE

    BUILD_CALL --> B_WEB["docker-web<br/>detect web affected"]:::build
    B_WEB --> B_WEB_GATE{"web affected?"}:::decision
    B_WEB_GATE -- "Yes" --> B_WEB_PUB["Build/push gaia-web image<br/>(self-host package, not a deploy)"]:::build
    B_WEB_GATE -- "No" --> B_WEB_SKIP["Skip web image build"]:::terminal
    B_WEB_PUB --> B_WEB_DONE["docker-web complete"]:::build
    B_WEB_SKIP --> B_WEB_DONE

    B_REL_DONE --> PLAN["deployment-plan (if: always())<br/>needs docker-release + docker-grafana<br/>runs even if a lane failed/cancelled"]:::decision

    PLAN --> PLAN_BE{"docker-release succeeded<br/>AND api/bots affected?"}:::decision
    PLAN --> PLAN_ORPHAN{"backend images published but<br/>the deploy did not run?"}:::decision
  end

  PLAN_BE -- "Yes" --> DEPLOY_BACKEND["trigger-deploy -> deploy-swarm-prod.yml"]:::deploy
  PLAN_ORPHAN -- "Yes" --> NOTIFY_ORPHAN["notify-publish-without-deploy<br/>Discord alert + gh workflow run<br/>build.yml -f deployment_mode=deploy remedy"]:::deploy

  subgraph BACKEND_DEPLOY["deploy-swarm-prod.yml (Swarm app stack)"]
    direction TB
    DEPLOY_BACKEND --> D_AUTH["SSH key setup + GHCR login"]:::deploy
    D_AUTH --> D_CTX["Create Docker context over SSH"]:::deploy
    D_CTX --> D_STACK["docker stack deploy gaia-prod<br/>pinned to immutable tags (or :latest fallback)"]:::deploy
    D_STACK --> D_RETAG["after convergence:<br/>re-point :latest at deployed tags"]:::deploy
    D_RETAG --> D_NOTIFY["Loki annotation + Discord notify"]:::deploy
  end

  RP --> RP_ANY{"releases_created == true?"}:::decision
  RP_ANY -- "Yes" --> RP_PRESERVE["preserve-desktop-latest<br/>gh release edit desktop-v* --latest"]:::release
  RP_ANY -- "No" --> RP_STOP["No releases, stop"]:::terminal

  RP --> RP_CLI{"CLI release created?"}:::decision
  RP_CLI -- "Yes" --> RP_DISPATCH["Dispatch publish-cli.yml"]:::release
  RP_CLI -- "No" --> RP_CLI_STOP["No CLI publish"]:::terminal

  RP_DISPATCH --> CLI_VERIFY["publish-cli.yml<br/>verify + publish/skip"]:::release
  CLI_VERIFY --> CLI_GATE{"should_publish == true?"}:::decision
  CLI_GATE -- "Yes" --> CLI_PUBLISH["Build + npm publish @heygaia/cli"]:::release
  CLI_GATE -- "No" --> CLI_SKIP["Skip publish (already exists)"]:::terminal

  RP --> RP_DESKTOP{"Desktop release created?"}:::decision
  RP_DESKTOP -- "Yes" --> RP_DESKTOP_PUBLISH["Publish desktop-v* release"]:::release
  RP_DESKTOP_PUBLISH --> DESKTOP_BUILD["desktop-release.yml<br/>build installers"]:::release
  RP_DESKTOP -- "No" --> RP_DESKTOP_SKIP["No desktop release publish"]:::terminal
  DESKTOP_BUILD --> DESKTOP_UPLOAD["Upload assets + mark desktop-v* as Latest"]:::release

  RELEASE_EVT["release.published (desktop-v*)"]:::event --> DESKTOP_BUILD
```

## Per-Workflow Steps
### `.github/workflows/main.yml`
1. Enter from PRs targeting `master` and pushes to `master`.
2. `detect`: validate the release manifest and compute Nx-affected Python/TypeScript project lists (fail-loud — an nx error fails the job rather than silently skipping every lane).
3. Correctness lanes, each gated on the affected lists: `build` (TS builds), `test-typescript` (vitest via Nx), `test-device-bridge` (the Node-driven e2e, its own lane so the shards can skip Node), and `test-python` — pytest sharded 6-way via pytest-split, run directly on the runner against live PostgreSQL/Redis/MongoDB/ChromaDB/RabbitMQ containers started by `scripts/ci/start-test-services.sh` (same images/credentials as the local `dagger call test-python` harness). The shards run `-p no:randomly` so collection order is identical everywhere and pytest-split's positional slices stay disjoint — per-shard random seeds left a third of the suite unrun. Each shard measures coverage with `--cov-fail-under=0`; `test-python-coverage` asserts the shards partitioned the suite (`scripts/ci/assert_shard_partition.py`), combines the shard files and enforces the repo gate (70% temporary, target 80%) plus diff-cover 90%, schemathesis, and gaia-shared tests. Static checks (ruff, mypy, Biome, tsc, custom AST lints, dead code) intentionally do NOT run here — they are enforced lanes in `code-quality.yml`.
4. `quality-gate` (branch protection target) fails on any failed/cancelled lane; skipped lanes pass.
5. On `master` pushes only, `build.yml` is called in two phases: `build-images` (`phase=build`, needs only `detect`) builds and publishes the Docker images in parallel with the test lanes — immutable `:<sha>`/version tags only, never `:latest`, and its deploy-side jobs (`deployment-plan`, orphan alert, `trigger-deploy`, `promote-latest`) are guarded off with `inputs.phase != 'build'`; then `trigger-build` (`phase=deploy`, needs `quality-gate` + `build-images`, `if: always()` so a failed gate still reaches the orphan guardrail) calls `build.yml` again with `gate_result` and the build phase's outputs to run the deploy plan, `:latest` promotion, and the Swarm deploy.

### `.github/workflows/code-quality.yml`
1. Enter from PRs targeting `master`, pushes to `master`, and manual dispatch.
2. `changes`: one cheap no-toolchain job detects which languages a PR touches; Python lanes and TypeScript lanes are skipped wholesale when their language is untouched (on push/dispatch everything runs).
3. Twenty hygiene lanes (Biome, deps, circular, file-size, types-location, components-per-file, jscpd, type-coverage, package hygiene, tsc, `python-static` = ruff + custom AST lints + xenon + interrogate + bandit + pip-audit in one job, mypy, evlog-map observability score, wide-event cross-runtime conformance, knip/vulture dead code), each self-scoping to changed files via `scripts/ci/changed-files.sh`. The Python static tools share one lane because each is seconds of work behind ~40s of runner boot + checkout + uv install; every tool step is `continue-on-error` with an aggregating verdict, so one red tool still does not hide the others. The `wide-event-conformance` lane runs the Python and TypeScript logging stacks for real and diffs the log shapes they actually emit against each other and against `scripts/ci/wide-event-conformance/contract.json`, so the two halves cannot drift apart. The observability lane (`tools/evlog_map`, enforced) posts the full-repo score to the job summary and fails PRs whose changed files score below the same files at the merge-base.

4. `Quality gate (required)` (the single required status check) fails the merge if any lane is neither `success` nor `skipped`; a lane skipped by `changes` counts as passing, but a failed `changes` job fails the gate. All lanes are enforced — there is no informational tier.

### `.github/workflows/build.yml`
0. Phase-aware entrypoints: called from main.yml as `phase=build` (image lanes only, pre-gate, immutable tags only) and `phase=deploy` (deploy plan + `:latest` promotion + Swarm deploy, fed by the build phase's outputs passed back as inputs). Manual `workflow_dispatch` / `repository_dispatch` leave `phase` empty and run the legacy single-phase flow unchanged. No job may move `:latest` in `phase=build` — the quality gate has not reported yet.
1. Start three build lanes: `docker-release`, `docker-web`, `docker-grafana` (skipped in `phase=deploy`).
2. `docker-release`: detect affected backend/bot projects, publish images to GHCR, optionally sync Discord commands. Records `images_published` right after its push steps (before Discord command sync), so a later, unrelated step failure never misreports a real publish as "nothing published". After the release steps, `scripts/ci/resolve-image-tags.sh` resolves the immutable per-commit tags nx pushed (production versionScheme `YYMM.DD.<shortsha>`, read from the local image store, never recomputed) and guarantees they exist in GHCR (pushing them if nx skipped publishing), emitting `apps_tag` (gaia + gaia-voice-agent) and `bots_tag` (the five bot images) — empty when that group wasn't released this run. Backend `:latest` is never pushed at build time: it is re-pointed exclusively by the deploy's `retag-latest-alias.sh` after convergence (":latest == deployed").
3. `docker-web`: detect `web` changes and build/push the `gaia-web` image only when affected. This is a package publish for self-host users (`docker-compose.selfhost.yml`), not a production deploy — the hosted frontend deploys via `.github/workflows/deploy-web.yml` → Cloudflare Workers (`wrangler deploy`) on every master push. In `phase=build` it pushes only `:<sha>`; `promote-latest` re-points `:latest` after the gate passes. Layer cache lives in GHCR (`gaia-web:buildcache`, zstd) — the `type=gha` export measured 449s of a 951s build.
4. `docker-grafana`: builds/pushes the Grafana image unconditionally every run (tiny COPY layer over the upstream image). Not part of orphan detection — it has no "affected" concept. Same `:latest` rule: `:<sha>` only in `phase=build`; `:latest` moves via the deploy retag or `promote-latest`.
5. `deployment-plan` runs with `if: always()` — it is never skipped by a lane failing or being cancelled — and needs `docker-release` + `docker-grafana` purely for sequencing (deploy planning must not race ahead of the build lanes). It evaluates `docker-release`'s `.result` plus backend affected-detection (`docker-release.outputs.api_affected`/`bots_affected`) via `scripts/ci/compute-deploy-plan.sh`:
   - `backend_deploy` is `true` only when `docker-release` succeeded AND api/bots affected. A failed/cancelled `docker-release` never deploys; `docker-web`'s result never gates it — the hosted frontend has already shipped itself either way.
   - `backend_orphaned` flags when backend images actually published to GHCR (`images_published` — publish evidence, not the job result) but the deploy did not run this time (lane failure, cancellation, or the plan deciding not to deploy). Scoped to `master` only, and a deploy the operator deliberately excluded via `deployment_mode=none` is never flagged — an operator choice is not drift.
   - Manual `workflow_dispatch` mode `deploy` bypasses affected-detection AND lane-result gating — the intended one-command remedy for drift: `gh workflow run build.yml --ref master -f deployment_mode=deploy` redeploys whatever is currently tagged `:latest` in GHCR regardless of what this run's own build lanes did. Manual `auto` behaves like an automatic push.
6. `notify-publish-without-deploy` fires a Discord alert when `backend_orphaned` is set, naming the published-but-undeployed images and the `gh workflow run` remedy above. All deploy-pipeline Discord sends go through `scripts/ci/notify-discord.sh` (single webhook embed; the previous appleboy action 400'd on messages over 256 chars and fragmented comma-containing ones), with `continue-on-error` on the send step only — the message is fully logged in the run either way, and a dropped webhook must not turn an otherwise-green run red.
7. Trigger `deploy-swarm-prod.yml` when `backend_deploy` is true. `trigger-deploy` passes the immutable tags through (`apps_image_tag` / `bots_image_tag` from `docker-release`, `grafana_image_tag` = the commit sha when `docker-grafana` succeeded); empty tags mean the deploy falls back to `:latest` (the manual-mode drift remedy keeps exactly its old semantics).
8. `promote-latest` (`phase=deploy`, gate passed): `scripts/ci/promote-latest.sh` re-points `:latest` for the two repos the Swarm deploy does not own — `gaia-web` (package publish) and `gaia-grafana` when no backend deploy runs to retag it — via registry-side `imagetools create`. Backend repos are deliberately absent (deploy retag owns them).

### `.github/workflows/deploy-swarm-prod.yml`
1. Install SSH private key from `PROD_VM_SSH_KEY` via the `setup-swarm-context` composite action and log in to GHCR.
2. Create Docker context pointing at the Hetzner VM over SSH.
3. Run `docker --context prod stack deploy --with-registry-auth` for the app stack (`gaia-prod`), exporting the `apps_image_tag` / `bots_image_tag` / `grafana_image_tag` inputs as `GAIA_IMAGE_TAG` / `GAIA_BOTS_IMAGE_TAG` / `GAIA_GRAFANA_IMAGE_TAG` so the stack is pinned to the exact images this run verified. Empty inputs fall through to the compose file's `${VAR:-latest}` defaults — the pre-parameterization behavior, used by manual dispatches that just want to redeploy `:latest`.
   Swarm handles rolling update; the workflow polls `gaia-backend`, `arq_worker`, and `voice-agent-worker` for convergence and fails on auto-rollback.
4. Only after convergence succeeds, `scripts/ci/retag-latest-alias.sh` re-points each deployed repo's `:latest` at the deployed tag registry-side (`docker buildx imagetools create`, no layer transfer) — `:latest` is a deploy-time alias meaning "what prod runs", not "what was last built". A failed deploy does not move `:latest`.
5. Push a deploy annotation to Loki (including the deployed tags) and send status to Discord via `scripts/ci/notify-discord.sh`.
6. Manual `workflow_dispatch` supports `action=rollback` with `rollback_mode=last` (Docker service rollback) or `rollback_mode=digest` (redeploy pinned image). After a successful rollback, the same retag script re-points `:latest` at the images the rolled-back services now run (digest mode: the pinned gaia ref; last mode: each rolled-back service's restored image spec), so the alias keeps tracking production through rollbacks too.

### `.github/workflows/deploy-web.yml`
1. Triggers on `push: master` (paths `apps/web/**`, `libs/shared/ts/**`, `wrangler.jsonc`, `open-next.config.ts`, `next.config.mjs`) and `pull_request: master` (same paths) plus manual `workflow_dispatch`.
2. `build`: checkout → `setup-node-pnpm` + `restore-nextjs-cache` + `.nx/cache` → `preflight` (best-effort Workers Builds API probe, never blocks) → `pnpm --filter ./apps/web cf:build` timed via `time` → upload `apps/web/.open-next` artifact → report duration to `$GITHUB_STEP_SUMMARY` (`::notice`) and fail visibly (`::error` + summary on failure). Concurrency `deploy-web-${{ github.ref }}` with `cancel-in-progress: false` so rapid master merges queue rather than drop the deploy.
3. `deploy-prod`: gated `if: github.ref == 'refs/heads/master' && github.event_name != 'pull_request'`, `environment: production`, downloads artifact, verifies `worker.js` exists, then `cloudflare/wrangler-action@v3` with `command: deploy --config apps/web/wrangler.jsonc`. Reports duration and success URL; fails visibly with token-scope hint on error.
4. `preview`: gated `if: github.event_name == 'pull_request'`, uploads preview version via `command: versions upload --preview-alias pr-${{ github.event.number }} --config apps/web/wrangler.jsonc`, reports duration, comments PR with expected preview URL. Requires Workers Versions / Gradual Rollouts enabled; `preview_urls: false` in `wrangler.jsonc` means the alias URL is only reachable if routing is configured.

> Workers Builds (dashboard git auto-deploy) must be **disabled** — see `docs/cloudflare-workers-builds.md` and `scripts/ci/disable-cf-builds.sh`. The workflow header comments the exact dashboard steps and the `preflight` API probe.

### `.github/workflows/release-please.yml`
1. Enforce `master` ref (manual runs on non-master fail fast).
2. Run Release Please for valid `master` executions.
3. Open/update release PRs and create component tags/releases.
4. If any releases were created (`releases_created`), run `preserve-desktop-latest`: marks the most recent `desktop-v*` release as GitHub's "Latest". This is required because electron-updater resolves updates via `/releases/latest`, and other component releases (api, web, cli) would otherwise steal the Latest flag from the desktop release, breaking auto-updates.
5. If CLI release created, dispatch `publish-cli.yml` with resolved tag/version.
6. Desktop release tags (`desktop-v*`) later trigger `desktop-release.yml` via GitHub `release.published`.

### `.github/workflows/publish-cli.yml`
1. Accept release `tag` and `version` via workflow dispatch.
2. Verify tag/version/manifests and npm idempotency (`should_publish`).
3. If publish required: build `packages/cli` and `npm publish --provenance`.
4. If version already exists: skip safely.

### `.github/workflows/desktop-release.yml`
1. Trigger on `release.published`, then continue only for `desktop-v*` tags.
2. Set desktop package version from release tag.
3. Build installers across macOS, Windows, Linux in parallel. electron-builder runs with `--publish never` to prevent it from auto-creating a separate `v*` GitHub release (it still uses `GH_TOKEN` for downloading Electron binaries without rate-limit issues).
4. Upload artifacts to the matching GitHub Release and mark it as GitHub's "Latest" (`make_latest: true`) so electron-updater can find `latest-*.yml` via `/releases/latest`.

### `.github/workflows/pr-naming-conventions.yml`
1. Trigger on PR open/edit/synchronize.
2. Validate PR title against configured semantic type list.

## File Map
- `.github/workflows/main.yml`: CI correctness gate (build + tests). Python tests run runner-native against live service containers.
- `.github/workflows/code-quality.yml`: code-hygiene lanes (lint/type/dead-code/complexity/security) behind the ratcheted `Quality gate (required)` check.
- `.github/workflows/build.yml`: Docker image build/publish via Dagger, deploy planning, and deploy triggers.
- `.github/workflows/deploy-swarm-prod.yml`: production backend deploy and rollback via Docker Swarm stack on Hetzner VM.
- `.github/workflows/deploy-web.yml`: Cloudflare Workers frontend deploy — builds `pnpm --filter ./apps/web cf:build`, deploys via `cloudflare/wrangler-action@v3` on `push: master` (paths `apps/web/**`), preview alias `pr-<n>` on PRs. Reports duration, fails visibly, uses `environment: production`. Workers Builds auto-deploy must be disabled (see `docs/cloudflare-workers-builds.md`).
- `.github/workflows/release-please.yml`: release PR/tag automation and CLI publish dispatch.
- `.github/workflows/publish-cli.yml`: CLI package validation/build/publish workflow.
- `.github/workflows/desktop-release.yml`: desktop installer build and release-asset upload.
- `.github/workflows/pr-naming-conventions.yml`: PR title convention enforcement.
