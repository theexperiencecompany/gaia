#!/usr/bin/env bash
# Start the shared dev infra, plus this linked worktree's private Redis and RabbitMQ vhost.
#
# The shared project (gaia-dev) bind-mounts files by absolute path, so its config hash
# differs per worktree and a plain `up -d` from a second worktree recreates postgres,
# rabbitmq and searxng under every running stack. --no-recreate starts what is missing
# and leaves running containers alone; after a deliberate compose change, recreate them
# once by hand (`nx run docker:docker:down`, then this).

set -euo pipefail

compose_dir="$(git rev-parse --show-toplevel)/infra/docker"
cd "$compose_dir"
env_file_args=()
[ -f .env ] && env_file_args=(--env-file .env)

docker compose ${env_file_args[@]+"${env_file_args[@]}"} up -d --no-recreate

slot="${GAIA_WT_SLOT:-0}"
[ "$slot" -eq 0 ] && exit 0

: "${WT_REDIS_PORT:?.env.worktree is not loaded: run mise run wt:env, then start through mise}"
: "${RABBITMQ_VHOST:?.env.worktree is not loaded: run mise run wt:env, then start through mise}"
: "${RABBITMQ_URL:?.env.worktree is not loaded: run mise run wt:env, then start through mise}"

docker compose -p "gaia-wt$((slot * 10))" -f docker-compose.worktree.yml up -d --wait

# The vhost must exist before the API or worker connects; the management API creates it idempotently.
credentials="${RABBITMQ_URL#amqp://}"
credentials="${credentials%%@*}"
management="http://localhost:${RABBITMQ_MGMT_PORT:-15672}/api"
request_timeout_s=10
deadline=$(( $(date +%s) + 90 ))
until curl -sf --max-time "$request_timeout_s" -o /dev/null -u "$credentials" "$management/overview"; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "ERROR: RabbitMQ's management API at $management did not answer within 90s." >&2
    exit 1
  fi
  sleep 2
done
curl -sfS --max-time "$request_timeout_s" -o /dev/null -u "$credentials" -X PUT "$management/vhosts/$RABBITMQ_VHOST"
user="${credentials%%:*}"
curl -sfS --max-time "$request_timeout_s" -o /dev/null -u "$credentials" -X PUT -H 'content-type: application/json' \
  -d '{"configure":".*","write":".*","read":".*"}' "$management/permissions/$RABBITMQ_VHOST/$user"
echo "worktree infra: Redis on :$WT_REDIS_PORT, RabbitMQ vhost $RABBITMQ_VHOST, Mongo database ${MONGO_DB_NAME:-GAIA}"
