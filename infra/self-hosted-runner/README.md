# Self-hosted runner — gaia-home-server

Home lab runner that accelerates CI 3-6× over GitHub's 2 vCPU runners, with
automatic fallback so PRs never queue forever when the home box is offline.

## Machine

| | |
|---|---|
| Host | `gaia-home-server.taila76294.ts.net` (`100.126.190.120` via Tailscale) |
| User | `gaia-ci` — dedicated unprivileged runner user; its home holds only runner installs and caches. No sudo. |
| OS | Ubuntu 24.04.4 LTS (Noble) |
| CPU | Intel i7-10700K — 8 cores / 16 threads @ 3.8 GHz (5.1 GHz boost) |
| RAM | 46 GiB |
| Disk | 457 GiB NVMe (104 GiB free) |
| Docker | 29.4.1 rootless per user (`unix:///run/user/<uid>/docker.sock`, `context=rootless`) |
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

Idempotent — re-running cleans stale registration and restarts the services.
`setup.sh` installs `RUNNER_COUNT` (default 4) runner instances, the job
hooks, the shared Nx cache service, and the nightly prune/janitor timer.

Host performance profile (one-time, needs sudo on the box):

```bash
bash infra/self-hosted-runner/tune-host.sh            # apply
bash infra/self-hosted-runner/tune-host.sh --revert   # undo
```

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

The probe writes a human summary to `$GITHUB_STEP_SUMMARY`:

> ### Runner selection — home (fast path) …or… Runner selection — fallback (offline)

A job never waits on a dead self-hosted label because nothing ever does `runs-on: [self-hosted]` unconditionally.

## Workflows using it

| Workflow | How it opts in |
|---|---|
| `.github/workflows/main.yml` ("Quality Checks") | Every compute lane goes through `select-runner` on every PR and master push — home box first, GitHub-hosted fallback. `workflow_dispatch` adds `force_home` (fail instead of falling back) and the `probe` job. |
| `.github/workflows/code-quality.yml` ("Code Quality") | Same `select-runner` job; every hygiene lane and the mutation shards land on the selected runner. |
| `.github/workflows/build.yml` | Does **not** use the home runner — every job is `ubuntu-latest`. Release image builds stay off the box on purpose. |

## Benchmarks

Measured during the migration (the profiling harness that produced this table
was removed with the experiment; re-measure with `gh run list` timings on real
runs, per the "Verify with real workflow runs" rule in the root `CLAUDE.md`).

Headroom (Amdahl, I/O-bound steps capped):

| Workload | GH 2 vCPU | Home 16c | Speedup |
|---|---|---|---|
| `pnpm install` (cold) | ~85 s | ~40 s | 2.1× |
| `nx run-many -t build` (web) | ~240 s | ~95 s | 2.5× |
| `ruff check .` (strict) | ~28 s | ~9 s | 3.1× |
| `mypy` staged-strict | ~95 s | ~32 s | 3.0× |
| `pytest -n auto` hermetic | ~180 s | ~45 s | 4.0× |
| `pytest` live-services | ~240 s | ~55 s | 4.4× |
| Docker build (api) | ~420 s† | ~150 s | 2.8× |

† GitHub-hosted 2 vCPU with BuildKit cache vs home NVMe + rootless BuildKit.

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

## Migrating to a new runner user

Everything in `setup.sh`, `prune-cache.sh`, `runner-health.sh` and the hooks
derives its paths from `$HOME` and its ports from environment, so a second
user's stack can run beside the old one on the same box during cutover.

Root payload (once, as an admin):

```bash
sudo useradd -m -s /bin/bash gaia-ci
grep -q '^gaia-ci:' /etc/subuid || echo 'gaia-ci:200000:65536' | sudo tee -a /etc/subuid /etc/subgid   # rootless docker
sudo loginctl enable-linger gaia-ci
# Seed the caches so the first jobs are warm (paths under the OLD user's home):
sudo rsync -a /home/aryan/ci-cache/ /home/gaia-ci/ci-cache/
sudo rsync -a /home/aryan/.local/share/pnpm/store/ /home/gaia-ci/.local/share/pnpm/store/
sudo rsync -a /home/aryan/.cache/uv/ /home/gaia-ci/.cache/uv/
sudo rsync -a /home/aryan/actions-runner-gaia-home-1/_work/_tool/ /home/gaia-ci/ci-cache/_tool-seed/
sudo install -d -m 0700 -o gaia-ci -g gaia-ci /home/gaia-ci/.config/gaia-ci
echo 'GH_TOKEN=<fine-grained PAT: Administration read/write on the repo, for the runners API>' \
  | sudo install -m 0600 -o gaia-ci -g gaia-ci /dev/stdin /home/gaia-ci/.config/gaia-ci/gh.env
sudo chown -R gaia-ci:gaia-ci /home/gaia-ci
```

