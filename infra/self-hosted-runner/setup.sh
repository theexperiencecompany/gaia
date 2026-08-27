#!/usr/bin/env bash
# setup.sh — idempotent multi-instance self-hosted runner installer for gaia-home-server
#
# Host: gaia-home-server.taila76294.ts.net  (100.126.190.120 via Tailscale)
# OS:   Ubuntu 24.04  —  Intel i7-10700K  16 threads  / 46 GiB  / NVMe / Docker 29.4.1 rootless
# User: aryan (uid 1001, groups: docker, sudo, gaia)
#
# Why N instances rather than one:
#   A runner instance executes exactly ONE job at a time. With a single
#   instance the hybrid-ci lanes (build, test-python, test-typescript) queue
#   behind each other — measured at 15+ minutes of pure queueing — while 16
#   cores sat at a load average of 3.5. Four instances let the lanes run
#   concurrently, which is where the core count actually pays off.
#
# Each instance gets RUNNER_INDEX in its .env. CI reads it to offset service
# container ports and names (scripts/ci/start-test-services.sh), so two
# concurrent test lanes on this box never collide on 5432/6379/27017/8000/5672.
#
# Usage (on the home server, or via tailscale ssh):
#   RUNNER_TOKEN=$(gh api --method POST /repos/theexperiencecompany/gaia/actions/runners/registration-token --jq .token) \
#   bash infra/self-hosted-runner/setup.sh
#
# Or pass token as $1:  bash infra/self-hosted-runner/setup.sh <token>
#
# Knobs: RUNNER_COUNT (default 4), RUNNER_VERSION, RUNNER_LABELS, RUNNER_LOCAL_CACHE
#
# Idempotent: safe to re-run. Cleans stale config, (re)installs, starts services.
# Requires: curl, tar, jq, docker. No inbound ports — runners poll GH over 443.
set -euo pipefail

REPO_URL="https://github.com/theexperiencecompany/gaia"
REPO_SLUG="theexperiencecompany/gaia"
RUNNER_COUNT="${RUNNER_COUNT:-6}"
# RUNNER_START lets a re-run add instances without re-registering the ones
# already serving jobs: RUNNER_START=5 RUNNER_COUNT=6 registers only 5 and 6.
RUNNER_START="${RUNNER_START:-1}"
RUNNER_NAME_PREFIX="${RUNNER_NAME_PREFIX:-gaia-home}"
RUNNER_LABELS="${RUNNER_LABELS:-gaia-home,16core,home-lab}"
RUNNER_GROUP="${RUNNER_GROUP:-default}"
INSTALL_ROOT="${RUNNER_INSTALL_ROOT:-/home/aryan}"
LEGACY_DIR="${LEGACY_RUNNER_DIR:-/home/aryan/actions-runner-gaia}"
RUNNER_VERSION="${RUNNER_VERSION:-2.336.0}"
RUNNER_ARCH="${RUNNER_ARCH:-x64}"
LOCAL_CACHE="${RUNNER_LOCAL_CACHE:-/home/aryan/ci-cache}"

# The runner's own PATH must carry the mise-managed Node the workflows expect
# (pnpm/action-setup shells out to node before setup-node has run; an older
# Node here surfaces as an opaque ERR_INVALID_ARG_TYPE).
RUNNER_PATH="${RUNNER_PATH:-/home/aryan/.local/share/mise/installs/node/22.23.2/bin:/home/aryan/.local/share/mise/installs/python/3.12/bin:/home/aryan/.local/bin:/home/aryan/.local/share/mise/shims:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin}"

# Resolve token: $1 > $RUNNER_TOKEN > $GITHUB_TOKEN (gh CLI fallback)
TOKEN="${1:-${RUNNER_TOKEN:-${GITHUB_TOKEN:-}}}"
if [[ -z "$TOKEN" ]]; then
  if command -v gh >/dev/null 2>&1; then
    echo "[setup] No token supplied — requesting ephemeral registration token via gh api..."
    TOKEN="$(gh api --method POST "/repos/${REPO_SLUG}/actions/runners/registration-token" --jq .token 2>&1 | tr -d '\n')" || true
  fi
