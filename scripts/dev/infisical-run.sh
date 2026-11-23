#!/usr/bin/env bash
# Run a command with the team's Infisical development secrets, where the caller's own
# environment wins.
#
# `infisical run` overwrites every variable it holds, so a value set in this shell or
# in .env.worktree (this worktree's REDIS_URL, MONGO_DB_NAME, ports) silently lost to
# the shared development value and pointed a sim run at another stack. The caller's
# environment is captured before infisical runs and re-applied inside it.
#
# Usage: infisical-run.sh <command> [args...]

set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "usage: infisical-run.sh <command> [args...]" >&2
  exit 2
fi

# Readonly variables cannot be re-declared and are not the caller's to give anyway.
GAIA_CALLER_ENV="$(export -p | grep -v '^declare -[a-z]*r')"
export GAIA_CALLER_ENV
# shellcheck disable=SC2016 # expanded by the inner shell, after infisical has injected its secrets
exec infisical run --env=development --silent -- \
  bash -c 'eval "$GAIA_CALLER_ENV"; unset GAIA_CALLER_ENV; exec "$@"' infisical-run "$@"
