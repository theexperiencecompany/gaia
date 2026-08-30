#!/usr/bin/env bash
# embedding-sidecar.sh — ONE embedding sidecar for the pytest run.
#
# Subcommands:
#   start   start (or reuse) the sidecar and publish its URL
#   stop    stop it — or deliberately leave it warm on the box
#
# The memory suite embeds and reranks through app.memory.embeddings, which uses
# a shared HTTP sidecar whenever MEMORY_EMBEDDING_SIDECAR_URL is set and loads
# the ONNX models in-process otherwise. In-process, every pytest-xdist worker
# that touches a memory test loads ~1.8 GB of weights (measured: 2.2 to 2.6 GB
# RSS per worker, 16 workers ≈ 40 GB) and the loads serialize behind a file
# lock. One sidecar loads them once; workers stay ~1 GB and never wait.
#
# Env contract:
#   RUNNER_INDEX          port offset and per-lane file suffix (default 0).
#   SIDECAR_PORT_BASE     base port (default 18200). A second runner user's
#                         stack on the same box sets its own so its sidecars
#                         never share a port with this one (setup.sh puts it in
#                         the runner unit; hooks/job-started.sh reads it too).
#   RUNNER_ENVIRONMENT    "self-hosted" enables keep-warm across jobs.
#   GAIA_CI_RUNDIR,
#   RUNNER_LOCAL_CACHE    where the pid/stamp/log files live.
#   GAIA_SIDECAR_LOG      override the log path.
#   GAIA_TEST_SERVICES_ENV  the services env file to publish the URL into.
#   STOP_SIDECAR=1        stop even on the box (defeat keep-warm).
#   GITHUB_ENV            when set, the sidecar env is appended to it.
#   MEMORY_ONNX_THREADS   inference threads per request (default 2).
#
# Port is offset by RUNNER_INDEX like the service containers, in a range that
# cannot collide with them (chroma at index 2 would otherwise land on the
# sidecar's default 8200). The URL is published to $GITHUB_ENV and to the
# services env file so the test lane and the local profiling harness share it.
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"

# Resolve the per-lane paths every subcommand works with. Called from the
# subcommands, never at source time.
_paths() {
  RUNNER_INDEX="${RUNNER_INDEX:-0}"
  PORT=$(( ${SIDECAR_PORT_BASE:-18200} + RUNNER_INDEX * 100 ))
  URL="http://127.0.0.1:${PORT}"
  REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
  # Per-user run dir (same rule in scripts/ci/test-services.sh, the runner
  # hooks and .github/actions/setup-python-test-env): GitHub-hosted has no
  # RUNNER_LOCAL_CACHE and keeps /tmp.
  RUNDIR="${GAIA_CI_RUNDIR:-${RUNNER_LOCAL_CACHE:-/tmp}}"
  [ -d "$RUNDIR" ] || RUNDIR=/tmp
  LOG="${GAIA_SIDECAR_LOG:-${RUNDIR}/gaia-embedding-sidecar-${RUNNER_INDEX}.log}"
  PIDFILE="${RUNDIR}/gaia-embedding-sidecar-${RUNNER_INDEX}.pid"
  STAMPFILE="${RUNDIR}/gaia-embedding-sidecar-${RUNNER_INDEX}.stamp"
}

# ── the port is the truth, not the pidfile ────────────────────────────────
# A pidfile can be lost (cleaned RUNDIR, a killed job, a box reboot that
# cleared /tmp but not the process) while a live uvicorn keeps holding the
# port. Every later job on that runner index then died with "address already
# in use" — observed on gaia-ci for port 28900. So before starting, ASK THE
# PORT: if something is listening, identify it and only remove it when it is
# our own orphaned sidecar.

port_listener_pid() {
  local port="$1" pid=""
  # ss is present on every Linux runner; -p reveals pids for processes this
  # user owns, which are exactly the ones we may kill.
  if command -v ss >/dev/null 2>&1; then
    pid="$(ss -ltnpH "sport = :${port}" 2>/dev/null | grep -oE 'pid=[0-9]+' | head -n1 | cut -d= -f2)"
  fi
  if [ -z "$pid" ] && command -v lsof >/dev/null 2>&1; then
    pid="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null | head -n1)"
  fi
  printf '%s' "$pid"
}

port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    [ -n "$(ss -ltnH "sport = :${port}" 2>/dev/null)" ]
  elif command -v lsof >/dev/null 2>&1; then
    [ -n "$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null)" ]
  else
    # Neither tool: fall back to the old pidfile-only behaviour rather than
    # refusing to start.
    return 1
  fi
}