fi
if [[ -z "$TOKEN" || "$TOKEN" == *"error"* ]]; then
  echo "::error::Missing runner registration token. Provide RUNNER_TOKEN env or gh auth."
  echo "  Obtain via: gh api --method POST /repos/${REPO_SLUG}/actions/runners/registration-token --jq .token"
  echo "  Or: GitHub → Settings → Actions → Runners → New self-hosted runner (copy token)"
  exit 1
fi

echo "[setup] Home server: $(hostname) — $(nproc) vCPUs, $(free -h | awk '/^Mem:/{print $2}') RAM"
echo "[setup] Instances: $RUNNER_COUNT  Labels: $RUNNER_LABELS  Version: $RUNNER_VERSION"
echo "[setup] Shared local CI cache: $LOCAL_CACHE"

# --- prerequisites ---
need() { command -v "$1" >/dev/null 2>&1 || { echo "::error::Missing $1"; exit 1; }; }
need curl
need tar

# Everything that needs root is optional: without it the runners still get
# installed, configured and started, they just run under nohup instead of a
# systemd unit and therefore do not survive a reboot. The summary at the end
# says so explicitly rather than leaving a silently non-persistent setup.
HAVE_SUDO=false
if sudo -n true 2>/dev/null; then
  HAVE_SUDO=true
fi
echo "[setup] Passwordless sudo: $HAVE_SUDO (systemd units and dependency install need it)"

if ! command -v jq >/dev/null 2>&1; then
  if [[ "$HAVE_SUDO" == "true" ]]; then
    echo "[setup] jq not found — installing..."
    sudo apt-get update -qq && sudo apt-get install -y -qq jq
  else
    echo "::warning::jq not found and no passwordless sudo — falling back to python3 for JSON"
  fi
fi
if ! docker info >/dev/null 2>&1; then
  echo "::warning::docker not reachable (rootless context may need XDG_RUNTIME_DIR). Continuing — the runner itself does not require docker, only CI jobs do."
fi

# Shared persistent cache: pnpm store, uv cache and the ~1.3 GB fastembed
# models live here instead of travelling through actions/cache on every run.
# actions-archive: the runner re-downloads every `uses:` action tarball per
# job unless ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE points somewhere persistent
# — measured at 69s for actions/cache@v6 alone on the residential uplink.
mkdir -p "$LOCAL_CACHE" "${LOCAL_CACHE}/actions-archive"

TARBALL="actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${TARBALL}"
CACHED_TARBALL="${LOCAL_CACHE}/${TARBALL}"

# Download once, extract N times.
if [[ ! -f "$CACHED_TARBALL" ]]; then
  echo "[setup] Downloading $URL ..."
  curl -fsSL --proto '=https' -o "$CACHED_TARBALL.part" "$URL"
  mv "$CACHED_TARBALL.part" "$CACHED_TARBALL"
else
  echo "[setup] Runner tarball already cached at $CACHED_TARBALL"
fi

# --- retire the legacy single-instance runner ---------------------------------
# It ran as a bare `nohup run.sh` (no systemd unit), so it neither survives a
# reboot nor participates in the indexed scheme. Its registration is removed so
# it cannot pick up jobs alongside the indexed instances.
if [[ -d "$LEGACY_DIR" && ! -f "$LEGACY_DIR/.runner_index" ]]; then
  echo "[setup] Retiring legacy single-instance runner at $LEGACY_DIR ..."
  pkill -f "$LEGACY_DIR/bin/Runner.Listener" 2>/dev/null || true
  if [[ -x "$LEGACY_DIR/svc.sh" ]]; then
    (cd "$LEGACY_DIR" && ./svc.sh stop 2>&1 | tail -n 3 || true)
    (cd "$LEGACY_DIR" && ./svc.sh uninstall 2>&1 | tail -n 3 || true)
  fi
  if [[ -f "$LEGACY_DIR/.runner" ]]; then
    (cd "$LEGACY_DIR" && ./config.sh remove --token "$TOKEN" 2>&1 | tail -n 5 || true)
  fi
  echo "[setup] Legacy runner retired (directory left on disk for inspection)."
fi

