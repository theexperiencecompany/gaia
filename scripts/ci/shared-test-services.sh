#!/usr/bin/env bash
#
# shared-test-services.sh — ONE persistent set of service containers that every
# concurrent CI lane on this box shares, namespaced per lane.
#
# Why this exists: start-test-services.sh boots five containers per job. On the
# home box six jobs can run at once, so that is 30 containers — a measured
# 20-45s of boot time paid by every job, and ~15-22 GB of RAM against 24 GB of
# machine. The same five containers, started once and kept warm, cost ~0.6 GB
# and zero boot time per job. The containers are the same for every lane; what
# has to differ is the *namespace* each lane writes into:
#
#   Postgres  a database per lane        gaia_test_r<r>       (CREATE DATABASE)
#   Redis     a 32-DB stripe per lane    GAIA_REDIS_DB_BASE=8+r*32
#   MongoDB   a db-name prefix per lane  gaia_test_r<r>_gw<n>
#   ChromaDB  a collection suffix        _r<r>   (Chroma has no namespaces)
#   RabbitMQ  a vhost per lane           /r<r>
#
# Subcommands:
#   up            start the five containers if they are not already healthy
#   prepare <r>   create lane r's namespaces, write/export its env contract
#   reset <r>     destroy everything lane r created
#   janitor       reset every lane whose env file is older than STALE_HOURS
#
# `up` is idempotent: a lane's job can call it unconditionally and pay nothing
# when the containers are already running. The containers deliberately outlive
# the job (--restart unless-stopped), so nothing here removes them.
set -euo pipefail

# Fixed ports: there is exactly one shared set, so the per-runner port
# arithmetic in start-test-services.sh has nothing to disambiguate here.
POSTGRES_PORT="${GAIA_SHARED_POSTGRES_PORT:-5432}"
REDIS_PORT="${GAIA_SHARED_REDIS_PORT:-6379}"
MONGO_PORT="${GAIA_SHARED_MONGO_PORT:-27017}"
CHROMA_PORT="${GAIA_SHARED_CHROMA_PORT:-8000}"
RABBITMQ_PORT="${GAIA_SHARED_RABBITMQ_PORT:-5672}"

PG_NAME="gaia-shared-postgres"
REDIS_NAME="gaia-shared-redis"
MONGO_NAME="gaia-shared-mongo"
CHROMA_NAME="gaia-shared-chroma"
RABBITMQ_NAME="gaia-shared-rabbitmq"

# Same digest-pinned images as scripts/ci/start-test-services.sh — the shared
# topology must be bit-identical to the per-job one, or a lane that falls back
# to start-test-services.sh tests against different bits. Bump both together.
POSTGRES_IMAGE="postgres:16.14-alpine3.24@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
REDIS_IMAGE="redis:7.4.9-alpine3.21@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
MONGO_IMAGE="mongo:7.0.37@sha256:340c1c56fb10e95cf79ff547f8664b96bc6ead9909bc355238cbf865a9695a6f"
CHROMA_IMAGE="chromadb/chroma:1.5.9@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6"
RABBITMQ_IMAGE="rabbitmq:3.13.7-alpine@sha256:d7af1c87c5f1eda13fcfca06db452bf3aeab6619fc3358b68535c0c02c4e52bc"

READY_TIMEOUT_SECS=90
PULL_ATTEMPTS=5
PULL_BACKOFF_SECS=5

# Lanes are numbered 0..MAX_LANE; the Redis stripe arithmetic below assumes the
# server has (MAX_LANE+1)*32 + 32 databases (256 covers six lanes with room).
MAX_LANE=5
REDIS_DATABASES=256
REDIS_STRIPE=32
REDIS_BLOCK_START=8

# A lane whose env file has not been touched in this long is assumed dead (the
# job was cancelled, the runner rebooted) and is collected by `janitor`.
STALE_HOURS="${GAIA_SHARED_STALE_HOURS:-3}"

env_file_for() { echo "/tmp/gaia-test-services-$1.env"; }

die() {
  echo "::error::$*" >&2
  exit 1
}

