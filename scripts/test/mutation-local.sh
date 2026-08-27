#!/usr/bin/env bash
# Run the FULL mutation gate locally, exactly as the CI lane runs it.
#
#   bash scripts/test/mutation-local.sh              # every changed module
#   bash scripts/test/mutation-local.sh app/x.py ... # only these modules
#
# The CI lane splits the same module list across 12 GitHub jobs; there is no
# second gate here, just the same matrix run on one machine. Modules run
# concurrently (override with MUTATION_JOBS=1 for readable output), each into
# its own log under verify-logs/mutation/.
#
# Why this exists: the lane's own command (`mutation-plan.sh && mutation-shard.sh`)
# is CI-shaped — the plan writes its matrix to $GITHUB_OUTPUT and the shard
# reads $GROUP from the job matrix, so run outside Actions the shard starts
# with no GROUP and mutates nothing. This wires the two together locally.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

LOG_DIR="verify-logs/mutation"
mkdir -p "$LOG_DIR"

if [ "$#" -gt 0 ]; then
  MATRIX="$(printf '%s\n' "$@" | sed 's|^apps/api/||; s|^|apps/api/|' |
    python3 scripts/ci/mutation-matrix.py)" || exit 1
else
  MATRIX="$(bash scripts/ci/mutation-matrix.sh)" || exit 1
fi

MODULE_COUNT="$(MATRIX="$MATRIX" python3 -c 'import json,os;print(len(json.loads(os.environ["MATRIX"])))')"
if [ "$MODULE_COUNT" = "0" ]; then
  echo "mutation: no changed app modules — nothing to mutate"
  exit 0
fi

# One TSV row per module, the same three fields mutation-shard.sh reads.
TSV="$(mktemp)"
trap 'rm -f "$TSV"' EXIT
MATRIX="$MATRIX" python3 - > "$TSV" <<'PY'
import json
import os

for entry in json.loads(os.environ["MATRIX"]):
    print(
        "\t".join(
            (
                entry["module"],
                json.dumps(entry["testfiles"], separators=(",", ":")),
                json.dumps(entry["changed_lines"], separators=(",", ":")),
            )
        )
    )
PY

echo "mutation: $MODULE_COUNT module(s), logs in $LOG_DIR/"

# Each module is its own single-module shard: same runner as CI, so a local
# pass and a lane pass mean the same thing.
run_one() {
  local module="$1" testfiles="$2" ranges="$3"
  local slug="${module//\//_}"
  GROUP="$(module="$module" testfiles="$testfiles" ranges="$ranges" python3 -c '
import json
import os

print(
    json.dumps(
        [{k: os.environ[k] for k in ("module", "testfiles", "ranges")}],
        separators=(",", ":"),
    )
)')" \
    SHARD_LOG="$LOG_DIR/$slug.log" \
    bash scripts/ci/mutation-shard.sh > "$LOG_DIR/$slug.out" 2>&1
  local rc=$?
  if [ "$rc" = "0" ]; then
    echo "  pass  $module"
  else
    echo "  FAIL  $module  ($LOG_DIR/$slug.log)"
  fi
  return $rc
}

JOBS="${MUTATION_JOBS:-4}"
rc=0
running=0
declare -a FAILED=()
while IFS=$'\t' read -r module testfiles ranges; do
  [ -n "$module" ] || continue
  run_one "$module" "$testfiles" "$ranges" &
  running=$((running + 1))
  if [ "$running" -ge "$JOBS" ]; then
    wait -n 2> /dev/null || rc=1
    running=$((running - 1))
  fi
done < "$TSV"
while [ "$running" -gt 0 ]; do
  wait -n 2> /dev/null || rc=1
  running=$((running - 1))
done

# Re-derive the verdict from the logs: `wait -n` gives a count, not a name, and
# a list of which modules failed is the only output worth acting on.
FAILED=()
while IFS=$'\t' read -r module _ _; do
  [ -n "$module" ] || continue
  slug="${module//\//_}"
  grep -q "MUTATION FAILED" "$LOG_DIR/$slug.log" 2> /dev/null && FAILED+=("$module")
done < "$TSV"

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo
  echo "mutation: ${#FAILED[@]} module(s) with survivors on changed lines:"
  printf '  %s\n' "${FAILED[@]}"
  exit 1
fi
[ "$rc" = "0" ] || exit "$rc"
echo "mutation: all $MODULE_COUNT module(s) clean"
