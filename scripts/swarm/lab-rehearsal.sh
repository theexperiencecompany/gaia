#!/usr/bin/env bash
# Local Swarm rehearsal — mirrors the exact production setup from ops/prod-setup.md.
#
# What this does (same order as prod):
#   1. Create Multipass VM  (= GCP VM)
#   2. Install Docker
#   3. Generate SSH key + add to VM  (= adding your key to the server)
#   4. Add SSH config entry  (= ~/.ssh/config Host gaia-prod)
#   5. Create Docker context  (= docker context create gaia-prod)
#   6. docker swarm init
#   7. docker network create --driver overlay --attachable gaia-prod-shared
#   8. Create Swarm secrets  (= docker secret create ... -)
#   9. docker stack deploy -c infra/docker/docker-compose.prod.yml gaia-prod
#  10. Check services
#  11. Rollback drill
#
# Usage:
#   bash scripts/swarm/lab-rehearsal.sh [options]
#
# Secrets are read from env vars. Pass real ones for a full integration test,
# or leave unset to use placeholders (infra services will start; app services
# will fail Infisical auth — that's expected with fake creds).
#
#   INFISICAL_TOKEN=...
#   INFISICAL_MACHINE_IDENTITY_CLIENT_ID=...
#   INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET=...
#   INFISICAL_PROJECT_ID=...
#   METRICS_TOKEN=...
#
# Options:
#   --vm-name <name>       Multipass VM name          (default: gaia-swarm-lab)
#   --cpus <n>             VM CPUs                    (default: 4)
#   --memory <size>        VM memory                  (default: 8G)
#   --disk <size>          VM disk                    (default: 40G)
#   --ubuntu-image <ver>   Ubuntu release             (default: 22.04)
#   --ssh-key <path>       SSH private key to use     (default: ~/.ssh/gaia-lab)
#   --context-name <name>  Docker context name        (default: gaia-lab)
#   --skip-launch          Reuse existing VM
#   --skip-secrets         Skip secret creation
#   --skip-deploy          Skip stack deploy (just set up infra)
#   -h, --help             Show this help

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
VM_NAME="gaia-swarm-lab"
VM_CPUS="4"
VM_MEMORY="8G"
VM_DISK="40G"
UBUNTU_IMAGE="22.04"
SSH_KEY="$HOME/.ssh/gaia-lab"
CONTEXT_NAME="gaia-lab"
SKIP_LAUNCH="false"
SKIP_SECRETS="false"
SKIP_DEPLOY="false"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --vm-name)      VM_NAME="$2";      shift 2 ;;
    --cpus)         VM_CPUS="$2";      shift 2 ;;
    --memory)       VM_MEMORY="$2";    shift 2 ;;
    --disk)         VM_DISK="$2";      shift 2 ;;
    --ubuntu-image) UBUNTU_IMAGE="$2"; shift 2 ;;
    --ssh-key)      SSH_KEY="$2";      shift 2 ;;
    --context-name) CONTEXT_NAME="$2"; shift 2 ;;
    --skip-launch)  SKIP_LAUNCH="true"; shift ;;
    --skip-secrets) SKIP_SECRETS="true"; shift ;;
    --skip-deploy)  SKIP_DEPLOY="true"; shift ;;
    -h|--help) grep '^#' "$0" | grep -v '^#!/' | sed 's/^# \?//'; exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
ts()    { date +"%H:%M:%S"; }
log()   { printf '\n[%s] %s\n' "$(ts)" "$*"; }
ok()    { printf '[%s] ✓  %s\n' "$(ts)" "$*"; }
phase() {
  printf '\n'
  printf '═%.0s' {1..60}
  printf '\n[%s]  %s\n' "$(ts)" "$*"
  printf '═%.0s' {1..60}
  printf '\n'
}

# ---------------------------------------------------------------------------
# PHASE 1 — Provision VM
# ---------------------------------------------------------------------------
phase "1/8  Provision Multipass VM"

if [ "$SKIP_LAUNCH" = "true" ]; then
  log "Skipping VM launch (--skip-launch)"
  multipass start "$VM_NAME" 2>/dev/null || true
else
  if multipass info "$VM_NAME" >/dev/null 2>&1; then
    log "VM '$VM_NAME' already exists — starting"
    multipass start "$VM_NAME" 2>/dev/null || true
  else
    log "Launching $VM_NAME ($VM_CPUS vCPU · $VM_MEMORY · $VM_DISK · Ubuntu $UBUNTU_IMAGE)"
    multipass launch "$UBUNTU_IMAGE" \
      --name "$VM_NAME" \
      --cpus "$VM_CPUS" \
      --memory "$VM_MEMORY" \
      --disk "$VM_DISK"
  fi
