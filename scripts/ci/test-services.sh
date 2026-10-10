#!/usr/bin/env bash
#
# test-services.sh — the PostgreSQL/Redis/MongoDB/ChromaDB/RabbitMQ topology the
# API pytest suite runs against, on whichever runner it lands on.
#
# Subcommands:
#   up            make the services exist and be ready (idempotent)
#   prepare [r]   claim lane r's namespace, clean it, write/export its env
#                 contract. Defaults to $RUNNER_INDEX.
#   reset [r]     release lane r's namespace. Never fails a green lane.
#   down          what a lane's `if: always()` teardown calls: reset on the box,
#                 remove this job's containers on a GitHub-hosted runner.
#   janitor       reset every lane whose env file is older than STALE_HOURS
#                 (self-hosted only; a GitHub-hosted runner is thrown away).
#
# The script decides for itself which topology it is on — callers never choose:
#
#   self-hosted ($RUNNER_ENVIRONMENT)  ONE persistent set of containers per box,
#                                      namespaced per lane by $RUNNER_INDEX.
#   GitHub-hosted                      five containers for this job alone, host
#                                      ports offset by $RUNNER_INDEX * 100.
#
# Why the shared set on the box: five containers per job × six concurrent jobs
# is 30 containers — a measured 20-45s of boot paid by every job and ~15-22 GB
# of RAM. The same five kept warm cost ~0.6 GB and zero boot time; only the
# NAMESPACE each lane writes into has to differ:
#
#   Postgres  a database per lane        gaia_test_r<r>       (CREATE DATABASE)
#   Redis     a 32-DB stripe per lane    GAIA_REDIS_DB_BASE=8+r*32
#   MongoDB   a db-name prefix per lane  gaia_test_r<r>_gw<n>
#   ChromaDB  a collection suffix        _r<r>   (Chroma has no namespaces)
#   RabbitMQ  a vhost per lane           /r<r>
#
# Plain `docker run`, never GitHub `services:`, because Redis needs a command
# override (--databases, for pytest-xdist worker isolation) that service
# containers cannot express.
#
# Env contract:
#   RUNNER_ENVIRONMENT      "self-hosted" selects the shared topology.
#   RUNNER_INDEX            lane number / port offset (default 0).
#   GAIA_CI_RUNDIR,
#   RUNNER_LOCAL_CACHE      where the per-lane env file and the lock live.
#   GAIA_TEST_SERVICES_ENV  override the env file path (per-job mode).
#   GAIA_SHARED_*_PORT      shared-set host ports.
#   GAIA_SHARED_PG_MAX_CONNECTIONS, GAIA_SHARED_PG_SHARED_BUFFERS
#   GAIA_SHARED_STALE_HOURS janitor threshold (default 3).
#   GITHUB_ENV              when set, `prepare` publishes the endpoints to it.
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"
# shellcheck source=scripts/ci/lib/service-images.sh
source "$(dirname "$0")/lib/service-images.sh"

READY_TIMEOUT_SECS=90
PULL_ATTEMPTS=5
PULL_BACKOFF_SECS=5

# Lanes are numbered 0..MAX_LANE; the Redis stripe arithmetic below assumes the
# server has (MAX_LANE+1)*32 + 32 databases (448 covers twelve lanes with room).
MAX_LANE=12  # lanes 0-12: Redis --databases 448 holds 13 stripes of 32 above DB 8; RUNNER_INDEX 1-12 map directly
REDIS_DATABASES=448
REDIS_STRIPE=32
REDIS_BLOCK_START=8

# A lane whose env file has not been touched in this long is assumed dead (the
# job was cancelled, the runner rebooted) and is collected by `janitor`.
STALE_HOURS="${GAIA_SHARED_STALE_HOURS:-3}"

# One Postgres serves every lane. Per-job containers run with
# max_connections=300; here (MAX_LANE+1) lanes each hold up to ~24 xdist workers
# × a few pooled connections at once, so the per-lane figure scaled by lane
# count is the floor. 1200 is that with headroom; the default 100 was the first
# thing to go under two lanes. shared_buffers is raised to match (the default
# 128MB is a single-database figure); the datadir is tmpfs so there is no I/O to
# hide behind anyway.
PG_MAX_CONNECTIONS="${GAIA_SHARED_PG_MAX_CONNECTIONS:-1200}"
PG_SHARED_BUFFERS="${GAIA_SHARED_PG_SHARED_BUFFERS:-512MB}"

