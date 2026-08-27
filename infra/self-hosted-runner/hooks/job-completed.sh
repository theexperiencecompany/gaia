#!/usr/bin/env bash
# job-completed.sh — runner job hook (ACTIONS_RUNNER_HOOK_JOB_COMPLETED).
# Belt and braces for the workflow's own teardown steps: if a job was
# cancelled before they ran, its containers and sidecar still go away here.
set -uo pipefail
IDX="${RUNNER_INDEX:-0}"
LEFT="$(docker ps -aq --filter "name=gaia-test-.*-${IDX}$" 2>/dev/null || true)"
# shellcheck disable=SC2086
[ -n "$LEFT" ] && docker rm -f $LEFT >/dev/null 2>&1
if [ -f "/tmp/gaia-embedding-sidecar-${IDX}.pid" ]; then
  kill "$(cat "/tmp/gaia-embedding-sidecar-${IDX}.pid")" 2>/dev/null; rm -f "/tmp/gaia-embedding-sidecar-${IDX}.pid"
fi
S="${RUNNER_LOCAL_CACHE:-$HOME/ci-cache}/shared-test-services.sh"
[ -x "$S" ] && bash "$S" reset "$IDX" >/dev/null 2>&1
exit 0
