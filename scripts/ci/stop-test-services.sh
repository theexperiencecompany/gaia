#!/usr/bin/env bash
# stop-test-services.sh — tear down the service containers this runner started.
#
# Reads the container list start-test-services.sh recorded, so the names stay
# correct as the per-runner index changes and no caller has to repeat them.
# Never fails the caller: teardown runs in trap/cleanup positions where a
# missing container is normal, not an error.
set -uo pipefail

RUNNER_INDEX="${RUNNER_INDEX:-0}"
SERVICES_ENV_FILE="${GAIA_TEST_SERVICES_ENV:-/tmp/gaia-test-services-${RUNNER_INDEX}.env}"

if [ -f "$SERVICES_ENV_FILE" ]; then
  CONTAINERS="$(grep '^GAIA_TEST_CONTAINERS=' "$SERVICES_ENV_FILE" | cut -d= -f2- | tr -d '"')"
else
  # The env file is gone (interrupted run, cleaned /tmp) — fall back to the
  # naming convention so containers are never left holding their ports.
  CONTAINERS="gaia-test-postgres-${RUNNER_INDEX} gaia-test-redis-${RUNNER_INDEX} gaia-test-mongo-${RUNNER_INDEX} gaia-test-chroma-${RUNNER_INDEX} gaia-test-rabbitmq-${RUNNER_INDEX}"
fi

# The container list is intentionally word-split into separate arguments.
# shellcheck disable=SC2086
[ -n "${CONTAINERS// /}" ] && docker rm -f $CONTAINERS >/dev/null 2>&1
echo "test services torn down (runner index ${RUNNER_INDEX})"
exit 0
