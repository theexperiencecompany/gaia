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
# Per-user run dir (same rule in scripts/ci/start-embedding-sidecar.sh,
# stop-embedding-sidecar.sh, shared-test-services.sh, the runner hooks and
# .github/actions/setup-python-test-env): GitHub-hosted has no
# RUNNER_LOCAL_CACHE and keeps /tmp.
RUNDIR="${GAIA_CI_RUNDIR:-${RUNNER_LOCAL_CACHE:-/tmp}}"
PORT_BASE="${SIDECAR_PORT_BASE:-18200}"
echo "::group::runner hygiene (instance ${IDX})"
# Containers this instance's previous job may have left (names are suffixed
# with the runner index by start-test-services.sh).
LEFT="$(docker ps -aq --filter "name=gaia-test-.*-${IDX}$" 2>/dev/null || true)"
if [ -n "$LEFT" ]; then
  # shellcheck disable=SC2086
  timeout 60 docker rm -f $LEFT >/dev/null 2>&1 && echo "removed leaked service containers: $(echo "$LEFT" | wc -l)"
fi
# The sidecar is left warm between jobs on purpose (scripts/ci/
# stop-embedding-sidecar.sh); only a dead or unresponsive one is a leak.
if [ -f "${RUNDIR}/gaia-embedding-sidecar-${IDX}.pid" ]; then
  pid="$(cat "${RUNDIR}/gaia-embedding-sidecar-${IDX}.pid")"
  if ! kill -0 "$pid" 2>/dev/null || ! curl -sf --max-time 5 "http://127.0.0.1:$((PORT_BASE + IDX * 100))/health" >/dev/null 2>&1; then
    kill "$pid" 2>/dev/null && echo "killed unresponsive embedding sidecar (pid $pid)"
    rm -f "${RUNDIR}/gaia-embedding-sidecar-${IDX}.pid" "${RUNDIR}/gaia-embedding-sidecar-${IDX}.stamp"
  fi
fi
# Shared-services namespace left by an interrupted job.
S="${RUNNER_LOCAL_CACHE:-$HOME/ci-cache}/shared-test-services.sh"
# Only when this index actually prepared a namespace (the env file is the marker):
# a reset is ~10-15s of docker execs, and it was running on every job, twice.
[ -x "$S" ] && [ -f "${RUNDIR}/gaia-test-services-${IDX}.env" ] && timeout 90 bash "$S" reset "$IDX" >/dev/null 2>&1 && echo "reset shared-services namespace r${IDX}"
# Stale per-index env file so a new job cannot read old ports.
rm -f "${RUNDIR}/gaia-test-services-${IDX}.env"
# Mutation work trees scripts/test/mutation.sh stages in RAM (/dev/shm/
# .mutation-<pid>) and cannot clean up after a SIGKILL. They are not scoped
# to an index, so only ones older than any live run (60 min) are swept; a
# failure here is never the job's problem.
if [ -d /dev/shm ]; then
  swept="$(find /dev/shm -mindepth 1 -maxdepth 1 -name '.mutation-*' -mmin +60 -print -exec rm -rf {} + 2>/dev/null | wc -l)" || swept=0
  [ "${swept:-0}" -gt 0 ] && echo "swept orphaned mutation trees from /dev/shm: $swept"
fi
# Persistent workspace: actions/checkout runs with clean: false on this box,
# so untracked build output would otherwise survive between jobs. Clean it
# here, sparing only the caches that make the instance fast. Patterns are
# gitignore-style, so `node_modules` matches at any depth.
# The runner exports GITHUB_WORKSPACE to its hooks; the fallback mirrors
# setup.sh's layout (<install root>/actions-runner-<runner name>/_work/gaia/gaia).
WS="${GITHUB_WORKSPACE:-${RUNNER_INSTALL_ROOT:-$HOME}/actions-runner-${RUNNER_NAME:-gaia-home-${IDX}}/_work/gaia/gaia}"
if [ -d "$WS/.git" ]; then
  # __pycache__ is kept: wiping it recompiled 812 app + 168 test modules in
  # EVERY xdist worker of every job (+3.5 CPU-s per worker, measured
  # 2026-08-28; unit-b collection 17.2 s cold vs 10.8 s warm).
  n=$(git -C "$WS" clean -ffdx -e node_modules -e .venv -e .nx/cache -e apps/web/.next/cache -e .mypy_cache -e .pytest_cache -e __pycache__ 2>/dev/null | wc -l)
  echo "scoped clean of persistent workspace: removed $n untracked path(s)"
  # A shallow workspace makes every `fetch-depth: 0` checkout run
  # `git fetch --unshallow` against GitHub (measured 21 s per detect job).
  # Pay it once here, then the per-job fetch is a ~1 s delta.
  if [ -f "$WS/.git/shallow" ]; then
    timeout 300 git -C "$WS" fetch --unshallow --quiet --no-tags origin 2>/dev/null \
      && echo "unshallowed persistent workspace (one-time)"
  fi
fi
# Report what the job is starting with — the numbers that decide parallelism.
echo "load=$(cut -d' ' -f1-3 /proc/loadavg) mem_avail=$(free -g | awk '/^Mem:/{print $7}')G disk_free=$(df -h / | awk 'NR==2{print $4}')"
echo "::endgroup::"
exit 0