validate_lane() {
  local lane="$1"
  [[ "$lane" =~ ^[0-9]+$ ]] || die "lane must be a non-negative integer, got '${lane}'"
  ((lane <= MAX_LANE)) || die "lane ${lane} exceeds MAX_LANE=${MAX_LANE}"
}

# --- container lifecycle ----------------------------------------------------

# Data on tmpfs with fsync off, exactly as start-test-services.sh does: these
# datasets are throwaway, and Postgres is commit-latency bound under xdist.
# Sized larger than the per-job containers because one Postgres now holds every
# lane's database at the same time.
start_postgres() {
  docker run -d --name "$PG_NAME" --restart unless-stopped \
    -e POSTGRES_USER=gaia -e POSTGRES_PASSWORD=gaia -e POSTGRES_DB=gaia_test \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=6g \
    -p "${POSTGRES_PORT}:5432" "$POSTGRES_IMAGE" \
    -c fsync=off -c synchronous_commit=off -c full_page_writes=off
}

# 256 logical databases: 32 per lane so lane r owns [8+r*32, 40+r*32) and
# tests/helpers.py:worker_redis_url can hand each xdist worker its own
# flushable DB inside that stripe without ever crossing into another lane.
start_redis() {
  docker run -d --name "$REDIS_NAME" --restart unless-stopped \
    -p "${REDIS_PORT}:6379" "$REDIS_IMAGE" \
    redis-server --databases "$REDIS_DATABASES" --save "" --appendonly no
}

start_mongo() {
  docker run -d --name "$MONGO_NAME" --restart unless-stopped \
    -e MONGO_INITDB_ROOT_USERNAME=gaia -e MONGO_INITDB_ROOT_PASSWORD=gaia \
    --tmpfs /data/db:rw,noexec,nosuid,size=6g \
    -p "${MONGO_PORT}:27017" "$MONGO_IMAGE"
}

start_chroma() {
  docker run -d --name "$CHROMA_NAME" --restart unless-stopped \
    -p "${CHROMA_PORT}:8000" "$CHROMA_IMAGE"
}

start_rabbitmq() {
  docker run -d --name "$RABBITMQ_NAME" --restart unless-stopped \
    -p "${RABBITMQ_PORT}:5672" "$RABBITMQ_IMAGE"
}

pull_with_retry() {
  local image="$1" attempt=1
  until docker pull --quiet "$image"; do
    if ((attempt >= PULL_ATTEMPTS)); then
      echo "::error::Failed to pull ${image} after ${PULL_ATTEMPTS} attempts"
      return 1
    fi
    echo "::warning::Pull of ${image} failed (attempt ${attempt}/${PULL_ATTEMPTS}) — retrying in ${PULL_BACKOFF_SECS}s"
    sleep "$PULL_BACKOFF_SECS"
    attempt=$((attempt + 1))
  done
}

# --- readiness probes (same shapes as start-test-services.sh) ---------------

pg_probe() { docker exec "$PG_NAME" pg_isready -U gaia -d gaia_test; }
redis_probe() { docker exec "$REDIS_NAME" redis-cli ping; }
mongo_probe() { docker exec "$MONGO_NAME" mongosh --quiet --eval "db.runCommand({ping:1}).ok"; }

# -u rabbitmq is load-bearing: the image has no USER directive, so a plain exec
# runs as root and creates a root-owned .erlang.cookie the server then cannot
# read (docker-library/rabbitmq#318).
rabbitmq_probe() { docker exec -u rabbitmq "$RABBITMQ_NAME" rabbitmq-diagnostics -q ping; }

# Chroma's heartbeat path moved between API v1 and v2; probe both so an image
# bump across that boundary can't silently break readiness.
chroma_probe() {
  curl -sf "http://localhost:${CHROMA_PORT}/api/v2/heartbeat" \
    || curl -sf "http://localhost:${CHROMA_PORT}/api/v1/heartbeat"
}

probe_until_deadline() {
  local deadline=$((SECONDS + READY_TIMEOUT_SECS))
  until "$@" >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then
      return 1
    fi
    sleep 1
  done
}

