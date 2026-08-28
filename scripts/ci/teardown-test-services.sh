#!/usr/bin/env bash
# teardown-test-services.sh — release everything a Python test lane holds.
#
# Every lane that ran setup-python-test-env with services must call this from
# an `if: always()` step. On the shared home box the lane's namespace in the
# persistent service containers is reset for the next job; on GitHub-hosted
# runners the per-job containers are simply stopped. The sidecar stop is the
# same on both.
set -uo pipefail

bash scripts/ci/stop-embedding-sidecar.sh
if [[ "${RUNNER_ENVIRONMENT:-}" == "self-hosted" ]]; then
  bash scripts/ci/shared-test-services.sh reset "${RUNNER_INDEX:-0}"
else
  bash scripts/ci/stop-test-services.sh
fi