install_runner() {
  local idx="$1"
  local name="${RUNNER_NAME_PREFIX}-${idx}"
  local dir="${INSTALL_ROOT}/actions-runner-${RUNNER_NAME_PREFIX}-${idx}"

  echo ""
  echo "[setup] ── instance ${idx}/${RUNNER_COUNT}: ${name} → ${dir}"

  mkdir -p "$dir"
  cd "$dir"

  if [[ ! -f "./bin/Runner.Listener" ]]; then
    echo "[setup]   extracting runner ${RUNNER_VERSION}..."
    tar xzf "$CACHED_TARBALL"
  else
    echo "[setup]   runner binaries present — skipping extract."
  fi

  # Only needed once per machine, and this box already runs a runner, so a
  # skip here is normal rather than a problem.
  if [[ -f "./bin/installdependencies.sh" && "$HAVE_SUDO" == "true" ]]; then
    sudo ./bin/installdependencies.sh > /dev/null 2>&1 || echo "::warning::installdependencies.sh failed for ${name} — continuing"
  fi

  # Per-instance environment. RUNNER_INDEX is the contract CI relies on to
  # offset service ports; RUNNER_LOCAL_CACHE points the cache-aware composite
  # actions at persistent local storage.
  cat > "$dir/.env" <<ENVFILE
PATH=${RUNNER_PATH}
MISE_NODE_COREPACK=1
RUNNER_INDEX=${idx}
RUNNER_LOCAL_CACHE=${LOCAL_CACHE}
ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE=${LOCAL_CACHE}/actions-archive
ACTIONS_RUNNER_HOOK_JOB_STARTED=${LOCAL_CACHE}/hooks/job-started.sh
ACTIONS_RUNNER_HOOK_JOB_COMPLETED=${LOCAL_CACHE}/hooks/job-completed.sh
${NX_REMOTE_ENV}
ENVFILE

  # Stale registration → remove with the fresh token before reconfiguring.
  if [[ -f ".runner" ]]; then
    echo "[setup]   removing stale registration..."
    ./config.sh remove --token "$TOKEN" > /dev/null 2>&1 || true
    rm -f .runner .credentials .credentials_rsaparams 2>/dev/null || true
  fi

  echo "[setup]   configuring..."
  ./config.sh \
    --url "$REPO_URL" \
    --token "$TOKEN" \
    --name "$name" \
    --labels "$RUNNER_LABELS" \
    --runnergroup "$RUNNER_GROUP" \
    --work "_work" \
    --unattended \
    --replace 2>&1 | tail -n 5

  mkdir -p "_work"
  seed_workdir "$dir"

  # Persistence via a systemd USER unit rather than GitHub's svc.sh.
  # svc.sh writes a system unit, so it needs root on every install and every
  # restart. A user unit needs root exactly once, for lingering (below), which
  # is the difference between "CI needs an admin" and "CI just comes back".
  pkill -f "$dir/bin/Runner.Listener" 2>/dev/null || true
  systemctl --user disable --now "gaia-runner@${idx}" > /dev/null 2>&1 || true

  echo "[setup]   enabling gaia-runner@${idx}.service (user unit)..."
  systemctl --user enable --now "gaia-runner@${idx}" 2>&1 | tail -n 2 || {
    echo "::warning::user unit failed for ${name} — falling back to nohup"
    nohup ./run.sh > runner.log 2>&1 &
    echo "[setup]   run.sh PID $! (logs: $dir/runner.log)"
    NON_PERSISTENT=true
  }

  echo "$idx" > "$dir/.runner_index"
  echo "[setup]   ${name} ready."
}

# --- git mirror -------------------------------------------------------------
# A fresh runner's _work is empty, so actions/checkout does a full clone. This
# repo's history is ~242 MB and the box is on a residential uplink, which made
# the first checkout on a new instance take longer than the job it was setting
# up (observed: 10+ minutes, still running). Keep one bare mirror on local disk
# and seed each instance from it — `git clone --local` hardlinks the object
# store, so seeding is effectively free and costs no bandwidth at all.
#
# Git object files are immutable, so sharing them via hardlinks is safe; the
# instances still fetch their own refs from GitHub afterwards, incrementally.
MIRROR="${LOCAL_CACHE}/gaia.git"
SEED_FROM="${RUNNER_SEED_REPO:-/home/aryan/gaia}"

if [[ ! -d "$MIRROR" ]]; then
  if [[ -d "$SEED_FROM/.git" ]]; then
    echo "[setup] Creating git mirror from local checkout $SEED_FROM (no network)..."
    git clone --bare --local "$SEED_FROM/.git" "$MIRROR" 2>&1 | tail -n 2 || true
  else
    echo "[setup] Creating git mirror from $REPO_URL (one-time full clone)..."
    git clone --bare "$REPO_URL" "$MIRROR" 2>&1 | tail -n 2 || true
  fi
