#!/usr/bin/env bash
#
# Bring up GAIA's backing services on a machine with no Docker daemon.
#
# Cloud sandboxes (Claude Code on the web, CI runners, dev containers) usually
# have no /var/run/docker.sock, so `docker compose up` in infra/docker/ is not
# an option. Everything here installs and runs natively instead, pinned to the
# same major versions we ship in prod (the prod compose lives in gaia-infra).
#
#   ./scripts/dev/sandbox-services.sh up      # install (if needed) + start
#   ./scripts/dev/sandbox-services.sh status  # per-service port probe
#   ./scripts/dev/sandbox-services.sh seed    # minimum rows required to boot
#   ./scripts/dev/sandbox-services.sh down    # stop
#
# After `up` and `seed`, apps/api boots with scripts/dev/sandbox-env.sh.
#
# Requires root (apt-get + /usr/local/bin). Idempotent: re-running is safe.
set -euo pipefail

MONGO_VERSION="8.0.4"
MONGO_DATA="${MONGO_DATA:-/var/lib/gaia-mongo}"
CHROMA_DATA="${CHROMA_DATA:-/var/lib/gaia-chroma}"
REDIS_DATA="${REDIS_DATA:-/var/lib/gaia-redis}"
RUN_DIR="${RUN_DIR:-/var/log/gaia-sandbox}"
API_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../apps/api" && pwd)"

log() { printf '\033[36m[sandbox]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[sandbox] %s\033[0m\n' "$*" >&2; exit 1; }

port_open() { python3 -c "
import socket,sys
s=socket.socket(); s.settimeout(2)
sys.exit(0 if s.connect_ex(('127.0.0.1',$1))==0 else 1)"; }

wait_for_port() {
  local port=$1 name=$2 tries=${3:-30}
  for _ in $(seq "$tries"); do
    port_open "$port" && { log "$name ready on $port"; return 0; }
    sleep 2
  done
  die "$name never opened port $port — check $RUN_DIR/$name.log"
}

install_mongo() {
  command -v mongod >/dev/null && return 0
  log "installing mongod $MONGO_VERSION (no apt package on noble; official tarball)"
  local tmp url
  tmp="$(mktemp -d)"
  url="https://fastdl.mongodb.org/linux/mongodb-linux-x86_64-ubuntu2404-${MONGO_VERSION}.tgz"
  curl -sL --proto '=https' --proto-redir '=https' -o "$tmp/mongo.tgz" "$url" || die "mongod download failed: $url"
  tar xzf "$tmp/mongo.tgz" -C "$tmp"
  cp -f "$tmp"/mongodb-linux-*/bin/mongod /usr/local/bin/mongod
  chmod +x /usr/local/bin/mongod
  rm -rf "$tmp"
}

install_apt_services() {
  local missing=()
  command -v redis-server   >/dev/null || missing+=(redis-server)
  command -v rabbitmq-server >/dev/null || missing+=(rabbitmq-server)
  command -v psql           >/dev/null || missing+=(postgresql)
  [ ${#missing[@]} -eq 0 ] && return 0
  log "apt-get install: ${missing[*]}"
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}"
}

start_all() {
  mkdir -p "$MONGO_DATA" "$CHROMA_DATA" "$RUN_DIR"

  port_open 27017 || {
    log "starting mongod"
    mongod --dbpath "$MONGO_DATA" --bind_ip 127.0.0.1 --port 27017 \
           --fork --logpath "$RUN_DIR/mongod.log"
  }
  wait_for_port 27017 mongod

  # --dir matters: redis snapshots to $PWD/dump.rdb by default, so starting it
  # from a checkout drops a binary dump into the working tree that a careless
  # `git add -A` will happily commit.
  port_open 6379 || {
    log "starting redis"
    mkdir -p "$REDIS_DATA"
    redis-server --port 6379 --daemonize yes --dir "$REDIS_DATA"
  }
  wait_for_port 6379 redis

  # RabbitMQ must NOT run as root: the server refuses a root-owned
  # .erlang.cookie, and a root-owned log path makes it die with
  # {cannot_log_to_file, eacces}. Run as the packaged rabbitmq user and let it
  # use its own default log dir. Same class of bug as the docker-library
  # #318 issue documented in .github/CLAUDE.md.
  port_open 5672 || {
    log "starting rabbitmq (as user rabbitmq)"
    su -s /bin/bash rabbitmq -c "rabbitmq-server -detached"
  }
  wait_for_port 5672 rabbitmq 45

  port_open 5432 || {
    log "starting postgres"
    pg_ctlcluster "$(ls /etc/postgresql | head -1)" main start || true
  }
  port_open 5432 && log "postgres ready on 5432" || log "postgres NOT running (optional: only langgraph checkpointing needs it)"

  # Chroma ships as a Python package in the API venv — no container needed.
  port_open 8080 || {
    log "starting chromadb"
    (cd "$API_DIR" && nohup uv run chroma run --host 127.0.0.1 --port 8080 \
       --path "$CHROMA_DATA" > "$RUN_DIR/chroma.log" 2>&1 &)
  }
  wait_for_port 8080 chromadb 45
}

# The API refuses to boot until subscription plans exist
# (app/services/startup_validation.py, strategy=ERROR). A plain count,
# so one row is enough to clear the gate.
#
# NOTE: the database is "GAIA", NOT the path in MONGO_DB. Seeding the URI's
# database looks like it works and leaves startup_validation still failing.
seed_mongo() {
  log "seeding GAIA.subscription_plans"
  (cd "$API_DIR" && uv run --no-build python - <<'PY'
from pymongo import MongoClient

db = MongoClient("mongodb://localhost:27017/")["GAIA"]
if db.subscription_plans.count_documents({}) == 0:
    db.subscription_plans.insert_one({
        "plan_id": "free", "name": "Free", "amount": 0,
        "currency": "USD", "is_active": True,
    })
print(f"subscription_plans={db.subscription_plans.count_documents({})}")
PY
  )
}

status_all() {
  for pair in "27017 mongod" "6379 redis" "5672 rabbitmq" "5432 postgres" "8080 chromadb"; do
    set -- $pair
    port_open "$1" && printf '  %-10s %-8s UP\n' "$2" "$1" || printf '  %-10s %-8s DOWN\n' "$2" "$1"
  done
}

case "${1:-up}" in
  up)
    [ "$(id -u)" -eq 0 ] || die "run as root (apt-get + /usr/local/bin)"
    install_apt_services
    install_mongo
    start_all
    log "all services up — now: $0 seed"
    ;;
  seed)   seed_mongo ;;
  status) status_all ;;
  down)
    pkill -x mongod || true
    redis-cli shutdown nosave 2>/dev/null || true
    su -s /bin/bash rabbitmq -c "rabbitmqctl stop" 2>/dev/null || true
    pkill -f "chroma run" || true
    log "stopped (postgres left running — pg_ctlcluster stop it manually)"
    ;;
  *) die "usage: $0 {up|seed|status|down}" ;;
esac
