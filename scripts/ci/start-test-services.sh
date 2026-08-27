#!/usr/bin/env bash
#
# start-test-services.sh — boot the live service containers the API test suite
# needs (PostgreSQL, Redis, MongoDB, ChromaDB, RabbitMQ) directly on the CI
# runner's Docker daemon, then block until every one of them is ready.
#
# This mirrors .dagger/src/gaia_ci/main.py:_service_test_container() exactly —
# same images, same credentials, same ports — so `uv run pytest` on the runner
# sees the identical topology the Dagger functions provide locally, just on
# localhost instead of service-binding hostnames.
#
# Plain `docker run` (not GitHub `services:`) because Redis needs a command
# override (`--databases 32` for pytest-xdist worker isolation) and service
# containers cannot pass container commands.
#
# Per-runner isolation: the home box runs several runner instances that can
# execute test lanes concurrently, and fixed host ports would make the second
# lane fail on "port is already allocated". Each instance carries RUNNER_INDEX
# in its .env (see infra/self-hosted-runner/setup.sh); it offsets every host
# port by index*100 and suffixes every container name. GitHub-hosted runners
# have no RUNNER_INDEX, so they default to 0 and keep the canonical ports.
#
# This script is the single source of truth for the suite's service URLs: it
# writes them to $GITHUB_ENV so consumers never duplicate (and drift from) the
# port arithmetic.
set -euo pipefail

RUNNER_INDEX="${RUNNER_INDEX:-0}"
PORT_OFFSET=$((RUNNER_INDEX * 100))
SUFFIX="${RUNNER_INDEX}"

POSTGRES_PORT=$((5432 + PORT_OFFSET))
REDIS_PORT=$((6379 + PORT_OFFSET))
MONGO_PORT=$((27017 + PORT_OFFSET))
CHROMA_PORT=$((8000 + PORT_OFFSET))
RABBITMQ_PORT=$((5672 + PORT_OFFSET))

PG_NAME="gaia-test-postgres-${SUFFIX}"
REDIS_NAME="gaia-test-redis-${SUFFIX}"
MONGO_NAME="gaia-test-mongo-${SUFFIX}"
CHROMA_NAME="gaia-test-chroma-${SUFFIX}"
RABBITMQ_NAME="gaia-test-rabbitmq-${SUFFIX}"

echo "Runner index ${RUNNER_INDEX} → ports pg=${POSTGRES_PORT} redis=${REDIS_PORT} mongo=${MONGO_PORT} chroma=${CHROMA_PORT} rabbit=${RABBITMQ_PORT}"

# Digest-pinned (tag kept for readability; the digest is what's pulled) so
# every run boots identical bits and a flake can't be image drift. Bump
# deliberately, and keep .dagger/src/gaia_ci/main.py on the same references.
POSTGRES_IMAGE="postgres:16.14-alpine3.24@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
REDIS_IMAGE="redis:7.4.9-alpine3.21@sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
MONGO_IMAGE="mongo:7.0.37@sha256:340c1c56fb10e95cf79ff547f8664b96bc6ead9909bc355238cbf865a9695a6f"
CHROMA_IMAGE="chromadb/chroma:1.5.9@sha256:1e0b73a187a28757c572acba508c46f48c9e8b0acaf5c20e6d95cdedce1acdf6"
RABBITMQ_IMAGE="rabbitmq:3.13.7-alpine@sha256:d7af1c87c5f1eda13fcfca06db452bf3aeab6619fc3358b68535c0c02c4e52bc"

READY_TIMEOUT_SECS=90

# Docker Hub pulls flake — the registry times out or rate-limits transiently.
# One unlucky pull would otherwise surface much later as an opaque `docker run`
# exit 125, so retry each pull with backoff before giving up.
PULL_ATTEMPTS=5
PULL_BACKOFF_SECS=5

# Data directories on tmpfs: every one of these containers is thrown away at
# the end of the job, so durability buys nothing and fsync costs real time.
# Postgres in particular is commit-latency bound under a 16-way xdist run.
start_postgres() {
  docker run -d --name "$PG_NAME" \
    -e POSTGRES_USER=gaia -e POSTGRES_PASSWORD=gaia -e POSTGRES_DB=gaia_test \
    -e PGDATA=/var/lib/postgresql/data/pgdata \
    --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=2g \
    -p "${POSTGRES_PORT}:5432" "$POSTGRES_IMAGE" \
    -c fsync=off -c synchronous_commit=off -c full_page_writes=off
}

# 32 logical databases so each pytest-xdist worker gets an isolated Redis DB.
# --save "" disables RDB snapshotting: the dataset is discarded with the
# container, and the fork-to-disk pauses only add latency.
start_redis() {
  docker run -d --name "$REDIS_NAME" \
    -p "${REDIS_PORT}:6379" "$REDIS_IMAGE" \
    redis-server --databases 32 --save "" --appendonly no
}

start_mongo() {
  docker run -d --name "$MONGO_NAME" \
    -e MONGO_INITDB_ROOT_USERNAME=gaia -e MONGO_INITDB_ROOT_PASSWORD=gaia \
    --tmpfs /data/db:rw,noexec,nosuid,size=2g \
    -p "${MONGO_PORT}:27017" "$MONGO_IMAGE"
}

start_chroma() {
  docker run -d --name "$CHROMA_NAME" \
    -p "${CHROMA_PORT}:8000" "$CHROMA_IMAGE"
}