kill_pid() {
  local pid="$1" _
  kill "$pid" 2>/dev/null || true
  # Poll instead of a flat sleep: uvicorn exits in ~100 ms.
  for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
  kill -9 "$pid" 2>/dev/null || true
}

# Make PORT ours, or fail loud naming whoever holds it.
claim_port() {
  local port="$1" pid cmd
  port_in_use "$port" || return 0
  pid="$(port_listener_pid "$port")"
  if [ -z "$pid" ]; then
    ci_die "port ${port} is already in use and the listener could not be identified (it belongs to another user). Free it before running this lane."
  fi
  cmd="$(ps -o command= -p "$pid" 2>/dev/null || ps -o args= -p "$pid" 2>/dev/null || true)"
  case "$cmd" in
    *embedding_sidecar*)
      ci_warn "port ${port} is held by an orphaned embedding sidecar (pid ${pid}) with no pidfile — killing it"
      kill_pid "$pid"
      ;;
    *)
      ci_die "port ${port} is held by pid ${pid} (${cmd:-unknown command}), which is not an embedding sidecar. Refusing to start; free the port or set SIDECAR_PORT_BASE."
      ;;
  esac
  if port_in_use "$port"; then
    ci_die "port ${port} is still held after stopping pid ${pid}"
  fi
}

# ── start ─────────────────────────────────────────────────────────────────

