#!/usr/bin/env bash
# Local Swarm rehearsal — mirrors the exact production setup from ops/prod-setup.md.
#
# Uses OrbStack to create an amd64 Ubuntu VM (matching production architecture).
# OrbStack runs x86_64 via Rosetta on Apple Silicon — all GHCR images work natively.
#
# What this does (same order as prod):
#   1. Create OrbStack amd64 VM  (= GCP VM)
#   2. Install Docker
#   3. Create Docker context  (= docker context create gaia-prod)
#   4. docker swarm init + overlay network
#   5. Create Swarm secrets  (= docker secret create ... -)
#   6. Sync observability configs to VM
#   7. docker stack deploy -c infra/docker/docker-compose.prod.yml gaia-prod
#   8. Check services + rollback drill
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
#   --vm-name <name>       OrbStack VM name           (default: gaia-swarm-lab)
#   --ubuntu-version <ver> Ubuntu release              (default: 22.04)
#   --context-name <name>  Docker context name         (default: gaia-lab)
#   --skip-launch          Reuse existing VM
#   --skip-secrets         Skip secret creation
#   --skip-deploy          Skip stack deploy (just set up infra)
#   -h, --help             Show this help

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
VM_NAME="gaia-swarm-lab"
UBUNTU_VERSION="22.04"
CONTEXT_NAME="gaia-lab"
SKIP_LAUNCH="false"
SKIP_SECRETS="false"  # pragma: allowlist secret
SKIP_DEPLOY="false"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --vm-name)         VM_NAME="$2";         shift 2 ;;
    --ubuntu-version)  UBUNTU_VERSION="$2";  shift 2 ;;
    --context-name)    CONTEXT_NAME="$2";    shift 2 ;;
    --skip-launch)     SKIP_LAUNCH="true";   shift ;;
    --skip-secrets)    SKIP_SECRETS="true"; shift ;;  # pragma: allowlist secret
    --skip-deploy)     SKIP_DEPLOY="true";   shift ;;
    -h|--help) grep '^#' "$0" | grep -v '^#!/' | sed 's/^# \?//'; exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# OrbStack SSH host — used for ssh, rsync, and docker context
SSH_HOST="$VM_NAME@orb"

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
# Pre-flight: check OrbStack is available
# ---------------------------------------------------------------------------
if ! command -v orbctl &>/dev/null; then
  echo "ERROR: OrbStack not found. Install from https://orbstack.dev" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Pre-flight: check VM disk space (Swarm Raft WAL needs at least 2 GB free)
# ---------------------------------------------------------------------------
check_vm_disk() {
  local avail_kb
  avail_kb=$(orb -m "$VM_NAME" df -k / 2>/dev/null | awk 'NR==2 {print $4}')
  local avail_gb=$(( avail_kb / 1024 / 1024 ))
  if [ "$avail_gb" -lt 2 ]; then
    echo "ERROR: VM has only ${avail_gb}GB free on /. Swarm needs ≥2 GB." >&2
    echo "Free space with: orb -m $VM_NAME docker system prune -af --volumes" >&2
    exit 1
  fi
  log "VM disk: ${avail_gb}GB free on /"
}

# ---------------------------------------------------------------------------
# PHASE 1 — Provision amd64 VM via OrbStack
# ---------------------------------------------------------------------------
phase "1/7  Provision OrbStack amd64 VM"

if [ "$SKIP_LAUNCH" = "true" ]; then
  log "Skipping VM creation (--skip-launch)"
  # Ensure it's running
  orbctl start "$VM_NAME" 2>/dev/null || true
else
  # Check if VM already exists
  if orbctl info "$VM_NAME" &>/dev/null; then
    log "VM '$VM_NAME' already exists — starting"
    orbctl start "$VM_NAME" 2>/dev/null || true
  else
    log "Creating $VM_NAME (amd64 · Ubuntu $UBUNTU_VERSION via Rosetta)"
    orbctl create -a amd64 "ubuntu:$UBUNTU_VERSION" "$VM_NAME"
  fi
fi

# Verify architecture
VM_ARCH=$(orb -m "$VM_NAME" uname -m 2>/dev/null)
VM_IP=$(orbctl info "$VM_NAME" 2>/dev/null | grep 'IPv4:' | awk '{print $2}')
log "VM IP: $VM_IP  Arch: $VM_ARCH"

if [ "$VM_ARCH" != "x86_64" ]; then
  echo "ERROR: VM architecture is $VM_ARCH, expected x86_64. Recreate with: orbctl delete $VM_NAME && orbctl create -a amd64 ubuntu:$UBUNTU_VERSION $VM_NAME" >&2
  exit 1
fi
ok "VM ready (amd64/x86_64)"

check_vm_disk

# ---------------------------------------------------------------------------
# PHASE 2 — Install Docker in VM
# ---------------------------------------------------------------------------
phase "2/7  Install Docker"

orb -m "$VM_NAME" -u root bash -s << 'INSTALL'
set -euo pipefail
if docker version >/dev/null 2>&1; then
  echo "Docker already installed: $(docker version --format '{{.Server.Version}}')"
  exit 0
fi
echo "Installing Docker + rsync..."
apt-get update -qq
apt-get install -y -qq docker.io rsync
# Add the default user to the docker group
DEFAULT_USER=$(getent passwd 1000 | cut -d: -f1)
usermod -aG docker "$DEFAULT_USER"
systemctl enable --now docker
echo "Docker installed: $(docker version --format '{{.Server.Version}}')"
INSTALL