# wait_ready <label> <container> <start_fn> <probe...> — one timeout recreates
# the container and re-waits, so a boot flake costs ~90s instead of a red
# build; a second fails loud with the container's logs.
wait_ready() {
  local label="$1" container="$2" start_fn="$3"
  shift 3
  if probe_until_deadline "$@"; then
    echo "${label}: ready"
    return 0
  fi
  echo "::warning::${label} not ready after ${READY_TIMEOUT_SECS}s — recreating container once (boot flake)"
  docker logs "$container" 2>&1 | tail -50
  docker rm -f "$container" >/dev/null
  "$start_fn"
  if probe_until_deadline "$@"; then
    echo "${label}: ready (after one restart)"
    return 0
  fi
  echo "::error::${label} not ready after ${READY_TIMEOUT_SECS}s and one restart"
  docker logs "$container" 2>&1 | tail -50
  exit 1
}

container_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]
}

all_running() {
  local name
  for name in "$PG_NAME" "$REDIS_NAME" "$MONGO_NAME" "$CHROMA_NAME" "$RABBITMQ_NAME"; do
    container_running "$name" || return 1
  done
}

all_healthy() {
  all_running || return 1
  pg_probe >/dev/null 2>&1 || return 1
  redis_probe >/dev/null 2>&1 || return 1
  mongo_probe >/dev/null 2>&1 || return 1
  rabbitmq_probe >/dev/null 2>&1 || return 1
  chroma_probe >/dev/null 2>&1 || return 1
}

# --- subcommand: up ---------------------------------------------------------

cmd_up() {
  # The whole point is to pay nothing on the common path: every lane calls `up`
  # and only the first one on a cold box does any work.
  if all_healthy; then
    echo "Shared test services already healthy — nothing to do"
    return 0
  fi

  echo "::group::Pull service images (parallel)"
  local pull_pids=() pull_failed=0 image pid
  for image in "$POSTGRES_IMAGE" "$REDIS_IMAGE" "$MONGO_IMAGE" "$CHROMA_IMAGE" "$RABBITMQ_IMAGE"; do
    pull_with_retry "$image" &
    pull_pids+=("$!")
  done
  # A bare `wait` swallows background exit codes; wait on each PID so a pull
  # that exhausted its retries fails here instead of inside `docker run`.
  for pid in "${pull_pids[@]}"; do
    wait "$pid" || pull_failed=1
  done
  ((pull_failed == 0)) || die "One or more service images could not be pulled"
  echo "::endgroup::"

  # Start only what is missing. A container that exists but is stopped (box
  # rebooted mid-pull, someone ran `docker stop`) is removed and recreated
  # rather than started, so its flags always match this script.
  echo "::group::Start missing containers"
  local name start_fn
  for pair in \
    "$PG_NAME:start_postgres" \
    "$REDIS_NAME:start_redis" \
    "$MONGO_NAME:start_mongo" \
    "$CHROMA_NAME:start_chroma" \
    "$RABBITMQ_NAME:start_rabbitmq"; do
    name="${pair%%:*}"
    start_fn="${pair##*:}"
    if container_running "$name"; then
      echo "${name}: already running"
      continue
    fi
    docker rm -f "$name" >/dev/null 2>&1 || true
    "$start_fn"
  done
  echo "::endgroup::"

  echo "::group::Wait for readiness"
  wait_ready "PostgreSQL" "$PG_NAME" start_postgres pg_probe
  wait_ready "Redis" "$REDIS_NAME" start_redis redis_probe
  wait_ready "MongoDB" "$MONGO_NAME" start_mongo mongo_probe
  wait_ready "RabbitMQ" "$RABBITMQ_NAME" start_rabbitmq rabbitmq_probe
  wait_ready "ChromaDB" "$CHROMA_NAME" start_chroma chroma_probe
  echo "::endgroup::"
}

# --- subcommand: prepare ----------------------------------------------------

psql_exec() {
  docker exec "$PG_NAME" psql -U gaia -d postgres -tAc "$1"
}