start_rabbitmq() {
  docker run -d --name "$RABBITMQ_NAME" \
    -p "${RABBITMQ_PORT}:5672" "$RABBITMQ_IMAGE"
}

# Retry a single image pull with a fixed backoff, failing loud if it never
# succeeds so a genuinely broken pull is diagnosable instead of masked.
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

echo "::group::Pull service images (parallel)"
pull_pids=()
for image in "$POSTGRES_IMAGE" "$REDIS_IMAGE" "$MONGO_IMAGE" "$CHROMA_IMAGE" "$RABBITMQ_IMAGE"; do
  pull_with_retry "$image" &
  pull_pids+=("$!")
done
# A bare `wait` swallows background exit codes; wait on each PID so a pull that
# exhausted its retries fails the step here instead of leaking into `docker run`.
pull_failed=0
for pid in "${pull_pids[@]}"; do
  wait "$pid" || pull_failed=1
done
if ((pull_failed)); then
  echo "::error::One or more service images could not be pulled"
  exit 1
fi
echo "::endgroup::"

# Self-hosted runners are reused, so a container left behind by an
# interrupted job would make `docker run` fail on a duplicate name.
echo "::group::Remove stale containers from a previous run"
docker rm -f "$PG_NAME" "$REDIS_NAME" "$MONGO_NAME" "$CHROMA_NAME" "$RABBITMQ_NAME" 2>/dev/null || true
echo "::endgroup::"

echo "::group::Start service containers"
start_postgres
start_redis
start_mongo
start_chroma
start_rabbitmq
echo "::endgroup::"

probe_until_deadline() {
  local deadline=$((SECONDS + READY_TIMEOUT_SECS))
  until "$@" >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then
      return 1
    fi
    sleep 1
  done
}

# wait_ready <label> <container> <start_fn> <probe command...> — poll until the
# probe passes or the timeout elapses. One timeout recreates the container and
# re-waits, so a genuine boot flake costs ~90s instead of a red build; a second
# fails loud with the container's logs so the cause is diagnosable straight
# from the CI log.
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

echo "::group::Wait for readiness"
wait_ready "PostgreSQL" "$PG_NAME" start_postgres \
  docker exec "$PG_NAME" pg_isready -U gaia -d gaia_test
wait_ready "Redis" "$REDIS_NAME" start_redis \
  docker exec "$REDIS_NAME" redis-cli ping
wait_ready "MongoDB" "$MONGO_NAME" start_mongo \
  docker exec "$MONGO_NAME" mongosh --quiet --eval "db.runCommand({ping:1}).ok"
# -u rabbitmq is load-bearing: the image has no USER directive, so a plain
# exec runs as root with HOME=/var/lib/rabbitmq — during boot, a root
# `rabbitmq-diagnostics` creates .erlang.cookie owned by root and the server
# (running as rabbitmq) then crashes with eacces
# (docker-library/rabbitmq#318, rabbitmq-server discussion #11856).
wait_ready "RabbitMQ" "$RABBITMQ_NAME" start_rabbitmq \
  docker exec -u rabbitmq "$RABBITMQ_NAME" rabbitmq-diagnostics -q ping
# Chroma's heartbeat path moved between API v1 and v2; probe both so an image
# bump across that boundary can't silently break readiness.
chroma_heartbeat() {
  curl -sf "http://localhost:${CHROMA_PORT}/api/v2/heartbeat" \
    || curl -sf "http://localhost:${CHROMA_PORT}/api/v1/heartbeat"
}
wait_ready "ChromaDB" "$CHROMA_NAME" start_chroma chroma_heartbeat
echo "::endgroup::"

# Publish the resolved endpoints so no consumer has to recompute the offsets.
# Written to a sourceable file always (local runs, the benchmark harness) and
# to $GITHUB_ENV when running inside Actions.
SERVICES_ENV_FILE="${GAIA_TEST_SERVICES_ENV:-/tmp/gaia-test-services-${RUNNER_INDEX}.env}"
cat > "$SERVICES_ENV_FILE" <<ENVEOF
DATABASE_URL=postgresql://gaia:gaia@localhost:${POSTGRES_PORT}/gaia_test
POSTGRES_URL=postgresql://gaia:gaia@localhost:${POSTGRES_PORT}/gaia_test
REDIS_URL=redis://localhost:${REDIS_PORT}/0
MONGODB_URL=mongodb://gaia:gaia@localhost:${MONGO_PORT}/gaia_test?authSource=admin
MONGO_DB=mongodb://gaia:gaia@localhost:${MONGO_PORT}/gaia_test?authSource=admin
CHROMADB_HOST=localhost
CHROMADB_PORT=${CHROMA_PORT}
RABBITMQ_URL=amqp://guest:guest@localhost:${RABBITMQ_PORT}/
GAIA_TEST_CONTAINERS=${PG_NAME} ${REDIS_NAME} ${MONGO_NAME} ${CHROMA_NAME} ${RABBITMQ_NAME}
ENVEOF
echo "Service endpoints written to $SERVICES_ENV_FILE"

if [ -n "${GITHUB_ENV:-}" ]; then
  # GAIA_TEST_CONTAINERS is a bookkeeping list for teardown, not suite config
  # — keep it out of the job environment.
  grep -v "^GAIA_TEST_CONTAINERS=" "$SERVICES_ENV_FILE" >> "$GITHUB_ENV"
  echo "Published service URLs to GITHUB_ENV (runner index ${RUNNER_INDEX})"
fi