fi

VM_IP=$(multipass info "$VM_NAME" --format json \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['$VM_NAME']['ipv4'][0])")
log "VM IP: $VM_IP"
ok "VM ready"

# ---------------------------------------------------------------------------
# PHASE 2 — Install Docker in VM
# ---------------------------------------------------------------------------
phase "2/8  Install Docker"

multipass exec "$VM_NAME" -- bash -s << 'INSTALL'
set -euo pipefail
if docker version >/dev/null 2>&1; then
  echo "Docker already installed: $(docker version --format '{{.Server.Version}}')"
  exit 0
fi
echo "Installing Docker..."
sudo apt-get update -qq
sudo apt-get install -y -qq docker.io
sudo usermod -aG docker ubuntu
sudo systemctl enable --now docker
echo "Docker installed: $(sudo docker version --format '{{.Server.Version}}')"
INSTALL
ok "Docker ready"

# ---------------------------------------------------------------------------
# PHASE 3 — SSH key setup  (mirrors: adding your pubkey to the server)
# ---------------------------------------------------------------------------
phase "3/8  SSH key setup"

if [ ! -f "$SSH_KEY" ]; then
  log "Generating SSH key at $SSH_KEY"
  ssh-keygen -t ed25519 -f "$SSH_KEY" -C "gaia-lab-ops" -N ""
fi
ok "SSH key: $SSH_KEY"

PUBKEY=$(cat "${SSH_KEY}.pub")
multipass exec "$VM_NAME" -- bash -c "
  mkdir -p ~/.ssh
  chmod 700 ~/.ssh
  grep -qxF '$PUBKEY' ~/.ssh/authorized_keys 2>/dev/null \
    || echo '$PUBKEY' >> ~/.ssh/authorized_keys
  chmod 600 ~/.ssh/authorized_keys
"
ok "Public key added to VM ubuntu user"

# ---------------------------------------------------------------------------
# PHASE 4 — SSH config  (mirrors: ~/.ssh/config Host gaia-prod)
# ---------------------------------------------------------------------------
phase "4/8  SSH config"

# Remove stale entry and add fresh one
TMPFILE=$(mktemp)
if [ -f ~/.ssh/config ]; then
  # Strip existing gaia-lab block if present
  awk "/^Host $CONTEXT_NAME$/{found=1} found && /^Host / && !/^Host $CONTEXT_NAME$/{found=0} !found" \
    ~/.ssh/config > "$TMPFILE"
else
  touch "$TMPFILE"
fi

cat >> "$TMPFILE" << EOF

Host $CONTEXT_NAME
  HostName $VM_IP
  User ubuntu
  IdentityFile $SSH_KEY
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
EOF

cp "$TMPFILE" ~/.ssh/config
rm "$TMPFILE"

# Wait for SSH to accept connections
log "Waiting for SSH..."
for i in $(seq 1 20); do
  ssh -o ConnectTimeout=2 "$CONTEXT_NAME" "echo ok" >/dev/null 2>&1 && break
  sleep 2
done
ssh "$CONTEXT_NAME" "echo ok" >/dev/null
ok "SSH config entry: Host $CONTEXT_NAME → $VM_IP"

# ---------------------------------------------------------------------------
# PHASE 5 — Docker context  (mirrors: docker context create gaia-prod)
# ---------------------------------------------------------------------------
phase "5/8  Docker context"

if docker context inspect "$CONTEXT_NAME" >/dev/null 2>&1; then
  log "Context '$CONTEXT_NAME' exists — removing and recreating"
  docker context rm "$CONTEXT_NAME" --force
fi

docker context create "$CONTEXT_NAME" \
  --docker "host=ssh://$CONTEXT_NAME" \
  --description "Multipass lab VM (mirrors gaia-prod)"

log "Testing context..."
docker --context "$CONTEXT_NAME" info --format "Docker {{.ServerVersion}} · Swarm: {{.Swarm.LocalNodeState}}"
ok "Context '$CONTEXT_NAME' ready"

# ---------------------------------------------------------------------------
# PHASE 6 — Swarm init + overlay network
# ---------------------------------------------------------------------------
phase "6/8  Swarm + network"