fi
if [[ -d "$MIRROR" ]]; then
  git -C "$MIRROR" remote set-url origin "$REPO_URL" 2>/dev/null || \
    git -C "$MIRROR" remote add origin "$REPO_URL" 2>/dev/null || true
  echo "[setup] Refreshing mirror..."
  git -C "$MIRROR" fetch --quiet --prune origin "+refs/heads/*:refs/heads/*" 2>&1 | tail -n 2 || \
    echo "::warning::mirror fetch failed — instances will fall back to a full clone"
  echo "[setup] Mirror: $MIRROR ($(du -sh "$MIRROR" 2>/dev/null | cut -f1))"
fi

# Lay down the checkout actions/checkout expects (_work/<repo>/<repo>) from the
# mirror, so its first run is an incremental fetch instead of a cold clone.
seed_workdir() {
  local dir="$1"
  local dest="$dir/_work/gaia/gaia"
  [[ -d "$MIRROR" ]] || return 0
  if [[ -d "$dest/.git" ]]; then
    echo "[setup]   workdir already seeded — skipping."
    return 0
  fi
  echo "[setup]   seeding $dest from the local mirror..."
  mkdir -p "$dir/_work/gaia"
  if git clone --local --no-checkout "$MIRROR" "$dest" 2>&1 | tail -n 2; then
    git -C "$dest" remote set-url origin "$REPO_URL"
    echo "[setup]   seeded ($(du -sh "$dest/.git" 2>/dev/null | cut -f1), 0 bytes over the network)"
  else
    echo "::warning::seeding failed — actions/checkout will do a full clone instead"
    rm -rf "$dest"
  fi
}

# Job hooks: the runner runs these before and after every job with the job's
# environment. They give ephemeral-grade hygiene (see hooks/job-started.sh)
# without per-job re-registration.
HOOK_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/hooks"
mkdir -p "${LOCAL_CACHE}/hooks"
install -m 0755 "$HOOK_SRC"/job-started.sh "$HOOK_SRC"/job-completed.sh "${LOCAL_CACHE}/hooks/" 2>/dev/null \
  && echo "[setup] Job hooks installed to ${LOCAL_CACHE}/hooks" \
  || echo "::warning::job hooks not found beside setup.sh"

# One templated user unit serves every instance: `gaia-runner@2` runs the
# runner in actions-runner-gaia-home-2. Restart=always covers the runner
# exiting after an update; the runner handles its own job-level lifecycle.
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/gaia-runner@.service" <<UNIT
[Unit]
Description=GitHub Actions runner (gaia-home instance %i)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_ROOT}/actions-runner-${RUNNER_NAME_PREFIX}-%i
ExecStart=${INSTALL_ROOT}/actions-runner-${RUNNER_NAME_PREFIX}-%i/run.sh
Restart=always
RestartSec=5
KillMode=process
KillSignal=SIGTERM
TimeoutStopSec=5min
Environment=RUNNER_INDEX=%i
Environment=RUNNER_LOCAL_CACHE=${LOCAL_CACHE}

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
echo "[setup] Wrote $UNIT_DIR/gaia-runner@.service"

# Shared Nx remote cache (see nx-cache-server/README.md). The per-runner local
# Nx cache is SQLite-backed and therefore keyed per instance; this server is
# the tier every instance shares. Loopback only; token stays on the host.
NX_SRV_DIR="${LOCAL_CACHE}/nx-cache-server"
NX_TOKEN_FILE="${LOCAL_CACHE}/nx-remote.token"
NX_CACHE_PORT="${NX_CACHE_PORT:-4222}"
NX_SRV_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/nx-cache-server/server.mjs"
if [[ -f "$NX_SRV_SRC" ]]; then
  mkdir -p "$NX_SRV_DIR" "${LOCAL_CACHE}/nx-remote"
  install -m 0644 "$NX_SRV_SRC" "$NX_SRV_DIR/server.mjs"
  if [[ ! -s "$NX_TOKEN_FILE" ]]; then
    (umask 077; head -c 32 /dev/urandom | base64 | tr -d '/+=\n' > "$NX_TOKEN_FILE")
    echo "[setup] Generated Nx cache token at $NX_TOKEN_FILE"
  fi
  NODE_BIN="$(command -v node || echo /home/aryan/.local/share/mise/installs/node/22.23.2/bin/node)"
  cat > "$UNIT_DIR/gaia-nx-cache.service" <<UNIT
