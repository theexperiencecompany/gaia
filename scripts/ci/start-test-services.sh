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

POSTGRES_IMAGE="postgres:16-alpine"
REDIS_IMAGE="redis:7-alpine"
MONGO_IMAGE="mongo:7"
CHROMA_IMAGE="chromadb/chroma:latest"
RABBITMQ_IMAGE="rabbitmq:3-alpine"

READY_TIMEOUT_SECS=90

echo "::group::Pull service images (parallel)"
for image in "$POSTGRES_IMAGE" "$REDIS_IMAGE" "$MONGO_IMAGE" "$CHROMA_IMAGE" "$RABBITMQ_IMAGE"; do
  docker pull --quiet "$image" &
done
wait
echo "::endgroup::"

echo "::group::Start service containers"
docker run -d --name gaia-test-postgres \
  -e POSTGRES_USER=gaia -e POSTGRES_PASSWORD=gaia -e POSTGRES_DB=gaia_test \
  -p 5432:5432 "$POSTGRES_IMAGE"

# 32 logical databases so each pytest-xdist worker gets an isolated Redis DB.
docker run -d --name gaia-test-redis \
  -p 6379:6379 "$REDIS_IMAGE" redis-server --databases 32

docker run -d --name gaia-test-mongo \
  -e MONGO_INITDB_ROOT_USERNAME=gaia -e MONGO_INITDB_ROOT_PASSWORD=gaia \
  -p 27017:27017 "$MONGO_IMAGE"

docker run -d --name gaia-test-chroma \
  -p 8000:8000 "$CHROMA_IMAGE"

docker run -d --name gaia-test-rabbitmq \
  -p 5672:5672 "$RABBITMQ_IMAGE"
echo "::endgroup::"

# wait_ready <label> <probe command...> — poll until the probe passes or the
# shared timeout elapses. Fails loud with the container's logs so a bad image
# or crashed service is diagnosable straight from the CI log.
wait_ready() {
  local label="$1" container="$2"
  shift 2
  local deadline=$((SECONDS + READY_TIMEOUT_SECS))
  until "$@" >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then
      echo "::error::${label} not ready after ${READY_TIMEOUT_SECS}s"
      docker logs "$container" | tail -50
      exit 1
    fi
    sleep 1
  done
  echo "${label}: ready"
}

echo "::group::Wait for readiness"
wait_ready "PostgreSQL" gaia-test-postgres \
  docker exec gaia-test-postgres pg_isready -U gaia -d gaia_test
wait_ready "Redis" gaia-test-redis \
  docker exec gaia-test-redis redis-cli ping
wait_ready "MongoDB" gaia-test-mongo \
  docker exec gaia-test-mongo mongosh --quiet --eval "db.runCommand({ping:1}).ok"
wait_ready "RabbitMQ" gaia-test-rabbitmq \
  docker exec gaia-test-rabbitmq rabbitmq-diagnostics -q ping
# Chroma's heartbeat path moved between API v1 and v2; probe both so the
# `latest` image is ready regardless of which generation it ships.
chroma_heartbeat() {
  curl -sf http://localhost:8000/api/v2/heartbeat \
    || curl -sf http://localhost:8000/api/v1/heartbeat
}
wait_ready "ChromaDB" gaia-test-chroma chroma_heartbeat
echo "::endgroup::"