Then, as `gaia-ci` (`sudo -iu gaia-ci`):

```bash
dockerd-rootless-setuptool.sh install && docker context use rootless
mise use -g node@22.23.2 python@3.12 && curl -LsSf https://astral.sh/uv/install.sh | sh
# The five test images, exported from the old user's daemon (docker save ...):
for f in ~/ci-cache/images/*.tar; do docker load -i "$f"; done
# Temporary prefix/labels/ports so nothing collides with the old stack:
RUNNER_NAME_PREFIX=gaia-ci RUNNER_LABELS=gaia-ci,16core,home-lab LINT_RUNNER_LABELS=gaia-ci-lint,16core,home-lab \
  SIDECAR_PORT_BASE=28200 NX_CACHE_PORT=4223 \
  GAIA_SHARED_POSTGRES_PORT=26432 GAIA_SHARED_REDIS_PORT=17379 GAIA_SHARED_MONGO_PORT=38017 \
  GAIA_SHARED_CHROMA_PORT=19000 GAIA_SHARED_RABBITMQ_PORT=26673 \
  RUNNER_TOKEN=<token> bash infra/self-hosted-runner/setup.sh
```

Proof run: `gh workflow run main.yml --ref <branch>` with the workflow pointed
at the temporary labels, and check the job logs show `/home/gaia-ci` paths and
the new ports. Then relabel the new instances to the production labels via the
runners API (`gh api -X POST repos/<owner>/<repo>/actions/runners/<id>/labels
-f 'labels[]=gaia-home'` and remove the temporary ones), and retire the old
user's instances: `systemctl --user disable --now 'gaia-runner@*'` as `aryan`,
then `./config.sh remove --token <token>` in each of its runner directories.
The ports can go back to the defaults on the next `setup.sh` run once the old
stack is gone.

## Security

* **Private repo only.** `theexperiencecompany/gaia` is private — PRs are from trusted collaborators. Never add this runner to a public repo (malicious PRs would execute on your home server).
* **No inbound firewall rules.** The runner initiates outbound long-poll on 443; Tailscale is only for your SSH maintenance, not for GitHub to reach the runner.
* **Ephemeral token.** Registration tokens expire in ~1 h. Never commit one; generate on demand.
* **Work dir isolation.** Each job runs in `~/actions-runner-gaia/_work/<repo>` and is cleaned between jobs. Secrets are masked; use `actions: read` minimal permissions on the probe job.
* **Docker rootless.** CI jobs run under the unprivileged `gaia-ci` user with its own rootless Docker daemon — a job cannot escape to host root via the Docker socket, and it cannot read the owner's home.

## Shared test services (one container set for every lane)

`scripts/ci/start-test-services.sh` boots five containers **per job**. With the
box's eleven `gaia-home` runner instances (`RUNNER_COUNT` / `LINT_RUNNER_START`
in `setup.sh`) that would be 55 containers:
a measured 20-45 s of boot time on every job's critical path, and ~12-18 GB of
RAM against 46 GiB of machine, alongside the lanes' own workers. The same five containers started **once** and kept warm cost ~0.6 GB and
zero boot time per job.

`scripts/ci/shared-test-services.sh` is that harness. The containers are shared;
what differs per lane is the namespace each lane writes into.

### Namespace per service

