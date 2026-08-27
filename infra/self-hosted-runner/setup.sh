#!/usr/bin/env bash
# setup.sh — idempotent self-hosted runner installer for gaia-home-server
#
# Host: gaia-home-server.taila76294.ts.net  (100.126.190.120 via Tailscale)
# OS:   Ubuntu 24.04  —  Intel i7-10700K  16 threads  / 46 GiB  / NVMe / Docker 29.4.1 rootless
# User: aryan (uid 1001, groups: docker, sudo, gaia)
#
# Usage (on the home server, or via tailscale ssh):
#   RUNNER_TOKEN=$(gh api --method POST /repos/theexperiencecompany/gaia/actions/runners/registration-token --jq .token) \
#   bash infra/self-hosted-runner/setup.sh
#
# Or pass token as $1:  bash infra/self-hosted-runner/setup.sh <token>
#
# Idempotent: safe to re-run. Cleans stale config, (re)installs runner, starts svc.
# Requires: curl, tar, jq, docker. No inbound ports — runner polls GH over 443.
set -euo pipefail

REPO_URL="https://github.com/theexperiencecompany/gaia"
RUNNER_NAME="${RUNNER_NAME:-gaia-home-server}"
RUNNER_LABELS="${RUNNER_LABELS:-gaia-home,16core,home-lab}"
RUNNER_GROUP="${RUNNER_GROUP:-default}"
WORK_DIR="${RUNNER_WORK_DIR:-_work}"
INSTALL_DIR="${RUNNER_DIR:-/home/aryan/actions-runner-gaia}"
RUNNER_VERSION="${RUNNER_VERSION:-2.328.0}"
RUNNER_ARCH="${RUNNER_ARCH:-x64}"

# Resolve token: $1 > $RUNNER_TOKEN > $GITHUB_TOKEN (gh CLI fallback)
TOKEN="${1:-${RUNNER_TOKEN:-${GITHUB_TOKEN:-}}}"
if [[ -z "$TOKEN" ]]; then
  if command -v gh >/dev/null 2>&1; then
    echo "[setup] No token supplied — requesting ephemeral registration token via gh api..."
    TOKEN="$(gh api --method POST /repos/theexperiencecompany/gaia/actions/runners/registration-token --jq .token 2>&1 | tr -d '\n')" || true
  fi
fi
if [[ -z "$TOKEN" || "$TOKEN" == *"error"* ]]; then
  echo "::error::Missing runner registration token. Provide RUNNER_TOKEN env or gh auth."
  echo "  Obtain via: gh api --method POST /repos/theexperiencecompany/gaia/actions/runners/registration-token --jq .token"
  echo "  Or: GitHub → Settings → Actions → Runners → New self-hosted runner (copy token)"
  exit 1
fi

echo "[setup] Home server: $(hostname) — $(nproc) vCPUs, $(free -h | awk '/^Mem:/{print $2}') RAM"
echo "[setup] Install dir: $INSTALL_DIR"
echo "[setup] Labels: $RUNNER_LABELS  Name: $RUNNER_NAME  Version: $RUNNER_VERSION"

# --- prerequisites ---
need() { command -v "$1" >/dev/null 2>&1 || { echo "::error::Missing $1"; exit 1; }; }
need curl
need tar
# jq optional but nicer
if ! command -v jq >/dev/null 2>&1; then
  echo "[setup] jq not found — installing..."
  sudo apt-get update -qq && sudo apt-get install -y -qq jq
fi
if ! docker info >/dev/null 2>&1; then
  echo "::warning::docker not reachable (rootless context may need XDG_RUNTIME_DIR). Continuing — runner itself does not require docker, only CI jobs do."
fi

# --- download & extract (idempotent) ---
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

TARBALL="actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz"
URL="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${TARBALL}"

if [[ -f "./run.sh" ]]; then
  echo "[setup] Existing runner detected — checking version..."
  INSTALLED_VERSION="$(cat .runner 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('gitHubUrl',''))" 2>&1 | head -n1 || true)"
  # If bin/Runner.Listener exists we are good; otherwise re-extract
  if [[ ! -f "./bin/Runner.Listener" ]]; then
    echo "[setup] Corrupt install — re-extracting..."
    rm -rf ./bin ./externals ./.runner ./.credentials* ./_work 2>&1 | head -n 5 || true
  fi
fi

if [[ ! -f "./run.sh" ]]; then
  echo "[setup] Downloading $URL ..."
  curl -fsSL --proto '=https' -o "$TARBALL" "$URL"
  echo "[setup] Verifying tarball..."
  # Pin checksum when known; otherwise skip with warning (GitHub does not publish checksums separately)
  tar xzf "$TARBALL"
  rm -f "$TARBALL"
  echo "[setup] Extracted to $INSTALL_DIR"
else
  echo "[setup] run.sh present — skipping download."
fi

# Install deps (libicu etc.)
if [[ -f "./bin/installdependencies.sh" ]]; then
  echo "[setup] Installing runner dependencies..."
  sudo ./bin/installdependencies.sh 2>&1 | tail -n 20 || echo "::warning::installdependencies.sh failed — continuing"
