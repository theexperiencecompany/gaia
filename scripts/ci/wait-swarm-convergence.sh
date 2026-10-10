#!/usr/bin/env bash
# Block until every named Swarm service has finished rolling to the new task set.
#
# Usage: wait-swarm-convergence.sh <service> [service...]
# Env:   DEPLOY_CONVERGE_TIMEOUT (seconds, default 600)
#
# Why this is not a running-task count. Every app service deploys with
# `order: start-first`, so during a roll the OLD task stays desired-state=running
# until the new one is healthy. Counting "at least one running task" therefore
# reports success from the OLD task the instant `stack deploy` returns — before a
# single new task has started — and any later auto-rollback is never observed.
# At N replicas it is worse still: N-1 can be crash-looping and the count passes.
#
# Swarm's own answer is `UpdateStatus.State`: `updating` while the roll is in
# flight, `completed` once every task is replaced and healthy, `paused` or
# `rollback_*` when it failed. An empty value means the service was not touched
# by this deploy, which is also converged. Both axes are checked — the update
# state AND the declared replica count — because `completed` alone would pass a
# service someone had scaled to 0.
set -euo pipefail

[ "$#" -gt 0 ] || { echo "::error::no services given" >&2; exit 2; }

SERVICES=("$@")
TIMEOUT="${DEPLOY_CONVERGE_TIMEOUT:-600}"
DEADLINE=$(( $(date +%s) + TIMEOUT ))

svc_field() {
  docker --context prod service inspect "gaia-prod_$1" --format "$2" 2>/dev/null || echo ""
}

echo "Waiting for ${SERVICES[*]} to converge (up to ${TIMEOUT}s)..."

while true; do
  pending=""
  status=""

  for svc in "${SERVICES[@]}"; do
    state=$(svc_field "$svc" '{{.UpdateStatus.State}}')

    case "$state" in
      rollback_*|paused)
        echo "rolled_back=true" >> "${GITHUB_OUTPUT:-/dev/null}"
        echo "::error::gaia-prod_${svc} did not roll out (update state: ${state})"
        exit 1
        ;;
    esac

    # Declared replicas; empty for a global-mode service, which has no count.
    want=$(svc_field "$svc" '{{if .Spec.Mode.Replicated}}{{.Spec.Mode.Replicated.Replicas}}{{end}}')
    running=$(docker --context prod service ps "gaia-prod_${svc}" \
      --filter desired-state=running --format '{{.CurrentState}}' 2>/dev/null \
      | grep -c "^Running" || true)
    running=${running:-0}

    status="${status}${svc}=${running}/${want:-?}(${state:-untouched}) "

    # `updating` is the only state that is still in flight. Everything else is
    # either done or already handled above.
    if [ "$state" = "updating" ] || { [ -n "$want" ] && [ "$running" -lt "$want" ]; }; then
      pending="${pending}${svc} "
    fi
  done

  if [ -z "$pending" ]; then
    echo "All app services converged (${status})"
    break
  fi

  now=$(date +%s)
  if [ "$now" -ge "$DEADLINE" ]; then
    echo "timed_out=true" >> "${GITHUB_OUTPUT:-/dev/null}"
    echo "::error::services did not converge within ${TIMEOUT}s (${status})"
    exit 1
  fi

  echo "  ... waiting (${status}$(( DEADLINE - now ))s remaining)"
  sleep 15
done
