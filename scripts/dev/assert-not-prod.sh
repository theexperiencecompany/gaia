#!/usr/bin/env bash
# Refuse to enable dev-only modes (the auth bypass and the scripted sim LLM) when
# the API would run in production.
#
# The dev auth bypass authenticates EVERY request as one fixed user, and sim mode
# replaces the model with a local stub — both are catastrophic in production. The
# API's get_settings() already hard-fails on this at boot, but that is deep in
# startup; this catches it at the mise-task boundary with a clear message before
# anything boots.
#
# Mirrors pydantic's ENV resolution: an OS env var wins, otherwise apps/api/.env.
#
# Usage: assert-not-prod.sh "<mode description>"

set -euo pipefail

mode="${1:-dev mode}"

resolved_env="${ENV:-}"
if [ -z "$resolved_env" ] && [ -f apps/api/.env ]; then
  # Last uncommented ENV= line wins, matching how a later .env entry overrides.
  resolved_env="$(grep -E '^[[:space:]]*ENV=' apps/api/.env \
    | tail -1 | cut -d= -f2- | tr -d '[:space:]"'\''' || true)"
fi

if [ "$resolved_env" = "production" ]; then
  echo "ERROR: refusing to enable $mode with ENV=production." >&2
  echo "       The dev auth bypass and the sim LLM must never run in production." >&2
  echo "       Use ENV=development for local driving; drop the --agent/--sim flag otherwise." >&2
  exit 1
fi