fi

# --- remove stale registration if present ---
if [[ -f ".runner" ]]; then
  echo "[setup] Removing stale registration..."
  # --unattended requires token; use the new token to remove old config
  ./config.sh remove --token "$TOKEN" 2>&1 | tail -n 20 || true
  rm -f .runner .credentials .credentials_rsaparams 2>&1 || true
fi

# --- configure ---
echo "[setup] Configuring runner..."
./config.sh \
  --url "$REPO_URL" \
  --token "$TOKEN" \
  --name "$RUNNER_NAME" \
  --labels "$RUNNER_LABELS" \
  --runnergroup "$RUNNER_GROUP" \
  --work "$WORK_DIR" \
  --unattended \
  --replace \
  --ephemeral false 2>&1 | tail -n 40

# Ensure work dir exists and is writable
mkdir -p "$WORK_DIR"
chmod 775 "$WORK_DIR" 2>&1 || true

# --- install & start service ---
# Prefer user systemd (rootless host) then fall back to system svc.
# Actions runner svc.sh supports both: it detects systemd and writes appropriate unit.

if [[ -f "./svc.sh" ]]; then
  echo "[setup] Installing service..."
  # Stop existing service first if running
  ./svc.sh stop 2>&1 | tail -n 10 || true
  ./svc.sh uninstall 2>&1 | tail -n 10 || true

  # Install (requires sudo for system unit; user unit does not)
  # On rootless Ubuntu, svc.sh will install a user service under ~/.config/systemd/user
  if ./svc.sh install 2>&1 | tail -n 20; then
    echo "[setup] Service installed."
  else
    echo "::warning::svc.sh install failed — falling back to nohup"
  fi

  echo "[setup] Starting runner service..."
  if ./svc.sh start 2>&1 | tail -n 20; then
    echo "[setup] Service started."
    ./svc.sh status 2>&1 | tail -n 30 || true
  else
    echo "::warning::svc.sh start failed — trying run.sh via nohup"
    nohup ./run.sh > runner.log 2>&1 &
    echo "[setup] run.sh launched in background (PID $!). Logs: $INSTALL_DIR/runner.log"
  fi
else
  echo "[setup] svc.sh not found — launching via nohup run.sh"
  nohup ./run.sh > runner.log 2>&1 &
  echo "[setup] run.sh PID $! — logs at $INSTALL_DIR/runner.log"
fi

# --- verify registration ---
echo "[setup] Verifying runner appears in GitHub API (up to 30s)..."
GH_TOKEN_FALLBACK="$(gh auth token 2>/dev/null | tr -d '\n' || echo "$TOKEN")"
for i in $(seq 1 6); do
  FOUND="$(curl -sSf --max-time 10 -H "Authorization: Bearer $GH_TOKEN_FALLBACK" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/theexperiencecompany/gaia/actions/runners" 2>&1 | \
    python3 -c "
import json,sys
label='gaia-home'
data=json.load(sys.stdin)
for r in data.get('runners',[]):
    if any(l.get('name')==label for l in r.get('labels',[])):
        print(f\"{r['name']} status={r['status']} busy={r['busy']} labels={[l['name'] for l in r['labels']]}\")
        sys.exit(0)
print('not-found')
" 2>&1 || echo "api-error")"
  echo "  attempt $i/6: $FOUND"
  if echo "$FOUND" | grep -q "status=online"; then
    echo "[setup] ✅ Runner online and registered!"
    break
  fi
  sleep 5
done

echo ""
echo "[setup] Done. Runner '$RUNNER_NAME' ($RUNNER_LABELS) at $INSTALL_DIR"
echo "  Check:  gh api repos/theexperiencecompany/gaia/actions/runners --jq '.runners[] | select(.labels[].name==\"gaia-home\")'"
echo "  Logs:   $INSTALL_DIR/_diag/*.log  or  journalctl --user -u actions.runner.* -f"
echo "  Stop:   $INSTALL_DIR/svc.sh stop"
echo "  Remove: $INSTALL_DIR/svc.sh uninstall && $INSTALL_DIR/config.sh remove --token <new-token>"
echo ""
echo "  Next: trigger hybrid CI to verify fallback:"
echo "    gh workflow run hybrid-ci.yml --ref \$(git branch --show-current) -f force_home=false"
echo "    # Should show 'Runner selection — home (fast path)' when online, else fallback in <15s"

# Warn about firewall / security
cat <<'SECURITY'

  Security notes (private repo only):
  • This repo is private (theexperiencecompany/gaia) — safe for self-hosted.
  • NEVER enable this runner on a public fork — PRs could execute arbitrary code on your home server.
  • No inbound ports opened: runner polls GitHub over HTTPS:443 outbound (long-poll).
  • Token used here is ephemeral (1h) — generate a fresh one for re-registration.
  • Runner work dir is ephemeral per job; secrets are masked in logs.
SECURITY
