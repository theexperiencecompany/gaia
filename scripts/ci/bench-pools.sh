#!/usr/bin/env bash
# bench-pools.sh — time each check in $CHECKS through mise ci:local: once cold
# (nx cache skipped), then twice with the local nx cache on (fill, then hit).
# Throwaway benchmark for the bench/m4-pools branch; never merged.
set -euo pipefail
summary="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
echo "| check | cold s | warm s (2nd cached run) | result |" >> "$summary"
echo "|---|---|---|---|" >> "$summary"

timed() {  # timed <label> <check> [env...] -> prints "<seconds> <exit code>"
  local label="$1" check="$2" start rc=0
  shift 2
  start=$(date +%s)
  env "$@" uv run --no-project python scripts/dev/gaia_verify.py --all --with-heavy --only "$check" \
    > "/tmp/bench-$check-$label.log" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] || tail -n 30 "/tmp/bench-$check-$label.log" >&2
  echo "$(( $(date +%s) - start )) $rc"
}

for check in $CHECKS; do
  read -r cold cold_rc < <(timed cold "$check" NX_SKIP_NX_CACHE=true)
  timed fill "$check" -u NX_SKIP_NX_CACHE > /dev/null
  read -r warm warm_rc < <(timed warm "$check" -u NX_SKIP_NX_CACHE)
  result=$([ "$cold_rc" -eq 0 ] && [ "$warm_rc" -eq 0 ] && echo pass || echo "FAIL (cold $cold_rc, warm $warm_rc)")
  echo "bench: $check cold=${cold}s warm=${warm}s $result"
  echo "| $check | $cold | $warm | $result |" >> "$summary"
done