# Verify docker works as the normal user (may need newgrp)
orb -m "$VM_NAME" docker version --format '{{.Server.Version}}' >/dev/null 2>&1 || {
  log "Refreshing group membership..."
  orb -m "$VM_NAME" -u root bash -c "su - \$(getent passwd 1000 | cut -d: -f1) -c 'docker version'" >/dev/null
}
ok "Docker ready"

# ---------------------------------------------------------------------------
# PHASE 3 — Docker context  (mirrors: docker context create gaia-prod)
# ---------------------------------------------------------------------------
phase "3/7  Docker context"

# OrbStack VMs are reachable via SSH at VMNAME@orb — no key setup needed
if docker context inspect "$CONTEXT_NAME" >/dev/null 2>&1; then
  log "Context '$CONTEXT_NAME' exists — removing and recreating"
  docker context rm "$CONTEXT_NAME" --force
fi

docker context create "$CONTEXT_NAME" \
  --docker "host=ssh://$SSH_HOST" \
  --description "OrbStack amd64 lab VM (mirrors gaia-prod)"

log "Testing context..."
docker --context "$CONTEXT_NAME" info --format "Docker {{.ServerVersion}} · Swarm: {{.Swarm.LocalNodeState}} · Arch: {{.Architecture}}"
ok "Context '$CONTEXT_NAME' ready"

# ---------------------------------------------------------------------------
# PHASE 4 — Swarm init + overlay network
# ---------------------------------------------------------------------------
phase "4/7  Swarm + network"

if docker --context "$CONTEXT_NAME" node ls >/dev/null 2>&1; then
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
# PHASE 5 — Swarm secrets  (mirrors: docker secret create ... -)
# ---------------------------------------------------------------------------
phase "5/7  Swarm secrets"

if [ "$SKIP_SECRETS" = "true" ]; then  # pragma: allowlist secret
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
# PHASE 6 — Sync configs + create placeholder .env files
# ---------------------------------------------------------------------------
# docker stack deploy with bind mounts means paths must exist on the Swarm
# manager (the VM), not on the local Mac. We sync the observability config
# files and create placeholder .env files on the VM before deploying.
#
# In production the operator does the same with:
#   rsync -a infra/docker/observability/ gaia-prod:/opt/gaia/infra/docker/observability/
# ---------------------------------------------------------------------------
phase "6/7  Sync configs to VM"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VM_DOCKER_DIR="/opt/gaia/infra/docker"

ssh "$SSH_HOST" "sudo mkdir -p '$VM_DOCKER_DIR/observability' /opt/gaia/apps/api /opt/gaia/apps/bots && \
  sudo chown -R \$(whoami) /opt/gaia"

rsync -a --exclude='*.example' --exclude='.gitignore' \
  "$REPO_ROOT/infra/docker/observability/" \
  "$SSH_HOST:$VM_DOCKER_DIR/observability/"
ok "Observability configs synced"

# env_file paths in the compose file are relative to the compose file's dir.
# On the VM, ../../apps/api/.env resolves to /opt/gaia/apps/api/.env etc.
# Create empty placeholders so docker stack deploy doesn't error.
# (In production these are real .env files; Swarm secrets handle the actual values.)
ssh "$SSH_HOST" "touch /opt/gaia/apps/api/.env /opt/gaia/apps/bots/.env /opt/gaia/infra/docker/.env"
ok "Placeholder .env files created"

rsync -a "$REPO_ROOT/infra/docker/docker-compose.prod.yml" \
  "$SSH_HOST:$VM_DOCKER_DIR/docker-compose.prod.yml"
ok "Compose file synced"

# ---------------------------------------------------------------------------
# PHASE 7 — Deploy stack  (mirrors: the exact CI deploy command)
# ---------------------------------------------------------------------------
phase "7/7  Deploy stack"

if [ "$SKIP_DEPLOY" = "true" ]; then
  log "Skipping deploy (--skip-deploy)"
else
  # Deploy from the VM so bind-mount paths resolve correctly.
  # Lab note: app services (gaia-backend, bots) will fail Infisical auth
  # with placeholder creds — that is expected. Infra services (postgres,
  # redis, chromadb, rabbitmq) should converge cleanly.

  log "Deploying stack from VM (local context) so bind-mount paths resolve correctly..."
  # Retry once — fresh swarm Raft consensus can briefly reject API calls.
  deploy_stack() {
    ssh "$SSH_HOST" "cd '$VM_DOCKER_DIR' && docker stack deploy \
      --with-registry-auth \
      -c docker-compose.prod.yml \
      gaia-prod"
  }
  if ! deploy_stack; then
    log "  First deploy attempt failed (transient Raft state) — retrying in 5s..."
    sleep 5
    deploy_stack
  fi

  log "Waiting 90s for images to pull and services to start..."
  sleep 90

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
  for svc in postgres redis rabbitmq chromadb loki prometheus grafana promtail; do
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

  SSH into the VM:
    ssh $SSH_HOST

  Tear down:
    docker --context $CONTEXT_NAME stack rm gaia-prod
    docker context rm $CONTEXT_NAME --force
    orbctl delete $VM_NAME

  Note: app services (gaia-backend, bots) will be in a restart loop with placeholder
  Infisical creds — that is expected.  Pass real env vars to test full auth:
    INFISICAL_TOKEN=... bash scripts/swarm/lab-rehearsal.sh --skip-launch --skip-secrets

EOF
