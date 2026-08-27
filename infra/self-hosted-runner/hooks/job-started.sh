#!/usr/bin/env bash
# job-started.sh — runner job hook (ACTIONS_RUNNER_HOOK_JOB_STARTED).
#
# Ephemeral-grade hygiene without --ephemeral. A true ephemeral runner
# de-registers after every job and needs a fresh registration token minted
# per job, which means a GitHub PAT living on this box. The failure class
# ephemeral runners prevent is state leaking between jobs — containers left
# holding ports, stray processes, a sidecar from a cancelled job — and the
# runner's job hooks let us kill exactly that state, scoped to THIS runner
# instance's index, before every job. Runs with the job's environment.
set -uo pipefail
IDX="${RUNNER_INDEX:-0}"
echo "::group::runner hygiene (instance ${IDX})"
# Containers this instance's previous job may have left (names are suffixed
# with the runner index by start-test-services.sh).
LEFT="$(docker ps -aq --filter "name=gaia-test-.*-${IDX}$" 2>/dev/null || true)"
if [ -n "$LEFT" ]; then
  # shellcheck disable=SC2086
  docker rm -f $LEFT >/dev/null 2>&1 && echo "removed leaked service containers: $(echo "$LEFT" | wc -l)"
fi
# A sidecar from an interrupted job.
if [ -f "/tmp/gaia-embedding-sidecar-${IDX}.pid" ]; then
  pid="$(cat "/tmp/gaia-embedding-sidecar-${IDX}.pid")"
  kill "$pid" 2>/dev/null && echo "killed leaked embedding sidecar (pid $pid)"
  rm -f "/tmp/gaia-embedding-sidecar-${IDX}.pid"
fi
# Shared-services namespace left by an interrupted job.
S="${RUNNER_LOCAL_CACHE:-$HOME/ci-cache}/shared-test-services.sh"
[ -x "$S" ] && bash "$S" reset "$IDX" >/dev/null 2>&1 && echo "reset shared-services namespace r${IDX}"
# Stale per-index env file so a new job cannot read old ports.
rm -f "/tmp/gaia-test-services-${IDX}.env"
# Persistent workspace: actions/checkout runs with clean: false on this box,
# so untracked build output would otherwise survive between jobs. Clean it
# here, sparing only the caches that make the instance fast. Patterns are
# gitignore-style, so `node_modules` matches at any depth.
WS="$HOME/actions-runner-gaia-home-${IDX}/_work/gaia/gaia"
if [ -d "$WS/.git" ]; then
  n=$(git -C "$WS" clean -ffdx -e node_modules -e .venv -e .nx/cache -e apps/web/.next/cache -e .mypy_cache -e .pytest_cache 2>/dev/null | wc -l)
  echo "scoped clean of persistent workspace: removed $n untracked path(s)"
fi
# Report what the job is starting with — the numbers that decide parallelism.
echo "load=$(cut -d' ' -f1-3 /proc/loadavg) mem_avail=$(free -g | awk '/^Mem:/{print $7}')G disk_free=$(df -h / | awk 'NR==2{print $4}')"
echo "::endgroup::"
exit 0