SWARM_STATE=$(docker --context "$CONTEXT_NAME" info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || echo "inactive")
if [ "$SWARM_STATE" = "active" ]; then
  log "Swarm already active"
else
  log "Initialising swarm..."
  docker --context "$CONTEXT_NAME" swarm init --advertise-addr "$VM_IP"
fi

NETWORK_EXISTS=$(docker --context "$CONTEXT_NAME" network ls \
  --filter name=gaia-prod-shared --format '{{.Name}}' 2>/dev/null || true)
if [ -n "$NETWORK_EXISTS" ]; then
  log "Overlay network already exists"
else
  log "Creating overlay network: gaia-prod-shared"
  docker --context "$CONTEXT_NAME" network create \
    --driver overlay --attachable gaia-prod-shared
fi
ok "Swarm active · network gaia-prod-shared ready"

# ---------------------------------------------------------------------------
# PHASE 7 — Swarm secrets  (mirrors: docker secret create ... -)
# ---------------------------------------------------------------------------
phase "7/8  Swarm secrets"

if [ "$SKIP_SECRETS" = "true" ]; then
  log "Skipping secret creation (--skip-secrets)"
else
  # Read from env vars — fall back to placeholder values if not set.
  # With placeholders, infra services start fine; app services will fail
  # Infisical auth (expected — use real creds for a full integration test).
  INFISICAL_TOKEN="${INFISICAL_TOKEN:-lab-placeholder-token}"
  INFISICAL_MACHINE_IDENTITY_CLIENT_ID="${INFISICAL_MACHINE_IDENTITY_CLIENT_ID:-lab-placeholder-client-id}"
  INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET="${INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET:-lab-placeholder-client-secret}"
  INFISICAL_PROJECT_ID="${INFISICAL_PROJECT_ID:-lab-placeholder-project-id}"
  METRICS_TOKEN="${METRICS_TOKEN:-lab-placeholder-metrics-token}"

  create_secret() {
    local name="$1" value="$2"
    if docker --context "$CONTEXT_NAME" secret inspect "$name" >/dev/null 2>&1; then
      log "  skip  $name (already exists)"
    else
      printf '%s' "$value" | docker --context "$CONTEXT_NAME" secret create "$name" - > /dev/null
      log "  ok    $name"
    fi
  }

  create_secret gaia_infisical_token                          "$INFISICAL_TOKEN"
  create_secret gaia_infisical_machine_identity_client_id     "$INFISICAL_MACHINE_IDENTITY_CLIENT_ID"
  create_secret gaia_infisical_machine_identity_client_secret "$INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET"
  create_secret gaia_infisical_project_id                     "$INFISICAL_PROJECT_ID"
  create_secret gaia_metrics_token                            "$METRICS_TOKEN"

  ok "Secrets created"
  docker --context "$CONTEXT_NAME" secret ls
fi

# ---------------------------------------------------------------------------
# PHASE 8 — Sync observability configs to VM
# ---------------------------------------------------------------------------
# docker stack deploy with bind mounts means paths must exist on the Swarm
# manager (the VM), not on the local Mac. We rsync the observability config
# files to a canonical path on the VM before deploying.
#
# In production the operator does the same with:
#   rsync -a infra/docker/observability/ gaia-prod:/opt/gaia/infra/docker/observability/
# ---------------------------------------------------------------------------
phase "8a/9  Sync observability configs"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VM_DOCKER_DIR="/opt/gaia/infra/docker"

ssh "$CONTEXT_NAME" "sudo mkdir -p '$VM_DOCKER_DIR/observability' && sudo chown -R ubuntu '$VM_DOCKER_DIR'"
rsync -a --exclude='*.example' --exclude='.gitignore' \
  "$REPO_ROOT/infra/docker/observability/" \
  "$CONTEXT_NAME:$VM_DOCKER_DIR/observability/"
ok "Observability configs synced to $VM_DOCKER_DIR/observability/"

# ---------------------------------------------------------------------------
# PHASE 9 — Deploy stack  (mirrors: the exact CI deploy command)
# ---------------------------------------------------------------------------
phase "9/9  Deploy stack"

if [ "$SKIP_DEPLOY" = "true" ]; then
  log "Skipping deploy (--skip-deploy)"
