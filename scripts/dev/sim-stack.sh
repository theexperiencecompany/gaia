#!/usr/bin/env bash
# The one way to run the sim stack: scripted LLM stub, API, ARQ worker and web, with the
# dev auth bypass, on this worktree's own ports, database, Redis and RabbitMQ vhost.
#
#   sim-stack.sh up [--no-web] [--no-seed]   start detached; return once every process is ready
#   sim-stack.sh down [--purge]              stop what `up` started (--purge drops the Mongo database)
#   sim-stack.sh status                      each process, its pid, port and log
#   sim-stack.sh logs [name]                 log paths, or the last 100 lines of one
#
# Every process gets the same environment, so the worker runs the scripted model and the
# bypass user exactly as the API does. Each writes its own log under .sim-stack/, and
# `down` stops only the process trees recorded in .sim-stack/*.pid.

set -euo pipefail

root="$(git rev-parse --show-toplevel)"
state_dir="$root/.sim-stack"
processes=(stub api worker web)
boot_timeout_s=600
probe_timeout_s=5

ports_of() {
  case "$1" in
    stub) echo "${LLM_STUB_PORT:-9797}" ;;
    api) echo "${API_PORT:-8000}" ;;
    worker) echo "${ARQ_METRICS_PORT:-9100}" ;;
    web) echo "${WEB_PORT:-3000}" ;;
  esac
}

pid_of() {
  local file="$state_dir/$1.pid"
  [ -f "$file" ] && cat "$file"
}

# A recorded pid is ours only while the process still began when we recorded it; after a
# crash the OS may hand the same pid to an unrelated process, which `down` must not signal.
started_at() {
  ps -o lstart= -p "$1" 2>/dev/null
}

alive() {
  local pid
  pid="$(pid_of "$1")" || return 1
  kill -0 "$pid" 2>/dev/null && [ "$(started_at "$pid")" = "$(cat "$state_dir/$1.started")" ]
}

kill_tree() {
  local pid="$1" signal="$2" child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child" "$signal"
  done
  kill "-$signal" "$pid" 2>/dev/null || true
}

start() {
  local name="$1"
  shift
  ( cd "$root" && exec "$@" ) >"$state_dir/$name.log" 2>&1 &
  echo "$!" >"$state_dir/$name.pid"
  started_at "$!" >"$state_dir/$name.started"
  # Recorded, so status reports the port this stack bound even from a shell without its env.
  ports_of "$name" >"$state_dir/$name.port"
}

fail_boot() {
  echo "ERROR: $1" >&2
  [ -n "${2:-}" ] && { echo "--- last 40 lines of $state_dir/$2.log ---" >&2; tail -n 40 "$state_dir/$2.log" >&2; }
  exit 1
}

wait_for() {
  local name="$1" probe="$2" deadline
  deadline=$(( $(date +%s) + boot_timeout_s ))
  until eval "$probe"; do
    for running in "${started[@]}"; do
      alive "$running" || fail_boot "$running exited while the stack was starting." "$running"
    done
    [ "$(date +%s)" -lt "$deadline" ] || fail_boot "$name was not ready within ${boot_timeout_s}s." "$name"
    sleep 2
  done
  echo "  $name ready"
}

worktree_redis() {
  docker compose -p "gaia-wt$((GAIA_WT_SLOT * 10))" -f "$root/infra/docker/docker-compose.worktree.yml" "$@"
}

worker_registered() {
  [ -n "$(worktree_redis exec -T redis redis-cli --scan --pattern 'arq:health:*')" ]
}

stop_processes() {
  local name
  for name in "${processes[@]}"; do
    alive "$name" && kill_tree "$(pid_of "$name")" TERM
  done
  sleep 3
  for name in "${processes[@]}"; do
    alive "$name" && kill_tree "$(pid_of "$name")" KILL
    rm -f "$state_dir/$name.pid" "$state_dir/$name.port" "$state_dir/$name.started"
  done
}

# Armed for the whole of `up`: a failed boot, a failed seed or Ctrl-C leaves no orphans
# that would make the next `up` refuse to start.
stop_unless_booted() {
  local status=$?
  [ "$status" -eq 0 ] || stop_processes
}

