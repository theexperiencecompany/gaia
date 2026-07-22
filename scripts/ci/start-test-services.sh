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
set -euo pipefail

# Exact tags (digest-matched to the previous floating tags) so every run boots
# identical bits and a flake can't be image drift. Bump deliberately, and keep
# .dagger/src/gaia_ci/main.py on the same tags.
POSTGRES_IMAGE="postgres:16.14-alpine3.24"
REDIS_IMAGE="redis:7.4.9-alpine3.21"
MONGO_IMAGE="mongo:7.0.37"
CHROMA_IMAGE="chromadb/chroma:1.5.9"
RABBITMQ_IMAGE="rabbitmq:3.13.7-alpine"

READY_TIMEOUT_SECS=90

start_postgres() {
  docker run -d --name gaia-test-postgres \
    -e POSTGRES_USER=gaia -e POSTGRES_PASSWORD=gaia -e POSTGRES_DB=gaia_test \
    -p 5432:5432 "$POSTGRES_IMAGE"
}

# 32 logical databases so each pytest-xdist worker gets an isolated Redis DB.
start_redis() {
  docker run -d --name gaia-test-redis \
    -p 6379:6379 "$REDIS_IMAGE" redis-server --databases 32
}

start_mongo() {
  docker run -d --name gaia-test-mongo \
    -e MONGO_INITDB_ROOT_USERNAME=gaia -e MONGO_INITDB_ROOT_PASSWORD=gaia \
    -p 27017:27017 "$MONGO_IMAGE"
}

start_chroma() {
  docker run -d --name gaia-test-chroma \
    -p 8000:8000 "$CHROMA_IMAGE"
}

start_rabbitmq() {
  docker run -d --name gaia-test-rabbitmq \
    -p 5672:5672 "$RABBITMQ_IMAGE"
}

echo "::group::Pull service images (parallel)"
for image in "$POSTGRES_IMAGE" "$REDIS_IMAGE" "$MONGO_IMAGE" "$CHROMA_IMAGE" "$RABBITMQ_IMAGE"; do
  docker pull --quiet "$image" &
done
wait
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
# probe passes or the timeout elapses. The official images intermittently crash
# at boot (seen: rabbitmq "/var/lib/rabbitmq/.erlang.cookie: eacces"), so one
# timeout recreates the container and re-waits; a second fails loud with the
# container's logs so the cause is diagnosable straight from the CI log.
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
wait_ready "PostgreSQL" gaia-test-postgres start_postgres \
  docker exec gaia-test-postgres pg_isready -U gaia -d gaia_test
wait_ready "Redis" gaia-test-redis start_redis \
  docker exec gaia-test-redis redis-cli ping
wait_ready "MongoDB" gaia-test-mongo start_mongo \
  docker exec gaia-test-mongo mongosh --quiet --eval "db.runCommand({ping:1}).ok"
wait_ready "RabbitMQ" gaia-test-rabbitmq start_rabbitmq \
  docker exec gaia-test-rabbitmq rabbitmq-diagnostics -q ping
# Chroma's heartbeat path moved between API v1 and v2; probe both so an image
# bump across that boundary can't silently break readiness.
chroma_heartbeat() {
  curl -sf http://localhost:8000/api/v2/heartbeat \
    || curl -sf http://localhost:8000/api/v1/heartbeat
}
wait_ready "ChromaDB" gaia-test-chroma start_chroma chroma_heartbeat
echo "::endgroup::"
