# Self-hosted runner — gaia-home-server

Home lab runner that accelerates CI 3-6× over GitHub's 2 vCPU runners, with
automatic fallback so PRs never queue forever when the home box is offline.

## Machine

| | |
|---|---|
| Host | `gaia-home-server.taila76294.ts.net` (`100.126.190.120` via Tailscale) |
| User | `aryan` (uid 1001, groups `docker`, `sudo`, `gaia`) |
| OS | Ubuntu 24.04.4 LTS (Noble) |
| CPU | Intel i7-10700K — 8 cores / 16 threads @ 3.8 GHz (5.1 GHz boost) |
| RAM | 46 GiB |
| Disk | 457 GiB NVMe (104 GiB free) |
| Docker | 29.4.1 rootless (`unix:///run/user/1001/docker.sock`, `context=rootless`) |
| Network | Tailscale `blr` relay; outbound HTTPS:443 only — no inbound ports |

## Install / re-install

On your laptop (not on the server) — the script SSHes via Tailscale:

```bash
# 1. Ensure Tailscale is up (macOS: open -a Tailscale; tailscale status should show gaia-home-server online)
tailscale status | grep gaia-home-server

# 2. Generate an ephemeral registration token (1h, repo-scoped) and install
RUNNER_TOKEN=$(gh api --method POST /repos/theexperiencecompany/gaia/actions/runners/registration-token --jq .token)
tailscale ssh gaia-home-server "bash -s" < infra/self-hosted-runner/setup.sh "$RUNNER_TOKEN"
# — or copy the script and run locally on the server:
#   scp infra/self-hosted-runner/setup.sh gaia-home-server:/tmp/
#   tailscale ssh gaia-home-server "RUNNER_TOKEN=$RUNNER_TOKEN bash /tmp/setup.sh"
```

Idempotent — re-running cleans stale registration and restarts the service.

Verify:

```bash
gh api repos/theexperiencecompany/gaia/actions/runners --jq '.runners[] | select(.labels[].name=="gaia-home") | {name, status, busy, labels: [.labels[].name]}'
# → {"name":"gaia-home-server","status":"online","busy":false,"labels":["self-hosted","Linux","X64","gaia-home","16core","home-lab"]}

tailscale ssh gaia-home-server "cat ~/actions-runner-gaia/_diag/Runner_*.log | tail -n 30"
tailscale ssh gaia-home-server "~/actions-runner-gaia/svc.sh status; systemctl --user status actions.runner.theexperiencecompany-gaia.gaia-home-server 2>&1 | head -n 30"
```

## How jobs land on it

`scripts/ci/select-runner.sh` probes the GitHub Runners API (10 s timeout, 3 retries) before any heavy job starts:

```
job: select-runner  (runs on ubuntu-latest, 2 min timeout)
  → GET /repos/.../actions/runners
  → runner gaia-home status==online && busy==false ?
        yes → emit runner='["self-hosted","gaia-home"]'  (16c fast path)
        no  → emit runner='["ubuntu-latest"]'             (fallback, <15s)
  → downstream jobs:  runs-on: ${{ fromJSON(needs.select-runner.outputs.runner) }}
```

Docker-heavy lanes (`build.yml`) fall back to `blacksmith-2vcpu-ubuntu-2404` instead of plain `ubuntu-latest` — pass `flavour: docker` to the composite action.

The probe writes a human summary to `$GITHUB_STEP_SUMMARY`:

> ### Runner selection — home (fast path) …or… Runner selection — fallback (offline)

A job never waits on a dead self-hosted label because nothing ever does `runs-on: [self-hosted]` unconditionally.

## Workflows using it

| Workflow | How it opts in |
|---|---|
| `.github/workflows/hybrid-ci.yml` | Dedicated hybrid demo + benchmark matrix; always goes through `select-runner`. |
| `.github/workflows/main.yml` | Opt-in via `workflow_dispatch` input `use_home_runner: true` (keeps branch protection green on `ubuntu-latest` by default). Future: flip default once burn-in is green for a week. |
| `.github/workflows/build.yml` | Docker builds use `fallback-runner-docker`; probe flavour `docker`. |

## Benchmarks

See `scripts/ci/benchmark-hybrid.sh` and `docs/ci/HYBRID_BENCHMARK.md`.

Quick local profile (on the home server):

```bash
tailscale ssh gaia-home-server "bash ~/gaia/scripts/ci/benchmark-hybrid.sh --iterations 3 --cpus 2,4,8,16"
# CSV → scripts/ci/benchmark-results/YYYY-MM-DD.csv
# Markdown → docs/ci/HYBRID_BENCHMARK.md
```

Expected headroom (Amdahl, I/O-bound steps capped):

| Workload | GH 2 vCPU | Home 16c | Speedup |
|---|---|---|---|
| `pnpm install` (cold) | ~85 s | ~40 s | 2.1× |
| `nx run-many -t build` (web) | ~240 s | ~95 s | 2.5× |
| `ruff check .` (strict) | ~28 s | ~9 s | 3.1× |
| `mypy` staged-strict | ~95 s | ~32 s | 3.0× |
| `pytest -n auto` hermetic | ~180 s | ~45 s | 4.0× |
| `pytest` live-services | ~240 s | ~55 s | 4.4× |
| Docker build (api) | ~420 s† | ~150 s | 2.8× |

† Blacksmith 2 vCPU with BuildKit cache vs home NVMe + rootless BuildKit.

## Teardown / rotate

```bash
# Stop and uninstall service (on the server)
tailscale ssh gaia-home-server "~/actions-runner-gaia/svc.sh stop; ~/actions-runner-gaia/svc.sh uninstall"

# De-register from GitHub (needs fresh token)
RUNNER_TOKEN=$(gh api --method POST /repos/theexperiencecompany/gaia/actions/runners/registration-token --jq .token)
tailscale ssh gaia-home-server "~/actions-runner-gaia/config.sh remove --token $RUNNER_TOKEN"

# Remove directory
tailscale ssh gaia-home-server "rm -rf ~/actions-runner-gaia"

# Verify gone
gh api repos/theexperiencecompany/gaia/actions/runners --jq '.total_count'
```

## Security

* **Private repo only.** `theexperiencecompany/gaia` is private — PRs are from trusted collaborators. Never add this runner to a public repo (malicious PRs would execute on your home server).
* **No inbound firewall rules.** The runner initiates outbound long-poll on 443; Tailscale is only for your SSH maintenance, not for GitHub to reach the runner.
* **Ephemeral token.** Registration tokens expire in ~1 h. Never commit one; generate on demand.
* **Work dir isolation.** Each job runs in `~/actions-runner-gaia/_work/<repo>` and is cleaned between jobs. Secrets are masked; use `actions: read` minimal permissions on the probe job.
* **Docker rootless.** CI jobs run under `aryan` (rootless Docker) — a job cannot escape to host root via Docker socket.