else
  # docker stack deploy resolves relative bind-mount paths using the compose
  # file's directory as root, then records them as absolute paths in the
  # service spec — so the Swarm manager VM must have those files at the same
  # absolute path.  We keep the compose file at its normal location and deploy
  # from REPO_ROOT so that ./observability/* resolves to
  # $REPO_ROOT/infra/docker/observability/* — but on the VM that path doesn't
  # exist.  To avoid forking the compose file we tell Docker the compose dir
  # is the VM path we just synced:
  #
  #   docker stack deploy -c <(sed ...) ...
  #
  # simplest: just cd to the synced dir on the VM and deploy locally there.
  # But we want to keep the remote-context pattern.  The cleanest workaround
  # is to run the deploy via SSH on the VM with a local context — which is
  # what prod ops actually does when you're already SSHed in.
  #
  # Lab note: this step validates the compose file syntax and Swarm config;
  # app services (gaia-backend, bots) will fail Infisical auth with placeholder
  # creds — that is expected.  Infra services (postgres, redis, chromadb,
  # rabbitmq) should converge cleanly.

  log "Deploying stack from VM (local context) so bind-mount paths resolve correctly..."
  rsync -a "$REPO_ROOT/infra/docker/docker-compose.prod.yml" \
    "$CONTEXT_NAME:$VM_DOCKER_DIR/docker-compose.prod.yml"

  ssh "$CONTEXT_NAME" "cd '$VM_DOCKER_DIR' && docker stack deploy \
    --with-registry-auth \
    -c docker-compose.prod.yml \
    gaia-prod"

  log "Waiting 45s for services to come up..."
  sleep 45

  echo ""
  log "Service status:"
  docker --context "$CONTEXT_NAME" stack services gaia-prod

  echo ""
  log "Service tasks:"
  for svc in gaia-backend arq_worker discord-bot slack-bot telegram-bot whatsapp-bot; do
    echo ""
    log "  gaia-prod_${svc}:"
    docker --context "$CONTEXT_NAME" service ps "gaia-prod_${svc}" \
      --format "table {{.Name}}\t{{.CurrentState}}\t{{.Error}}" 2>/dev/null || true
  done

  echo ""
  log "Infra service health (expected: Running):"
  for svc in postgres redis rabbitmq chromadb; do
    state=$(docker --context "$CONTEXT_NAME" service ps "gaia-prod_${svc}" \
      --filter desired-state=running \
      --format '{{.CurrentState}}' 2>/dev/null | head -1 || echo "unknown")
    printf '  %-20s %s\n' "${svc}:" "$state"
  done

  echo ""
  log "App service health (expected: failing Infisical auth with placeholder creds):"
  for svc in gaia-backend arq_worker discord-bot slack-bot telegram-bot whatsapp-bot; do
    state=$(docker --context "$CONTEXT_NAME" service ps "gaia-prod_${svc}" \
      --filter desired-state=running \
      --format '{{.CurrentState}}' 2>/dev/null | head -1 || echo "not started")
    printf '  %-20s %s\n' "${svc}:" "$state"
  done

  echo ""
  log "Rollback drill — rolling back gaia-backend..."
  docker --context "$CONTEXT_NAME" service rollback gaia-prod_gaia-backend 2>/dev/null || \
    log "  (rollback skipped — service may not have a previous revision yet)"

  echo ""
  log "Secrets present in Swarm:"
  docker --context "$CONTEXT_NAME" secret ls
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
phase "Complete"

cat << EOF

  Context is live. Use it exactly like you would gaia-prod:

    docker --context $CONTEXT_NAME stack services gaia-prod
    docker --context $CONTEXT_NAME service logs -f gaia-prod_gaia-backend
    docker --context $CONTEXT_NAME service ps gaia-prod_gaia-backend
    docker --context $CONTEXT_NAME secret ls

  Inspect a specific service:
    docker --context $CONTEXT_NAME service inspect --pretty gaia-prod_gaia-backend

  Force restart (rolling update):
    docker --context $CONTEXT_NAME service update --force gaia-prod_gaia-backend

  Rollback drill:
    docker --context $CONTEXT_NAME service rollback gaia-prod_gaia-backend

  Tear down:
    docker --context $CONTEXT_NAME stack rm gaia-prod
    docker context rm $CONTEXT_NAME --force
    multipass delete $VM_NAME && multipass purge
    # Remove Host $CONTEXT_NAME entry from ~/.ssh/config if desired

  Note: app services (gaia-backend, bots) will be in a restart loop with placeholder
  Infisical creds — that is expected.  Pass real env vars to test full auth:
    INFISICAL_TOKEN=... bash scripts/swarm/lab-rehearsal.sh --skip-launch --skip-secrets

EOF