# max_connections for a per-job Postgres: the default 100 is a single-client
# default, and this suite is not one client. `pytest -n auto` gives a worker per
# core, and each worker can hold the app engine (pool_size=5 + max_overflow=10)
# AND the checkpointer pool (max_size=20) at once — 35 apiece before the
# per-test NullPool engines the real-services memory tests open. Four workers
# already exceed 100, which is why the suite met "sorry, too many clients
# already" as it grew rather than on any one change. Slots are a few KB each.
PERJOB_PG_MAX_CONNECTIONS=300
# 32 logical databases so each pytest-xdist worker gets an isolated Redis DB.
PERJOB_REDIS_DATABASES=32

# Per-user run dir for the per-lane env files (same rule in
# embedding-sidecar.sh, the runner hooks and setup-python-test-env):
# GitHub-hosted has no RUNNER_LOCAL_CACHE and keeps /tmp; on the box each runner
# user gets its own.
RUNDIR="${GAIA_CI_RUNDIR:-${RUNNER_LOCAL_CACHE:-/tmp}}"
[ -d "$RUNDIR" ] || RUNDIR=/tmp

# `up` runs under a lock. Every lane calls it at job start, so on a cold box
# several arrive together, all see "unhealthy", and all try to `docker rm -f`
# + `docker run` the same container name — every loser fails its job on a
# name conflict. flock makes the first one do the work and the rest find it
# healthy. The lock file sits in the runner-local cache when there is one
# (per box, persistent), else /tmp.
LOCK_FILE="${RUNDIR}/gaia-shared-test-services.lock"
LOCK_WAIT_SECS=600

env_file_for() { echo "${RUNDIR}/gaia-test-services-$1.env"; }

# ── which topology are we on? ─────────────────────────────────────────────
# RUNNER_ENVIRONMENT is set by the Actions runner itself ("self-hosted" on the
# box, "github-hosted" on a GitHub VM); RUNNER_INDEX comes from each instance's
# .env (gaia-infra:self-hosted-runner/setup.sh). Exactly the signals the
# separate scripts keyed off before they were merged.
on_the_box() { [[ "${RUNNER_ENVIRONMENT:-}" == "self-hosted" ]]; }

lane_of() {
  local lane="${1:-${RUNNER_INDEX:-0}}"
  [[ "$lane" =~ ^[0-9]+$ ]] || ci_die "lane must be a non-negative integer, got '${lane}'"
  ((lane <= MAX_LANE)) || ci_die "lane ${lane} exceeds MAX_LANE=${MAX_LANE}"
  echo "$lane"
}

# Names and host ports differ per topology; everything below reads these.
set_topology() {
  if on_the_box; then
    # Fixed ports: there is exactly one shared set, so the per-runner port
    # arithmetic has nothing to disambiguate here. High, non-standard host
    # ports: the home box runs its own Postgres/Redis/Mongo/RabbitMQ/Chroma
    # alongside CI (5432/6379/27017/5672/8000 are taken, and so are
    # 15432/15673), and the per-job CI containers use <base>+index*100 below
    # 10000. Surveyed free on 2026-08-28: 25432 16379 37017 18000 25673.
    POSTGRES_PORT="${GAIA_SHARED_POSTGRES_PORT:-25432}"
    REDIS_PORT="${GAIA_SHARED_REDIS_PORT:-16379}"
    MONGO_PORT="${GAIA_SHARED_MONGO_PORT:-37017}"
    CHROMA_PORT="${GAIA_SHARED_CHROMA_PORT:-18000}"
    RABBITMQ_PORT="${GAIA_SHARED_RABBITMQ_PORT:-25673}"
    PG_NAME="gaia-shared-postgres"
    REDIS_NAME="gaia-shared-redis"
    MONGO_NAME="gaia-shared-mongo"
    CHROMA_NAME="gaia-shared-chroma"
    RABBITMQ_NAME="gaia-shared-rabbitmq"
  else
    # Per-runner isolation: fixed host ports would make a second concurrent
    # lane fail on "port is already allocated". RUNNER_INDEX offsets every
    # host port by index*100 and suffixes every container name; GitHub-hosted
    # runners have no RUNNER_INDEX, so they default to 0 and keep the
    # canonical ports.
    local idx offset
    idx="${RUNNER_INDEX:-0}"
    offset=$((idx * 100))
    POSTGRES_PORT=$((5432 + offset))
    REDIS_PORT=$((6379 + offset))
    MONGO_PORT=$((27017 + offset))
    CHROMA_PORT=$((8000 + offset))
    RABBITMQ_PORT=$((5672 + offset))
    PG_NAME="gaia-test-postgres-${idx}"
    REDIS_NAME="gaia-test-redis-${idx}"
    MONGO_NAME="gaia-test-mongo-${idx}"
    CHROMA_NAME="gaia-test-chroma-${idx}"
    RABBITMQ_NAME="gaia-test-rabbitmq-${idx}"
  fi
}

