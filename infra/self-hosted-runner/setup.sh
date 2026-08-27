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
RUNNER_COUNT="${RUNNER_COUNT:-4}"
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
if ! command -v jq >/dev/null 2>&1; then
  echo "[setup] jq not found — installing..."
  sudo apt-get update -qq && sudo apt-get install -y -qq jq
fi
if ! docker info >/dev/null 2>&1; then
  echo "::warning::docker not reachable (rootless context may need XDG_RUNTIME_DIR). Continuing — the runner itself does not require docker, only CI jobs do."
fi

# Shared persistent cache: pnpm store, uv cache and the ~1.3 GB fastembed
# models live here instead of travelling through actions/cache on every run.
mkdir -p "$LOCAL_CACHE"

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

  if [[ -f "./bin/installdependencies.sh" ]]; then
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

  # systemd user unit, so the instance survives a reboot — the previous
  # nohup-based runner did not. Requires lingering (enabled below).
  echo "[setup]   installing service..."
  ./svc.sh stop > /dev/null 2>&1 || true
  ./svc.sh uninstall > /dev/null 2>&1 || true
  if ./svc.sh install 2>&1 | tail -n 3; then
    ./svc.sh start 2>&1 | tail -n 3
  else
    echo "::warning::svc.sh install failed for ${name} — falling back to nohup"
    nohup ./run.sh > runner.log 2>&1 &
    echo "[setup]   run.sh PID $! (logs: $dir/runner.log)"
  fi

  echo "$idx" > "$dir/.runner_index"
  echo "[setup]   ${name} ready."
}

for i in $(seq 1 "$RUNNER_COUNT"); do
  install_runner "$i"
done

# Without lingering, systemd user units stop when the last session for the
# user ends — the runners would silently disappear after an ssh logout.
sudo loginctl enable-linger aryan 2>/dev/null || echo "::warning::could not enable linger for aryan — runners may stop on logout"

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
  Check:  gh api repos/${REPO_SLUG}/actions/runners --jq '.runners[] | select(.labels[].name=="gaia-home") | "\(.name) \(.status) busy=\(.busy)"'
  Logs:   journalctl --user -u 'actions.runner.*' -f
  Stop:   for d in ${INSTALL_ROOT}/actions-runner-${RUNNER_NAME_PREFIX}-*; do (cd "\$d" && ./svc.sh stop); done
  Remove: for d in ${INSTALL_ROOT}/actions-runner-${RUNNER_NAME_PREFIX}-*; do (cd "\$d" && ./svc.sh uninstall && ./config.sh remove --token <new-token>); done

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