cmd_prepare() {
  local lane="$1"
  validate_lane "$lane"
  all_running || die "shared services are not running — run '$0 up' first"

  local pg_db="gaia_test_r${lane}"
  local vhost="r${lane}"
  local redis_base=$((REDIS_BLOCK_START + lane * REDIS_STRIPE))
  local mongo_base="gaia_test_r${lane}"
  local chroma_suffix="_r${lane}"

  # CREATE DATABASE has no IF NOT EXISTS, and a lane re-preparing after a
  # cancelled job must not fail — so check first.
  if [ "$(psql_exec "SELECT 1 FROM pg_database WHERE datname='${pg_db}'")" != "1" ]; then
    psql_exec "CREATE DATABASE ${pg_db} OWNER gaia" >/dev/null
    echo "Postgres: created ${pg_db}"
  else
    echo "Postgres: ${pg_db} already exists"
  fi

  # add_vhost is idempotent in RabbitMQ; set_permissions is not conditional and
  # is cheap, so it is applied every time (it also repairs a half-made vhost).
  docker exec -u rabbitmq "$RABBITMQ_NAME" rabbitmqctl -q add_vhost "$vhost" \
    || echo "RabbitMQ: vhost ${vhost} already exists"
  docker exec -u rabbitmq "$RABBITMQ_NAME" rabbitmqctl -q \
    set_permissions -p "$vhost" guest ".*" ".*" ".*"
  echo "RabbitMQ: vhost ${vhost} ready"

  # Mongo and Chroma need no provisioning: a Mongo database and a Chroma
  # collection both spring into existence on first write. Only their names
  # have to be agreed, which is what this env file does.
  local env_file
  env_file="$(env_file_for "$lane")"
  cat > "$env_file" <<ENVEOF
DATABASE_URL=postgresql://gaia:gaia@localhost:${POSTGRES_PORT}/${pg_db}
POSTGRES_URL=postgresql://gaia:gaia@localhost:${POSTGRES_PORT}/${pg_db}
REDIS_URL=redis://localhost:${REDIS_PORT}/0
GAIA_REDIS_DB_BASE=${redis_base}
MONGODB_URL=mongodb://gaia:gaia@localhost:${MONGO_PORT}/${mongo_base}?authSource=admin
MONGO_DB=mongodb://gaia:gaia@localhost:${MONGO_PORT}/${mongo_base}?authSource=admin
MONGO_DB_NAME=${mongo_base}
GAIA_MONGO_DB_BASE=${mongo_base}
CHROMADB_HOST=localhost
CHROMADB_PORT=${CHROMA_PORT}
GAIA_CHROMA_COLLECTION_SUFFIX=${chroma_suffix}
RABBITMQ_URL=amqp://guest:guest@localhost:${RABBITMQ_PORT}/${vhost}
ENVEOF
  echo "Lane ${lane} env contract written to ${env_file}"

  if [ -n "${GITHUB_ENV:-}" ]; then
    cat "$env_file" >> "$GITHUB_ENV"
    echo "Published lane ${lane} service URLs to GITHUB_ENV"
  fi
}

# --- subcommand: reset ------------------------------------------------------