# ── container lifecycle ───────────────────────────────────────────────────
# Data on tmpfs with fsync off: these datasets are thrown away, so durability
# buys nothing and fsync costs real time — Postgres in particular is
# commit-latency bound under a 16-way xdist run. The shared set is sized larger
# because one Postgres now holds every lane's database at the same time.
#
# CONFIG FINGERPRINT: every container is labelled with a hash of the exact image
# digest and flags it was started with. `up` recreates a running container whose
# label no longer matches, so bumping max_connections or --databases actually
# reconciles instead of silently keeping a container started under the old
# values (which is how a box could serve a suite that needed 1200 connections
# from a Postgres still running with 300).
CONFIG_LABEL="gaia.ci.config"

_fingerprint() { printf '%s' "$*" | sha256sum | cut -c1-16; }

_run_labelled() {
  # _run_labelled <name> <fingerprint-source> <docker run args...>
  local name="$1" spec="$2"
  shift 2
  docker run -d --name "$name" --label "${CONFIG_LABEL}=$(_fingerprint "$spec")" "$@"
}

_pg_spec() {
  if on_the_box; then
    echo "${POSTGRES_IMAGE}|shared|${POSTGRES_PORT}|max_connections=${PG_MAX_CONNECTIONS}|shared_buffers=${PG_SHARED_BUFFERS}|tmpfs=6g"
  else
    echo "${POSTGRES_IMAGE}|perjob|${POSTGRES_PORT}|max_connections=${PERJOB_PG_MAX_CONNECTIONS}|tmpfs=2g"
  fi
}

start_postgres() {
  if on_the_box; then
    _run_labelled "$PG_NAME" "$(_pg_spec)" --restart unless-stopped \
      -e POSTGRES_USER=gaia -e POSTGRES_PASSWORD=gaia -e POSTGRES_DB=gaia_test \
      -e PGDATA=/var/lib/postgresql/data/pgdata \
      --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=6g \
      -p "127.0.0.1:${POSTGRES_PORT}:5432" "$POSTGRES_IMAGE" \
      -c fsync=off -c synchronous_commit=off -c full_page_writes=off \
      -c "max_connections=${PG_MAX_CONNECTIONS}" -c "shared_buffers=${PG_SHARED_BUFFERS}"
  else
    _run_labelled "$PG_NAME" "$(_pg_spec)" \
      -e POSTGRES_USER=gaia -e POSTGRES_PASSWORD=gaia -e POSTGRES_DB=gaia_test \
      -e PGDATA=/var/lib/postgresql/data/pgdata \
      --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=2g \
      -p "127.0.0.1:${POSTGRES_PORT}:5432" "$POSTGRES_IMAGE" \
      -c "max_connections=${PERJOB_PG_MAX_CONNECTIONS}" \
      -c fsync=off -c synchronous_commit=off -c full_page_writes=off
  fi
}

# Shared: 448 logical databases, 32 per lane, so lane r owns
# [8+r*32, 40+r*32) and tests/helpers.py:worker_redis_url can hand each xdist
# worker its own flushable DB inside that stripe without ever crossing into
# another lane. Per-job: 32, one per worker.
# --save "" disables RDB snapshotting: the dataset is discarded with the
# container, and the fork-to-disk pauses only add latency.
_redis_databases() { if on_the_box; then echo "$REDIS_DATABASES"; else echo "$PERJOB_REDIS_DATABASES"; fi; }
_redis_spec() { echo "${REDIS_IMAGE}|${REDIS_PORT}|databases=$(_redis_databases)"; }

start_redis() {
  local restart=()
  on_the_box && restart=(--restart unless-stopped)
  _run_labelled "$REDIS_NAME" "$(_redis_spec)" "${restart[@]}" \
    -p "127.0.0.1:${REDIS_PORT}:6379" "$REDIS_IMAGE" \
    redis-server --databases "$(_redis_databases)" --save "" --appendonly no
}