[Unit]
Description=Shared Nx remote cache for the home runner instances
After=network.target

[Service]
Type=simple
Environment=NX_CACHE_DIR=${LOCAL_CACHE}/nx-remote
Environment=NX_CACHE_PORT=${NX_CACHE_PORT}
Environment=NX_CACHE_HOST=127.0.0.1
Environment=NX_CACHE_MAX_BYTES=${NX_CACHE_MAX_BYTES:-8589934592}
ExecStart=/bin/bash -c 'NX_CACHE_TOKEN="\$(cat ${NX_TOKEN_FILE})" exec ${NODE_BIN} ${NX_SRV_DIR}/server.mjs'
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable --now gaia-nx-cache.service > /dev/null 2>&1 \
    && echo "[setup] Nx cache server enabled on 127.0.0.1:${NX_CACHE_PORT}" \
    || echo "::warning::could not start gaia-nx-cache.service"
  NX_REMOTE_ENV="NX_SELF_HOSTED_REMOTE_CACHE_SERVER=http://127.0.0.1:${NX_CACHE_PORT}
NX_SELF_HOSTED_REMOTE_CACHE_ACCESS_TOKEN=$(cat "$NX_TOKEN_FILE")"
else
  NX_REMOTE_ENV=""
fi

# One persistent BuildKit builder shared by every runner instance. The slow
# part of an image build here is the --mount=type=cache layers (apt, uv:
# measured 29 minutes cold over the residential uplink, 5 seconds warm) and
# those mounts live INSIDE the builder instance — no --cache-to exports them.
# A per-job builder, which is what docker/setup-buildx-action creates by
# default, throws them away every time. GC is bounded by SIZE (keep_bytes),
# not age, so a busy week cannot grow it past the disk.
if command -v docker >/dev/null 2>&1 && docker buildx version >/dev/null 2>&1; then
  BUILDKIT_CONF="${LOCAL_CACHE}/buildkitd.toml"
  cat > "$BUILDKIT_CONF" <<'BKCONF'
# Shared CI builder. Cache bounded by size; see setup.sh.
[worker.oci]
  gc = true
  [[worker.oci.gcpolicy]]
    keepBytes = "20GB"
    keepDuration = "168h"
  [[worker.oci.gcpolicy]]
    all = true
    keepBytes = "30GB"
BKCONF
  if docker buildx inspect gaia-ci >/dev/null 2>&1; then
    echo "[setup] buildx builder 'gaia-ci' already exists"
  else
    docker buildx create --name gaia-ci --driver docker-container \
      --driver-opt network=host --config "$BUILDKIT_CONF" --bootstrap >/dev/null 2>&1 \
      && echo "[setup] buildx builder 'gaia-ci' created (persistent, 30 GB cache cap)" \
      || echo "::warning::could not create the gaia-ci buildx builder"
  fi
fi

# Nightly cache prune as a user timer, so the persistent caches that make the
# box fast stay size-bounded without anyone remembering to run anything.
# prune-cache.sh is copied beside the runners so the timer does not depend on
# a particular checkout existing.
PRUNE_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prune-cache.sh"
if [[ -f "$PRUNE_SRC" ]]; then
  install -m 0755 "$PRUNE_SRC" "${LOCAL_CACHE}/prune-cache.sh"
  cat > "$UNIT_DIR/gaia-ci-prune.service" <<UNIT
[Unit]
Description=Prune the home runner's persistent CI caches to their size budgets

[Service]
Type=oneshot
Environment=RUNNER_LOCAL_CACHE=${LOCAL_CACHE}
Environment=PATH=${RUNNER_PATH}
ExecStart=/usr/bin/env bash ${LOCAL_CACHE}/prune-cache.sh --apply
UNIT
  cat > "$UNIT_DIR/gaia-ci-prune.timer" <<'UNIT'
[Unit]
Description=Nightly CI cache prune

[Timer]
OnCalendar=*-*-* 04:30:00
RandomizedDelaySec=15m
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable --now gaia-ci-prune.timer > /dev/null 2>&1 \
    && echo "[setup] Nightly cache prune timer enabled (gaia-ci-prune.timer, 04:30)" \
    || echo "::warning::could not enable gaia-ci-prune.timer"