cmd_reset() {
  local lane="$1"
  validate_lane "$lane"
  all_running || die "shared services are not running — nothing to reset"

  local pg_db="gaia_test_r${lane}"
  local vhost="r${lane}"
  local redis_base=$((REDIS_BLOCK_START + lane * REDIS_STRIPE))
  local suffix="_r${lane}"

  # WITH (FORCE) terminates leftover backends from a cancelled job; without it
  # a single stuck connection makes the drop hang until the next janitor pass.
  psql_exec "DROP DATABASE IF EXISTS ${pg_db} WITH (FORCE)" >/dev/null \
    || echo "::warning::Postgres: dropping ${pg_db} failed"
  echo "Postgres: dropped ${pg_db}"

  # Flush the lane's whole 32-DB stripe, not just the 24 the workers use: a
  # stray key outside the block is still this lane's litter.
  local db
  for ((db = redis_base; db < redis_base + REDIS_STRIPE; db++)); do
    docker exec "$REDIS_NAME" redis-cli -n "$db" flushdb >/dev/null
  done
  echo "Redis: flushed DBs ${redis_base}-$((redis_base + REDIS_STRIPE - 1))"

  # Every worker database of this lane: gaia_test_r<lane>_gw0, _gw1, ...
  docker exec "$MONGO_NAME" mongosh --quiet \
    -u gaia -p gaia --authenticationDatabase admin \
    --eval "db.adminCommand({listDatabases:1,nameOnly:true}).databases
      .map(d => d.name)
      .filter(n => /^gaia_test_r${lane}_/.test(n))
      .forEach(n => { db.getSiblingDB(n).dropDatabase(); print('dropped ' + n); })"
  echo "MongoDB: dropped gaia_test_r${lane}_* databases"

  # Chroma has no namespace concept, so the lane's collections are identified
  # by the name suffix the app appended (GAIA_CHROMA_COLLECTION_SUFFIX) and
  # deleted one by one through the v2 REST API.
  reset_chroma "$suffix"

  docker exec -u rabbitmq "$RABBITMQ_NAME" rabbitmqctl -q delete_vhost "$vhost" \
    || echo "RabbitMQ: vhost ${vhost} was already absent"
  echo "RabbitMQ: deleted vhost ${vhost}"

  rm -f "$(env_file_for "$lane")"
}

# reset_chroma <suffix> — delete every collection whose name ends in <suffix>.
# python3 does the JSON parsing: the runner has it (it runs the pytest suite),
# and jq is not guaranteed to be installed.
reset_chroma() {
  local suffix="$1"
  local base="http://localhost:${CHROMA_PORT}/api/v2/tenants/default_tenant/databases/default_database/collections"
  local names
  names="$(curl -sf "${base}?limit=1000" \
    | python3 -c 'import json,sys
for c in json.load(sys.stdin):
    print(c["name"])' 2>/dev/null || true)"
  if [ -z "$names" ]; then
    echo "ChromaDB: no collections listed (empty server or v2 API unavailable)"
    return 0
  fi
  local name deleted=0
  while IFS= read -r name; do
    case "$name" in
      *"$suffix")
        curl -sf -X DELETE "${base}/${name}" >/dev/null \
          && deleted=$((deleted + 1)) \
          || echo "::warning::ChromaDB: failed to delete collection ${name}"
        ;;
    esac
  done <<< "$names"
  echo "ChromaDB: deleted ${deleted} collection(s) ending in ${suffix}"
}

# --- subcommand: janitor ----------------------------------------------------

# A cancelled job never runs its own reset, so its namespaces would accumulate
# until the box ran out of tmpfs. The env file's mtime is the liveness signal:
# `prepare` writes it at job start, and nothing outlives STALE_HOURS legitimately.
cmd_janitor() {
  all_running || die "shared services are not running — nothing to collect"
  local lane env_file swept=0
  for ((lane = 0; lane <= MAX_LANE; lane++)); do
    env_file="$(env_file_for "$lane")"
    [ -f "$env_file" ] || continue
    if [ -z "$(find "$env_file" -mmin "+$((STALE_HOURS * 60))" -print -quit)" ]; then
      continue
    fi
    echo "Lane ${lane}: env file older than ${STALE_HOURS}h — resetting"
    cmd_reset "$lane"
    swept=$((swept + 1))
  done
  echo "Janitor: reset ${swept} stale lane(s)"
}

# --- dispatch ---------------------------------------------------------------

usage() {
  cat >&2 <<'USAGE'
Usage: shared-test-services.sh <command> [lane]

  up            start the shared containers (no-op when already healthy)
  prepare <r>   create lane r's namespaces and write its env contract
  reset <r>     destroy everything lane r created
  janitor       reset every lane whose env file is stale
USAGE
  exit 2
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    up) cmd_up ;;
    prepare) [ $# -eq 2 ] || usage; cmd_prepare "$2" ;;
    reset) [ $# -eq 2 ] || usage; cmd_reset "$2" ;;
    janitor) cmd_janitor ;;
    *) usage ;;
  esac
}

main "$@"
