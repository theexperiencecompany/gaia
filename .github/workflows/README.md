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

  START["Feature branch changes"]:::event --> PR_DEV["PR to develop"]:::event
  PR_DEV --> PR_TITLE["pr-naming-conventions.yml<br/>Validate PR title"]:::ci
  PR_DEV --> MAIN_PR_DEV["main.yml<br/>quality-checks (PR)"]:::ci
  MAIN_PR_DEV --> DEV_MERGED{"Merged to develop?"}:::decision
  DEV_MERGED -- "No" --> STOP1["Stop"]:::terminal
  DEV_MERGED -- "Yes" --> PR_MASTER["PR develop -> master"]:::event

  PR_MASTER --> PR_TITLE
  PR_MASTER --> MAIN_PR_MASTER["main.yml<br/>quality-checks (PR + master source policy)"]:::ci
  MAIN_PR_MASTER --> MASTER_MERGED{"Merged to master?"}:::decision
  MASTER_MERGED -- "No" --> STOP2["Stop"]:::terminal
  MASTER_MERGED -- "Yes" --> PUSH_MASTER["push -> master"]:::event

  PUSH_MASTER --> MAIN_PUSH["main.yml<br/>quality-checks (push)"]:::ci
  PUSH_MASTER --> RP["release-please.yml<br/>master-ref guard + run release-please"]:::release

  MAIN_PUSH --> MAIN_GATE{"Push checks pass?"}:::decision
  MAIN_GATE -- "No" --> MAIN_STOP["Stop"]:::terminal
  MAIN_GATE -- "Yes" --> BUILD_CALL["Call build.yml"]:::build

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
    B_WEB_GATE -- "Yes" --> B_WEB_PUB["Build/push gaia-web image"]:::build
    B_WEB_GATE -- "No" --> B_WEB_SKIP["Skip web image build"]:::terminal
    B_WEB_PUB --> B_WEB_DONE["docker-web complete"]:::build
    B_WEB_SKIP --> B_WEB_DONE

    B_REL_DONE --> PLAN["deployment-plan<br/>(needs docker-release + docker-web)"]:::decision
    B_WEB_DONE --> PLAN

    PLAN --> PLAN_BE{"backend_deploy == true?"}:::decision
    PLAN --> PLAN_FE{"frontend_deploy == true?"}:::decision
  end

  PLAN_BE -- "Yes" --> DEPLOY_BACKEND["trigger-deploy -> deploy.yml"]:::deploy
  PLAN_FE -- "Yes" --> DEPLOY_FRONTEND["trigger-web -> deploy-frontend.yml"]:::deploy

  subgraph BACKEND_DEPLOY["deploy.yml (backend + bots)"]
    direction TB
    DEPLOY_BACKEND --> D_AUTH["Auth to GCP + GHCR"]:::deploy
    D_AUTH --> D_SSH["SSH VM -> docker compose pull + up -d"]:::deploy
    D_SSH --> D_VERIFY["Verify services + cleanup + Discord notify"]:::deploy
  end

  subgraph FRONTEND_DEPLOY["deploy-frontend.yml (frontend)"]
    direction TB
    DEPLOY_FRONTEND --> F_SYNC["Sync master to private fork"]:::deploy
    F_SYNC --> F_VERCEL["Vercel auto-deploys or no-ops"]:::external
    F_VERCEL --> F_NOTIFY["Discord notify"]:::deploy
  end

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
  DESKTOP_BUILD --> DESKTOP_UPLOAD["Upload desktop assets to GitHub Release"]:::release

  RELEASE_EVT["release.published (desktop-v*)"]:::event --> DESKTOP_BUILD
```

## Per-Workflow Steps
### `.github/workflows/main.yml`
1. Enter from PRs targeting `develop`/`master` and pushes to `master`.
2. Run master promotion policy guard (`develop` or `release-please--*` to `master`).
3. Install toolchains and dependencies, validate release manifest, run affected quality checks.
4. If run is a successful push on `master`, call `build.yml`.

### `.github/workflows/build.yml`
1. Start two build lanes: `docker-release` and `docker-web`.
2. `docker-release`: detect affected backend/bot projects, release relevant images, optionally sync Discord commands.
3. `docker-web`: detect `web` changes and build/push web image only when affected.
4. `deployment-plan` waits for both lanes and computes `backend_deploy` / `frontend_deploy`.
5. Trigger `deploy.yml` and/or `deploy-frontend.yml` based on plan outputs.

### `.github/workflows/deploy.yml`
1. Authenticate to Google Cloud (WIF) and GHCR.
2. SSH into production VM, pull latest images, run `docker compose up -d`.
3. Verify expected services are running/healthy, then perform Docker cleanup.
4. Send deployment status to Discord.

### `.github/workflows/deploy-frontend.yml`
1. Sync `master` to the private fork used as Vercel source.
2. Vercel performs deploy/no-op based on its own change detection.
3. Send deployment status to Discord.

### `.github/workflows/release-please.yml`
1. Enforce `master` ref (manual runs on non-master fail fast).
2. Run Release Please for valid `master` executions.
3. Open/update release PRs and create component tags/releases.
4. If CLI release created, dispatch `publish-cli.yml` with resolved tag/version.
5. Desktop release tags (`desktop-v*`) later trigger `desktop-release.yml` via GitHub `release.published`.

### `.github/workflows/publish-cli.yml`
1. Accept release `tag` and `version` via workflow dispatch.
2. Verify tag/version/manifests and npm idempotency (`should_publish`).
3. If publish required: build `packages/cli` and `npm publish --provenance`.
4. If version already exists: skip safely.

### `.github/workflows/desktop-release.yml`
1. Trigger on `release.published`, then continue only for `desktop-v*` tags.
2. Set desktop package version from release tag.
3. Build installers across macOS, Windows, Linux.
4. Upload artifacts to the matching GitHub Release.

### `.github/workflows/pr-naming-conventions.yml`
1. Trigger on PR open/edit/synchronize.
2. Validate PR title against configured semantic type list.

## File Map
- `.github/workflows/main.yml`: CI quality gate and master promotion policy.
- `.github/workflows/build.yml`: image build/release lanes, deploy planning, deploy triggers.
- `.github/workflows/deploy.yml`: production backend and bot deployment to GCP VM.
- `.github/workflows/deploy-frontend.yml`: frontend sync path for Vercel source repository.
- `.github/workflows/release-please.yml`: release PR/tag automation and CLI publish dispatch.
- `.github/workflows/publish-cli.yml`: CLI package validation/build/publish workflow.
- `.github/workflows/desktop-release.yml`: desktop installer build and release-asset upload.
- `.github/workflows/pr-naming-conventions.yml`: PR title convention enforcement.