cmd_start() {
  _paths
  local STAMP STAMP_TREES REUSED="" deadline

  # Keep-warm (self-hosted): loading the two ONNX models costs 8 s per lane
  # (measured run 33171716529) and the sidecar is stateless, so a healthy one
  # left by the previous job on this runner is reused when nothing it depends
  # on changed. STAMP covers everything the sidecar process imports — the
  # sidecar package itself plus app.memory (embeddings), app.constants (memory
  # constants) and libs/shared/py (wide_events) — and the locked dependency
  # set; a PR that touches any of them gets a fresh process. Tree-object ids
  # from one `git rev-parse` call: no hashing of file contents, so the check is
  # a few ms. If any path is missing the whole call fails and the stamp is
  # "none", which never matches — a safe cold start. Everything else — a dead
  # pid, a failed health probe, a GitHub-hosted runner — cold-starts as before.
  if ! STAMP_TREES="$(git -C "$REPO_ROOT" rev-parse \
      "HEAD:apps/api/app/services/embedding_sidecar" \
      "HEAD:apps/api/app/memory" \
      "HEAD:apps/api/app/constants" \
      "HEAD:libs/shared/py" 2>/dev/null | tr '\n' '-')"; then
    STAMP_TREES="none-"
  fi
  STAMP="${STAMP_TREES}$(git -C "$REPO_ROOT" hash-object uv.lock 2>/dev/null || echo none)"

  if [ "${RUNNER_ENVIRONMENT:-}" = "self-hosted" ] && [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null \
     && [ "$(cat "$STAMPFILE" 2>/dev/null)" = "$STAMP" ] && curl -sf --max-time 5 "${URL}/health" > /dev/null 2>&1; then
    echo "embedding sidecar reused at ${URL} (pid $(cat "$PIDFILE"), warm)"
    REUSED=1
  elif [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    kill "$(cat "$PIDFILE")" 2>/dev/null || true; sleep 1
  fi

  if [ -z "$REUSED" ]; then
    # The pidfile has had its say; now ask the port itself.
    claim_port "$PORT"

    cd "$REPO_ROOT/apps/api"
    # --no-sync: the environment is already synced by the caller; this must not
    # touch the network. The model cache dir is inherited from the environment.
    # Slots = cores / MEMORY_ONNX_THREADS. The default (4 threads → 4 slots on
    # 16 cores) left a 6-worker lane contending on every embed: each miss is a
    # 503 + retry sleep, and the lane measured 227% CPU across 6 workers. 2
    # threads per inference gives 8 slots — more than the lane's workers — at a
    # small per-request latency cost that the parallelism repays.
    export MEMORY_ONNX_THREADS="${MEMORY_ONNX_THREADS:-2}"
    nohup uv run --frozen --no-sync uvicorn app.services.embedding_sidecar.server:app \
      --host 127.0.0.1 --port "$PORT" --log-level warning > "$LOG" 2>&1 < /dev/null &
    echo $! > "$PIDFILE"

    # Model load is the startup cost (~5-20s from a warm disk cache).
    deadline=$((SECONDS + 180))
    until curl -sf "${URL}/health" > /dev/null 2>&1; do
      if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        tail -30 "$LOG"; ci_die "embedding sidecar exited during startup"
      fi
      if (( SECONDS >= deadline )); then
        tail -30 "$LOG"; ci_die "embedding sidecar not healthy after 180s"
      fi
      sleep 1
    done
    echo "$STAMP" > "$STAMPFILE"
    echo "embedding sidecar ready at ${URL} (pid $(cat "$PIDFILE"), $((SECONDS))s)"
  fi

  # Retry backoff for the test lane. The client sleeps a FIXED
  # MEMORY_SIDECAR_RETRY_MAX_WAIT_SECONDS between attempts, and the sidecar
  # 503s a request that cannot get one of its (cores / MEMORY_ONNX_THREADS)
  # inference slots. In prod that pairing is right: a 5s pause rides out a
  # restart. Under xdist it is the opposite of what we want — every worker
  # funnels through the one sidecar, so slot contention is the NORMAL state,
  # and each contended call pays a 5s sleep in which the worker does nothing.
  # That idle is what shows up as 227% total CPU across 6 workers. A short
  # backoff keeps the retry (an overloaded sidecar is still ridden out,
  # exhaustion still fails loud) without parking the worker for whole seconds.
  local sidecar_env=(
    "MEMORY_EMBEDDING_SIDECAR_URL=${URL}"
    "MEMORY_SIDECAR_RETRY_MAX_WAIT_SECONDS=${MEMORY_SIDECAR_RETRY_MAX_WAIT_SECONDS:-0.25}"
  )

  if [ -n "${GITHUB_ENV:-}" ]; then
    printf '%s\n' "${sidecar_env[@]}" >> "$GITHUB_ENV"
  fi
  local services_env_file="${GAIA_TEST_SERVICES_ENV:-${RUNDIR}/gaia-test-services-${RUNNER_INDEX}.env}"
  if [ -f "$services_env_file" ]; then
    grep -vE '^(MEMORY_EMBEDDING_SIDECAR_URL|MEMORY_SIDECAR_RETRY_MAX_WAIT_SECONDS)=' \
      "$services_env_file" > "$services_env_file.tmp" || true
    printf '%s\n' "${sidecar_env[@]}" >> "$services_env_file.tmp"
    mv "$services_env_file.tmp" "$services_env_file"
  fi
  ci_ok "embedding sidecar: serving ${URL}"
}

# ── stop ──────────────────────────────────────────────────────────────────

# Never fails the caller: it runs in teardown positions.
cmd_stop() {
  set +e
  _paths
  local pid
  # Self-hosted runners keep the sidecar warm for the next job on this runner
  # (`start` reuses it while its stamp matches). STOP_SIDECAR=1 forces a stop.
  if [ "${RUNNER_ENVIRONMENT:-}" = "self-hosted" ] && [ "${STOP_SIDECAR:-0}" != "1" ] \
     && [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    ci_ok "embedding sidecar left warm (runner index ${RUNNER_INDEX}, pid $(cat "$PIDFILE"))"
    exit 0
  fi
  if [ -f "$PIDFILE" ]; then
    pid="$(cat "$PIDFILE")"
    if kill -0 "$pid" 2>/dev/null; then
      kill_pid "$pid"
    fi
    rm -f "$PIDFILE"
  fi
  # The pidfile may have been lost while the process lives; do not leave the
  # port held for the next job on this runner index.
  if port_in_use "$PORT"; then
    pid="$(port_listener_pid "$PORT")"
    if [ -n "$pid" ] && ps -o command= -p "$pid" 2>/dev/null | grep -q embedding_sidecar; then
      ci_warn "port ${PORT} still held by an orphaned sidecar (pid ${pid}) — stopping it"
      kill_pid "$pid"
    fi
  fi
  ci_ok "embedding sidecar stopped (runner index ${RUNNER_INDEX})"
  exit 0
}

usage() {
  cat >&2 <<'USAGE'
Usage: embedding-sidecar.sh <start|stop>

  start   start (or reuse) the sidecar and publish MEMORY_EMBEDDING_SIDECAR_URL
  stop    stop it, or leave it warm on the box (STOP_SIDECAR=1 forces a stop)
USAGE
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    start) cmd_start "$@" ;;
    stop)  cmd_stop "$@" ;;
    *)
      echo "embedding-sidecar.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