_mongo_tmpfs() { if on_the_box; then echo 6g; else echo 2g; fi; }
_mongo_spec() { echo "${MONGO_IMAGE}|${MONGO_PORT}|tmpfs=$(_mongo_tmpfs)"; }

start_mongo() {
  local restart=()
  on_the_box && restart=(--restart unless-stopped)
  _run_labelled "$MONGO_NAME" "$(_mongo_spec)" "${restart[@]}" \
    -e MONGO_INITDB_ROOT_USERNAME=gaia -e MONGO_INITDB_ROOT_PASSWORD=gaia \
    --tmpfs "/data/db:rw,noexec,nosuid,size=$(_mongo_tmpfs)" \
    -p "127.0.0.1:${MONGO_PORT}:27017" "$MONGO_IMAGE"
}

_chroma_spec() { echo "${CHROMA_IMAGE}|${CHROMA_PORT}"; }

start_chroma() {
  local restart=()
  on_the_box && restart=(--restart unless-stopped)
  _run_labelled "$CHROMA_NAME" "$(_chroma_spec)" "${restart[@]}" \
    -p "127.0.0.1:${CHROMA_PORT}:8000" "$CHROMA_IMAGE"
}

_rabbitmq_spec() { echo "${RABBITMQ_IMAGE}|${RABBITMQ_PORT}"; }

start_rabbitmq() {
  local restart=()
  on_the_box && restart=(--restart unless-stopped)
  _run_labelled "$RABBITMQ_NAME" "$(_rabbitmq_spec)" "${restart[@]}" \
    -p "127.0.0.1:${RABBITMQ_PORT}:5672" "$RABBITMQ_IMAGE"
}

# Docker Hub pulls flake — the registry times out or rate-limits transiently.
# One unlucky pull would otherwise surface much later as an opaque `docker run`
# exit 125, so retry each pull with backoff before giving up.
pull_with_retry() {
  local image="$1" attempt=1
  until docker pull --quiet "$image"; do
    if ((attempt >= PULL_ATTEMPTS)); then
      echo "::error::Failed to pull ${image} after ${PULL_ATTEMPTS} attempts"
      return 1
    fi
    ci_warn "Pull of ${image} failed (attempt ${attempt}/${PULL_ATTEMPTS}) — retrying in ${PULL_BACKOFF_SECS}s"
    sleep "$PULL_BACKOFF_SECS"
    attempt=$((attempt + 1))
  done
}

# ── readiness probes ──────────────────────────────────────────────────────

pg_probe() { docker exec "$PG_NAME" pg_isready -U gaia -d gaia_test; }
redis_probe() { docker exec "$REDIS_NAME" redis-cli ping; }
mongo_probe() { docker exec "$MONGO_NAME" mongosh --quiet --eval "db.runCommand({ping:1}).ok"; }

# -u rabbitmq is load-bearing: the image has no USER directive, so a plain exec
# runs as root with HOME=/var/lib/rabbitmq — during boot, a root
# `rabbitmq-diagnostics` creates .erlang.cookie owned by root and the server
# (running as rabbitmq) then crashes with eacces
# (docker-library/rabbitmq#318, rabbitmq-server discussion #11856).
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

container_running() {
  [ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]
}

container_config() {
  docker inspect -f "{{index .Config.Labels \"${CONFIG_LABEL}\"}}" "$1" 2>/dev/null || true
}

all_running() {
  local name
  for name in "$PG_NAME" "$REDIS_NAME" "$MONGO_NAME" "$CHROMA_NAME" "$RABBITMQ_NAME"; do
    container_running "$name" || return 1
  done
}

all_healthy() {
  all_running || return 1
  config_current || return 1
  pg_probe >/dev/null 2>&1 || return 1
  redis_probe >/dev/null 2>&1 || return 1
  mongo_probe >/dev/null 2>&1 || return 1
  rabbitmq_probe >/dev/null 2>&1 || return 1
  chroma_probe >/dev/null 2>&1 || return 1
}

# Every running container was started with the flags this script would use now.
config_current() {
  local i
  local names=("$PG_NAME" "$REDIS_NAME" "$MONGO_NAME" "$CHROMA_NAME" "$RABBITMQ_NAME")
  local specs=("$(_pg_spec)" "$(_redis_spec)" "$(_mongo_spec)" "$(_chroma_spec)" "$(_rabbitmq_spec)")
  for i in "${!names[@]}"; do
    [ "$(container_config "${names[$i]}")" = "$(_fingerprint "${specs[$i]}")" ] || return 1
  done
}