| Service | Namespace unit | Lane `r` gets | Provisioned by |
| --- | --- | --- | --- |
| PostgreSQL | database | `gaia_test_r<r>` | `prepare` (`CREATE DATABASE`) |
| Redis | 32-DB stripe | DBs `8+r*32` … `39+r*32` | nothing — server runs `--databases 256` |
| MongoDB | database name | `gaia_test_r<r>_gw<n>` | nothing — created on first write |
| ChromaDB | collection **name suffix** | `…_r<r>` | nothing — created on first write |
| RabbitMQ | vhost | `/r<r>` | `prepare` (`add_vhost` + `set_permissions`) |

### Commands

```bash
scripts/ci/shared-test-services.sh up          # idempotent; no-op when healthy
scripts/ci/shared-test-services.sh prepare 3   # lane 3's namespaces + env file
scripts/ci/shared-test-services.sh reset 3     # destroy everything lane 3 made
scripts/ci/shared-test-services.sh janitor     # reset lanes stale for >3 h
```

`up` is safe to call from every lane unconditionally — only the first job on a
cold box does any work. The containers carry `--restart unless-stopped` and are
named `gaia-shared-<svc>`; nothing in this script removes them. A cancelled job
never runs its own `reset`, so `janitor` (cron, hourly) collects any lane whose
`/tmp/gaia-test-services-<r>.env` has not been touched in `GAIA_SHARED_STALE_HOURS`
(default 3).

### The env contract a lane needs

`prepare <r>` writes `/tmp/gaia-test-services-<r>.env` and appends it to
`$GITHUB_ENV` when set. A lane needs exactly these, and nothing else:

```
DATABASE_URL=postgresql://gaia:gaia@localhost:5432/gaia_test_r<r>
POSTGRES_URL=postgresql://gaia:gaia@localhost:5432/gaia_test_r<r>
REDIS_URL=redis://localhost:6379/0
GAIA_REDIS_DB_BASE=<8 + r*32>
MONGODB_URL=mongodb://gaia:gaia@localhost:27017/gaia_test_r<r>?authSource=admin
MONGO_DB=mongodb://gaia:gaia@localhost:27017/gaia_test_r<r>?authSource=admin
MONGO_DB_NAME=gaia_test_r<r>
GAIA_MONGO_DB_BASE=gaia_test_r<r>
CHROMADB_HOST=localhost
CHROMADB_PORT=8000
GAIA_CHROMA_COLLECTION_SUFFIX=_r<r>
RABBITMQ_URL=amqp://guest:guest@localhost:5672/r<r>
```

Three of those are new and are what make sharing possible:

* **`GAIA_REDIS_DB_BASE`** — `tests/helpers.py:worker_redis_url` starts its
  flushable block here instead of at the hardcoded DB 8. DB 0 is still never
  used by any worker, so `flushdb()` teardown can never touch a live database.
* **`MONGO_DB_NAME`** / **`GAIA_MONGO_DB_BASE`** — the app ignores the database
  component of the Mongo URI by design (`app/db/mongodb/mongodb.py`), so the
  *name* is the only namespace available. The first names the app's database,
  the second the base that `worker_mongo_db_name()` suffixes per xdist worker.
* **`GAIA_CHROMA_COLLECTION_SUFFIX`** — appended to every GAIA collection name
  (`app/constants/chroma.py`, `constants/memory.py`, `constants/files.py`, and
  the bootstrap list in `db/chroma/chromadb.py`).

**Every one of them defaults to the current single-lane behaviour when unset**,
so `start-test-services.sh` and local runs are unaffected.

### Trade-off: one Chroma process for all lanes

Postgres, Redis, Mongo and RabbitMQ all have a real server-side namespace, so a
lane is isolated *and* independently resource-accounted. ChromaDB has neither —
one process, one flat collection namespace, one shared HNSW index cache and one
shared request queue. Isolation is by naming convention only, which means:

* **Noisy neighbour.** A lane running the memory suite's embedding-heavy tests
  slows every other lane's Chroma calls. There is no per-collection quota.
* **Blast radius.** If the single Chroma process OOMs or wedges, every lane
  fails together rather than one.
* **Leak visibility.** A lane that dies without `reset` leaves its collections
  resident in the shared process until `janitor` runs.

Accepted deliberately: a per-lane Chroma is the single most expensive container
of the five, and the alternative (one Chroma per lane) is most of the RAM problem this
scheme exists to solve. If Chroma contention shows up in lane timings, the next
move is a per-lane Chroma while the other four services stay shared.
