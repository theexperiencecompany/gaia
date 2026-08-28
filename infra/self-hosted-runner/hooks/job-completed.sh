#!/usr/bin/env bash
# job-completed.sh — runner job hook (ACTIONS_RUNNER_HOOK_JOB_COMPLETED).
# Belt and braces for the workflow's own teardown steps: if a job was
# cancelled before they ran, its containers still go away here. The embedding
# sidecar is deliberately left warm (scripts/ci/stop-embedding-sidecar.sh);
# job-started.sh replaces it if it is dead or unresponsive.
set -uo pipefail
IDX="${RUNNER_INDEX:-0}"
LEFT="$(docker ps -aq --filter "name=gaia-test-.*-${IDX}$" 2>/dev/null || true)"
# shellcheck disable=SC2086
[ -n "$LEFT" ] && timeout 60 docker rm -f $LEFT >/dev/null 2>&1
S="${RUNNER_LOCAL_CACHE:-$HOME/ci-cache}/shared-test-services.sh"
# Hard bound: a hook that blocks (docker daemon busy with a build, a wedged
# service) keeps the job in "Complete runner" — measured 25+ min holding the
# runner slot AND the workflow's concurrency group, which left the next run
# pending with zero jobs. Better to leave a namespace dirty (the next
# job-started hook resets it) than to wedge the pool.
[ -x "$S" ] && [ -f "/tmp/gaia-test-services-${IDX}.env" ] && timeout 90 bash "$S" reset "$IDX" >/dev/null 2>&1
exit 0