# wait_ready <label> <container> <start_fn> <probe...> — one timeout on a
# container that DIED recreates it and re-waits, so a boot flake costs ~90s
# instead of a red build; a second fails loud with the container's logs.
#
# On the box a container that is still RUNNING is never recreated: these
# containers are shared, a probe that times out under load (a dozen lanes
# hammering Postgres) is not a boot flake, and `docker rm -f` on it would take
# every other lane's database down mid-test. It gets one more probe window and
# then a clear failure for a human. Per-job containers belong to this job alone,
# so the original recreate-once behaviour stands.
wait_ready() {
  local label="$1" container="$2" start_fn="$3"
  shift 3
  if probe_until_deadline "$@"; then
    echo "${label}: ready"
    return 0
  fi
  docker logs "$container" 2>&1 | tail -50
  if on_the_box && container_running "$container"; then
    ci_warn "${label} is running but failed its probe for ${READY_TIMEOUT_SECS}s — NOT recreating a live shared container (other lanes may be using it); waiting once more"
    if probe_until_deadline "$@"; then
      echo "${label}: ready (slow probe, container kept)"
      return 0
    fi
    ci_die "${label} (${container}) is running but unresponsive after $((READY_TIMEOUT_SECS * 2))s. Refusing to recreate a live shared container; inspect it (docker logs ${container}) and restart it by hand if it is wedged."
  fi
  ci_warn "${label} not ready after ${READY_TIMEOUT_SECS}s — recreating container once (boot flake)"
  docker rm -f "$container" >/dev/null 2>&1 || true
  "$start_fn"
  if probe_until_deadline "$@"; then
    echo "${label}: ready (after one restart)"
    return 0
  fi
  docker logs "$container" 2>&1 | tail -50
  ci_die "${label} not ready after ${READY_TIMEOUT_SECS}s and one restart"
}

# ── up ────────────────────────────────────────────────────────────────────

cmd_up() {
  set_topology
  echo "test services: $(on_the_box && echo 'shared set (self-hosted)' || echo "per-job containers (runner index ${RUNNER_INDEX:-0})") — pg=${POSTGRES_PORT} redis=${REDIS_PORT} mongo=${MONGO_PORT} chroma=${CHROMA_PORT} rabbit=${RABBITMQ_PORT}"

  # The whole point is to pay nothing on the common path: every lane calls `up`
  # and only the first one on a cold box does any work. The pre-lock check keeps
  # the warm path lock-free; the post-lock check is what makes the cold-start
  # race safe (see LOCK_FILE above).
  if all_healthy; then
    ci_ok "test services: already healthy — nothing to do"
    return 0
  fi
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    flock -w "$LOCK_WAIT_SECS" 9 || ci_die "could not take ${LOCK_FILE} within ${LOCK_WAIT_SECS}s — another 'up' is stuck?"
    if all_healthy; then
      ci_ok "test services: already healthy (brought up by another lane while we waited)"
      return 0
    fi
  else
    ci_warn "flock not available — concurrent 'up' calls on a cold box may race"
  fi

  ci_group "Pull service images (parallel)"
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
  ((pull_failed == 0)) || ci_die "One or more service images could not be pulled"
  ci_endgroup

  # Start what is missing, and RECONCILE what no longer matches. A container
  # that exists but is stopped (box rebooted mid-pull, someone ran `docker
  # stop`) is removed and recreated rather than started; a running container
  # whose config fingerprint differs from what this script would start now is
  # also recreated, under the lock, so a flag bump takes effect.
  ci_group "Start missing or stale containers"
  local i name spec start_fn
  local names=("$PG_NAME" "$REDIS_NAME" "$MONGO_NAME" "$CHROMA_NAME" "$RABBITMQ_NAME")
  local specs=("$(_pg_spec)" "$(_redis_spec)" "$(_mongo_spec)" "$(_chroma_spec)" "$(_rabbitmq_spec)")
  local starts=(start_postgres start_redis start_mongo start_chroma start_rabbitmq)
  for i in "${!names[@]}"; do
    name="${names[$i]}"; spec="${specs[$i]}"; start_fn="${starts[$i]}"
    if container_running "$name"; then
      if [ "$(container_config "$name")" = "$(_fingerprint "$spec")" ]; then
        echo "${name}: already running"
        continue
      fi
      ci_warn "${name}: running with stale configuration — recreating so the current flags apply"
    fi
    docker rm -f "$name" >/dev/null 2>&1 || true
    "$start_fn"
  done
  ci_endgroup

  ci_group "Wait for readiness"
  wait_ready "PostgreSQL" "$PG_NAME" start_postgres pg_probe
  wait_ready "Redis" "$REDIS_NAME" start_redis redis_probe
  wait_ready "MongoDB" "$MONGO_NAME" start_mongo mongo_probe
  wait_ready "RabbitMQ" "$RABBITMQ_NAME" start_rabbitmq rabbitmq_probe
  wait_ready "ChromaDB" "$CHROMA_NAME" start_chroma chroma_probe
  ci_endgroup
  ci_ok "test services: up (pg=${POSTGRES_PORT} redis=${REDIS_PORT} mongo=${MONGO_PORT} chroma=${CHROMA_PORT} rabbit=${RABBITMQ_PORT})"
}