else
  echo "::warning::prune-cache.sh not found beside setup.sh — no cache prune timer installed"
fi

NON_PERSISTENT=false
for i in $(seq "$RUNNER_START" "$RUNNER_COUNT"); do
  install_runner "$i"
done

# The one and only step that needs root. Without lingering, user units stop
# when the last session for the user ends, so the runners would vanish on ssh
# logout and never return after a reboot.
if loginctl show-user "$(id -un)" --property=Linger 2>/dev/null | grep -q "Linger=yes"; then
  echo "[setup] Lingering already enabled for $(id -un)."
elif sudo -n loginctl enable-linger "$(id -un)" 2>/dev/null; then
  echo "[setup] Lingering enabled for $(id -un)."
else
  NON_PERSISTENT=true
  echo "::warning::could not enable lingering (needs root once). The runners are"
  echo "::warning::running now but will not survive a reboot or logout until you run:"
  echo "::warning::  sudo loginctl enable-linger $(id -un)"
fi

# --- verify registration ------------------------------------------------------
echo ""
echo "[setup] Verifying instances appear in the GitHub API (up to 60s)..."
GH_TOKEN_FALLBACK="$(gh auth token 2>/dev/null | tr -d '\n' || echo "$TOKEN")"
for attempt in $(seq 1 12); do
  COUNT="$(curl -sSf --max-time 10 \
    -H "Authorization: Bearer $GH_TOKEN_FALLBACK" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${REPO_SLUG}/actions/runners" 2>/dev/null | \
    jq '[.runners[] | select(.labels[].name=="gaia-home") | select(.status=="online")] | length' 2>/dev/null || echo 0)"
  echo "  attempt $attempt/12: ${COUNT}/${RUNNER_COUNT} online"
  if [[ "$COUNT" -ge "$RUNNER_COUNT" ]]; then
    echo "[setup] ✅ All ${RUNNER_COUNT} instances online."
    break
  fi
  sleep 5
done

curl -sSf --max-time 10 -H "Authorization: Bearer $GH_TOKEN_FALLBACK" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${REPO_SLUG}/actions/runners" 2>/dev/null | \
  jq -r '.runners[] | select(.labels[].name=="gaia-home") | "  \(.name)\tstatus=\(.status)\tbusy=\(.busy)"' || true

cat <<EOF

[setup] Done. ${RUNNER_COUNT} instances labelled '${RUNNER_LABELS}'.
$(if [[ "$NON_PERSISTENT" == "true" ]]; then
cat <<'WARN'

  ⚠  Not fully reboot-persistent yet. The runners are up, but user units only
     survive logout/reboot once lingering is enabled — a one-time root step:
       sudo loginctl enable-linger $(id -un)
     No other part of this setup needs root, by design.
WARN
fi)
  Check:  gh api repos/${REPO_SLUG}/actions/runners --jq '.runners[] | select(.labels[].name=="gaia-home") | "\(.name) \(.status) busy=\(.busy)"'
  Logs:   journalctl --user -u 'gaia-runner@*' -f
  Prune:  systemctl --user list-timers gaia-ci-prune.timer   (nightly; run now: systemctl --user start gaia-ci-prune)
  Status: systemctl --user status 'gaia-runner@*'
  Stop:   systemctl --user disable --now gaia-runner@{1..${RUNNER_COUNT}}
  Remove: for d in ${INSTALL_ROOT}/actions-runner-${RUNNER_NAME_PREFIX}-*; do (cd "\$d" && ./config.sh remove --token <new-token>); done

  Next: trigger hybrid CI and watch the lanes run concurrently:
    gh workflow run hybrid-ci.yml --ref \$(git branch --show-current) -f force_home=false
EOF

cat <<'SECURITY'

  Security notes (private repo only):
  • This repo is private (theexperiencecompany/gaia) — safe for self-hosted.
  • NEVER enable these runners on a public fork — PRs could execute arbitrary code on your home server.
  • No inbound ports opened: runners poll GitHub over HTTPS:443 outbound (long-poll).
  • The registration token used here is ephemeral (1h) — generate a fresh one to re-register.
  • Job work dirs are cleaned per job; secrets are masked in logs.
  • The shared local CI cache holds dependency artifacts only — never secrets.
SECURITY