cmd_up() {
  local web=1 seed=1 arg name
  for arg in "$@"; do
    case "$arg" in
      --no-web) web="" ;;
      --no-seed) seed="" ;;
      *) echo "sim-stack up: unknown flag $arg" >&2; exit 2 ;;
    esac
  done

  bash "$root/scripts/dev/require-worktree-env.sh"
  bash "$root/scripts/dev/assert-not-prod.sh" "the sim stack (dev auth bypass + scripted LLM)"
  for name in "${processes[@]}"; do
    if alive "$name"; then
      echo "ERROR: the sim stack is already up ($name is pid $(pid_of "$name")). See: $0 status, or $0 down" >&2
      exit 1
    fi
  done
  local wanted=(stub api worker)
  [ -n "$web" ] && wanted+=(web)
  local port_args=()
  for name in "${wanted[@]}"; do port_args+=("$name=$(ports_of "$name")"); done
  bash "$root/scripts/dev/check-ports.sh" "${port_args[@]}"

  bash "$root/scripts/dev/docker-up.sh"

  mkdir -p "$state_dir"
  export DEV_AUTH_BYPASS_EMAIL="${DEV_USER:-dev@gaia.local}"
  export GAIA_SIM_MODE=1
  export LLM_STUB_PORT="${LLM_STUB_PORT:-9797}"
  # Forced, never inherited: an OPENROUTER_BASE_URL from Infisical would reach the real model.
  export OPENROUTER_BASE_URL="http://localhost:$LLM_STUB_PORT/api/v1"
  # A scripted model's traces mean nothing, and exporting them logs an OTEL ERROR per
  # batch whenever the Langfuse host is unreachable; blank is "not configured".
  export LANGFUSE_HOST=""
  local api="http://localhost:$(ports_of api)"

  started=()
  trap stop_unless_booted EXIT
  trap 'exit 130' INT TERM
  start stub uv run tools/llm-stub/server.py && started+=(stub)
  start api nx run api:dev --output-style=stream && started+=(api)
  start worker nx run api:worker --output-style=stream && started+=(worker)
  [ -n "$web" ] && start web nx run web:dev --output-style=stream && started+=(web)
  {
    echo "commit=$(git -C "$root" rev-parse --short HEAD)"
    echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "slot=${GAIA_WT_SLOT:-0} mongo_db=${MONGO_DB_NAME:-GAIA} redis=${REDIS_URL:-shared} vhost=${RABBITMQ_VHOST:-/}"
    echo "user=$DEV_AUTH_BYPASS_EMAIL api=$api web=http://localhost:$(ports_of web) stub=$OPENROUTER_BASE_URL"
  } >"$state_dir/state"

  echo "sim stack starting (logs in $state_dir/):"
  wait_for stub "curl -sf --max-time $probe_timeout_s -o /dev/null http://localhost:$LLM_STUB_PORT/health"
  # /health/ready, not /health: it answers only once Mongo, Postgres, Redis, RabbitMQ and Chroma do.
  wait_for api "curl -sf --max-time $probe_timeout_s -o /dev/null $api/health/ready"
  if [ "${GAIA_WT_SLOT:-0}" -ne 0 ]; then
    wait_for worker worker_registered
  else
    echo "  worker started (main checkout: Redis is shared, so its health key cannot be told from another worker's)"
  fi
  [ -n "$web" ] && wait_for web "curl -sf --max-time $probe_timeout_s -o /dev/null http://localhost:$(ports_of web)/"
  if [ -n "$seed" ]; then
    SEED_TASKS=0 SEED_CONVERSATIONS=0 DEV_USER="$DEV_AUTH_BYPASS_EMAIL" mise run seed >/dev/null
    echo "  $DEV_AUTH_BYPASS_EMAIL minted with Pro"
  fi
  trap - EXIT INT TERM
  cmd_status
}

cmd_down() {
  local purge=""
  [ "${1:-}" = "--purge" ] && purge=1
  stop_processes
  if [ "${GAIA_WT_SLOT:-0}" -ne 0 ]; then
    worktree_redis down >/dev/null 2>&1
    if [ -n "$purge" ]; then
      docker exec mongo mongosh --quiet --eval "db.getSiblingDB('$MONGO_DB_NAME').dropDatabase()" >/dev/null
      echo "dropped Mongo database $MONGO_DB_NAME"
    fi
  elif [ -n "$purge" ]; then
    echo "ERROR: --purge refuses the main checkout, whose database is the shared GAIA one." >&2
    exit 1
  fi
  echo "sim stack down"
}

cmd_status() {
  local name pid state
  [ -f "$state_dir/state" ] && cat "$state_dir/state"
  for name in "${processes[@]}"; do
    pid="$(pid_of "$name")" || { printf '  %-7s not started\n' "$name"; continue; }
    if kill -0 "$pid" 2>/dev/null; then state="up"; else state="EXITED"; fi
    printf '  %-7s %-7s pid %-7s port %-6s %s\n' "$name" "$state" "$pid" "$(cat "$state_dir/$name.port")" "$state_dir/$name.log"
  done
}

cmd_logs() {
  if [ -n "${1:-}" ]; then
    tail -n 100 "$state_dir/$1.log"
  else
    ls -1 "$state_dir"/*.log
  fi
}

case "${1:-}" in
  up) shift; cmd_up "$@" ;;
  down) shift; cmd_down "$@" ;;
  status) cmd_status ;;
  logs) shift; cmd_logs "$@" ;;
  *) echo "usage: sim-stack.sh up [--no-web] [--no-seed] | down [--purge] | status | logs [name]" >&2; exit 2 ;;
esac