# ── prepare ───────────────────────────────────────────────────────────────

psql_exec() {
  docker exec "$PG_NAME" psql -U gaia -d postgres -tAc "$1"
}

cmd_prepare() {
  set_topology
  local lane
  lane="$(lane_of "${1:-}")"
  all_running || ci_die "test services are not running — run '$0 up' first"

  if on_the_box; then
    _prepare_shared "$lane"
  else
    _prepare_perjob
  fi
}

# The lane's namespace is made CLEAN here rather than trusted to have been left
# clean. A reset is best-effort by design (see cmd_reset) and a job that was
# cancelled never ran one at all, so "the previous lane tidied up" is not a
# property this can rely on — the next suite would then start against a
# half-populated database and fail in ways that look like test pollution.
_prepare_shared() {
  local lane="$1"
  local pg_db="gaia_test_r${lane}"
  local vhost="r${lane}"
  local redis_base=$((REDIS_BLOCK_START + lane * REDIS_STRIPE))
  local mongo_base="gaia_test_r${lane}"
  local chroma_suffix="_r${lane}"

  # Drop and recreate rather than CREATE-IF-ABSENT: WITH (FORCE) also
  # terminates backends a cancelled job left connected, which would otherwise
  # make the drop hang until the next janitor pass.
  psql_exec "DROP DATABASE IF EXISTS ${pg_db} WITH (FORCE)" >/dev/null \
    || ci_warn "Postgres: dropping a stale ${pg_db} failed — continuing"
  psql_exec "CREATE DATABASE ${pg_db} OWNER gaia" >/dev/null \
    || ci_die "Postgres: could not create ${pg_db}"
  echo "Postgres: ${pg_db} created empty"

  flush_redis_stripe "$redis_base" || ci_warn "Redis: flushing the lane stripe failed — continuing"
  drop_mongo_databases "$lane" || ci_warn "MongoDB: dropping stale gaia_test_r${lane}_* failed — continuing"
  reset_chroma "$chroma_suffix" || ci_warn "ChromaDB: clearing collections ending in ${chroma_suffix} failed — continuing"

  # A vhost left by a cancelled job keeps its queues and their contents; delete
  # before adding so the lane always starts with an empty broker.
  docker exec -u rabbitmq "$RABBITMQ_NAME" rabbitmqctl -q delete_vhost "$vhost" >/dev/null 2>&1 || true
  # `rabbitmq-diagnostics ping` (the readiness probe) answers before the
  # management subsystem accepts vhost commands, so right after `up` the first
  # rabbitmqctl call can fail with a usage/"not running" error. Retry briefly.
  local tries=0
  until docker exec -u rabbitmq "$RABBITMQ_NAME" rabbitmqctl -q add_vhost "$vhost" >/dev/null 2>&1 \
     && docker exec -u rabbitmq "$RABBITMQ_NAME" rabbitmqctl -q set_permissions -p "$vhost" guest ".*" ".*" ".*" >/dev/null 2>&1; do
    tries=$((tries + 1))
    ((tries < 30)) || ci_die "RabbitMQ: could not provision vhost ${vhost} after 30 attempts"
    sleep 1
  done
  echo "RabbitMQ: vhost ${vhost} ready"

  # Mongo and Chroma need no provisioning: a Mongo database and a Chroma
  # collection both spring into existence on first write. Only their names have
  # to be agreed, which is what this env file does.
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
  ci_ok "test services: lane ${lane} prepared (${pg_db}, redis ${redis_base}-$((redis_base + REDIS_STRIPE - 1)), vhost ${vhost})"
}

# The per-job containers were created by this job's own `up` and hold nothing
# from anyone else, so there is no namespace to clean — only the endpoint
# contract to publish. This is the single source of truth for the suite's
# service URLs: consumers never recompute the port arithmetic.
_prepare_perjob() {
  local env_file
  env_file="${GAIA_TEST_SERVICES_ENV:-$(env_file_for "${RUNNER_INDEX:-0}")}"
  cat > "$env_file" <<ENVEOF
DATABASE_URL=postgresql://gaia:gaia@localhost:${POSTGRES_PORT}/gaia_test
POSTGRES_URL=postgresql://gaia:gaia@localhost:${POSTGRES_PORT}/gaia_test
REDIS_URL=redis://localhost:${REDIS_PORT}/0
MONGODB_URL=mongodb://gaia:gaia@localhost:${MONGO_PORT}/gaia_test?authSource=admin
MONGO_DB=mongodb://gaia:gaia@localhost:${MONGO_PORT}/gaia_test?authSource=admin
CHROMADB_HOST=localhost
CHROMADB_PORT=${CHROMA_PORT}
RABBITMQ_URL=amqp://guest:guest@localhost:${RABBITMQ_PORT}/
GAIA_TEST_CONTAINERS="${PG_NAME} ${REDIS_NAME} ${MONGO_NAME} ${CHROMA_NAME} ${RABBITMQ_NAME}"
ENVEOF
  echo "Service endpoints written to $env_file"

  if [ -n "${GITHUB_ENV:-}" ]; then
    # GAIA_TEST_CONTAINERS is a bookkeeping list for teardown, not suite config
    # — keep it out of the job environment.
    grep -v "^GAIA_TEST_CONTAINERS=" "$env_file" >> "$GITHUB_ENV"
    echo "Published service URLs to GITHUB_ENV (runner index ${RUNNER_INDEX:-0})"
  fi
  ci_ok "test services: endpoints published (runner index ${RUNNER_INDEX:-0})"
}

# ── reset ─────────────────────────────────────────────────────────────────

# Flush the lane's whole 32-DB stripe, not just the 24 the workers use: a stray
# key outside the block is still this lane's litter. One docker exec, not one
# per DB: 32 execs cost 3.2 s of every services lane's teardown (run
# 33171716529); a single exec with the loop inside the container is ~0.3 s.
flush_redis_stripe() {
  local base="$1"
  docker exec "$REDIS_NAME" sh -c \
    "for db in \$(seq $base $((base + REDIS_STRIPE - 1))); do redis-cli -n \$db flushdb >/dev/null; done"
}

# Every worker database of this lane: gaia_test_r<lane>_gw0, _gw1, ...
drop_mongo_databases() {
  local lane="$1"
  docker exec "$MONGO_NAME" mongosh --quiet \
    -u gaia -p gaia --authenticationDatabase admin \
    --eval "db.adminCommand({listDatabases:1,nameOnly:true}).databases
      .map(d => d.name)
      .filter(n => /^gaia_test_r${lane}_/.test(n))
      .forEach(n => { db.getSiblingDB(n).dropDatabase(); print('dropped ' + n); })"
}

# Chroma has no namespace concept, so the lane's collections are identified by
# the name suffix the app appended (GAIA_CHROMA_COLLECTION_SUFFIX) and deleted
# one by one through the v2 REST API. python3 does the JSON parsing: the runner
# has it (it runs the pytest suite), and jq is not guaranteed to be installed.
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
        if curl -sf -X DELETE "${base}/${name}" >/dev/null; then
          deleted=$((deleted + 1))
        else
          ci_warn "ChromaDB: failed to delete collection ${name}"
        fi
        ;;
    esac
  done <<< "$names"
  echo "ChromaDB: deleted ${deleted} collection(s) ending in ${suffix}"
}

# Releasing a namespace must NEVER red a green lane. Teardown runs from
# `if: always()`, and lanes that took no services (unit-a/unit-b run with
# services: "false") call it too — "there is nothing to reset" is the normal
# case for them, not an error.
cmd_reset() {
  set_topology
  local lane
  lane="$(lane_of "${1:-}")"

  if ! on_the_box; then
    _down_perjob
    return 0
  fi
  if ! all_running; then
    ci_warn "shared test services are not running — nothing to reset for lane ${lane}"
    rm -f "$(env_file_for "$lane")" 2>/dev/null || true
    return 0
  fi

  local pg_db="gaia_test_r${lane}"
  local vhost="r${lane}"
  local redis_base=$((REDIS_BLOCK_START + lane * REDIS_STRIPE))
  local suffix="_r${lane}"

  # Every step below is best-effort: under set -e one Mongo or Rabbit hiccup
  # would abort the reset half-way. A warning per failed step, and the env file
  # always goes — `prepare` re-cleans the namespace before the next lane uses
  # it, so a partial reset costs nothing.
  if psql_exec "DROP DATABASE IF EXISTS ${pg_db} WITH (FORCE)" >/dev/null; then
    echo "Postgres: dropped ${pg_db}"
  else
    ci_warn "Postgres: dropping ${pg_db} failed"
  fi

  if flush_redis_stripe "$redis_base"; then
    echo "Redis: flushed DBs ${redis_base}-$((redis_base + REDIS_STRIPE - 1))"
  else
    ci_warn "Redis: flushing DBs ${redis_base}-$((redis_base + REDIS_STRIPE - 1)) failed"
  fi

  if drop_mongo_databases "$lane"; then
    echo "MongoDB: dropped gaia_test_r${lane}_* databases"
  else
    ci_warn "MongoDB: dropping gaia_test_r${lane}_* databases failed"
  fi

  reset_chroma "$suffix" || ci_warn "ChromaDB: resetting collections ending in ${suffix} failed"

  if docker exec -u rabbitmq "$RABBITMQ_NAME" rabbitmqctl -q delete_vhost "$vhost"; then
    echo "RabbitMQ: deleted vhost ${vhost}"
  else
    echo "RabbitMQ: vhost ${vhost} was already absent (or delete failed — see above)"
  fi

  rm -f "$(env_file_for "$lane")" || ci_warn "could not remove $(env_file_for "$lane")"
  ci_ok "test services: lane ${lane} released"
}

# ── down ──────────────────────────────────────────────────────────────────

# Remove the containers this job started. Reads the list `prepare` recorded so
# the names stay correct as the per-runner index changes, and falls back to the
# naming convention when the env file is gone (interrupted run, cleaned /tmp) so
# containers are never left holding their ports. Never fails the caller.
_down_perjob() {
  local env_file containers
  env_file="${GAIA_TEST_SERVICES_ENV:-$(env_file_for "${RUNNER_INDEX:-0}")}"
  if [ -f "$env_file" ]; then
    containers="$(grep '^GAIA_TEST_CONTAINERS=' "$env_file" | cut -d= -f2- | tr -d '"')"
  else
    containers=""
  fi
  [ -n "${containers// /}" ] || containers="$PG_NAME $REDIS_NAME $MONGO_NAME $CHROMA_NAME $RABBITMQ_NAME"
  # The container list is intentionally word-split into separate arguments.
  # shellcheck disable=SC2086
  docker rm -f $containers >/dev/null 2>&1 || true
  rm -f "$env_file" 2>/dev/null || true
  ci_ok "test services: torn down (runner index ${RUNNER_INDEX:-0})"
}

cmd_down() { cmd_reset "${1:-}"; }

# ── janitor ───────────────────────────────────────────────────────────────

# A cancelled job never runs its own reset, so its namespaces would accumulate
# until the box ran out of tmpfs. The env file's mtime is the liveness signal:
# `prepare` writes it at job start, and nothing outlives STALE_HOURS legitimately.
cmd_janitor() {
  set_topology
  if ! on_the_box; then
    ci_ok "test services: janitor is a no-op off the box (GitHub-hosted runners are thrown away)"
    return 0
  fi
  if ! all_running; then
    ci_warn "shared test services are not running — nothing to collect"
    return 0
  fi
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
  ci_ok "test services: janitor reset ${swept} stale lane(s)"
}

# ── dispatch ──────────────────────────────────────────────────────────────

usage() {
  cat >&2 <<'USAGE'
Usage: test-services.sh <up|prepare|reset|down|janitor> [lane]

  up            make the services exist and be ready (idempotent)
  prepare [r]   claim lane r's namespace, clean it, export its env contract
  reset [r]     release lane r's namespace (never fails a green lane)
  down          teardown for an `if: always()` step
  janitor       reset every lane whose env file is stale (self-hosted only)

The topology (shared set on the box vs per-job containers) is decided from
RUNNER_ENVIRONMENT and RUNNER_INDEX; callers do not choose.
USAGE
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    up)      cmd_up "$@" ;;
    prepare) cmd_prepare "$@" ;;
    reset)   cmd_reset "$@" ;;
    down)    cmd_down "$@" ;;
    janitor) cmd_janitor "$@" ;;
    *)
      echo "test-services.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
