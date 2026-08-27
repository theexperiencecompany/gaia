#!/usr/bin/env bash
# Mutation gate orchestrator: compute the changed-module list and run the
# mutation check for each (zero survivors required), with bounded
# parallelism. Fails the lane on: changed app code with no test file
# anywhere, zero mutants (tests do not cover the changed lines), any
# surviving mutant, or the lane budget being exceeded.
#
# Used by the test-mutation lane (code-quality.yml) — the workflow step is
# just `bash scripts/ci/mutation-check.sh`; all logic lives here.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

# 1. Changed app modules + their test files, as JSON. The matrix script
#    fails loudly (exit 1) when a changed module has no test file.
bash scripts/ci/mutation-matrix.sh > /tmp/mutation-matrix.json

# 2. Flatten to "module testfile changed-ranges" lines (one per line — the
#    newline matters: xargs-style grouping across concatenated lines glues
#    the JSON to the next module name when a range list is empty).
python3 - << 'EOF'
import json

modules = json.load(open("/tmp/mutation-matrix.json"))
with open("/tmp/mutation-modules.txt", "w") as f:
    for m in modules:
        f.write(f"{m['module']} {m['testfile']} {json.dumps(m['changed_lines'], separators=(',', ':'))}\n")
print(f"{len(modules)} module(s) to mutate")
EOF

# 3. No changed app modules — nothing to prove.
if [ ! -s /tmp/mutation-modules.txt ]; then
  echo "no changed app modules — nothing to mutate"
  exit 0
fi

# 4. Size the run to the machine. Two levels of parallelism multiply here:
#    modules run concurrently, and mutmut forks --max-children mutant workers
#    inside each. Handing both `nproc` would oversubscribe 16 cores by an
#    order of magnitude and thrash. Split one budget between them instead.
#
#    Leave 2 cores for the runner agent, docker, and the OS. Most PRs touch
#    one or two modules, so weighting toward mutmut's children (rather than
#    module fan-out) is what actually keeps the cores busy.
NPROC="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
BUDGET="${MUTATION_CPU_BUDGET:-$(( NPROC > 3 ? NPROC - 2 : 1 ))}"
MODULE_COUNT="$(wc -l < /tmp/mutation-modules.txt | tr -d ' ')"

MODULE_PAR="$MODULE_COUNT"
[ "$MODULE_PAR" -gt 4 ] && MODULE_PAR=4
[ "$MODULE_PAR" -lt 1 ] && MODULE_PAR=1
[ "$MODULE_PAR" -gt "$BUDGET" ] && MODULE_PAR="$BUDGET"

CHILDREN=$(( BUDGET / MODULE_PAR ))
[ "$CHILDREN" -lt 1 ] && CHILDREN=1
export MUTMUT_MAX_CHILDREN="${MUTMUT_MAX_CHILDREN:-$CHILDREN}"

echo "mutation: ${MODULE_COUNT} module(s) on ${NPROC} vCPUs — budget ${BUDGET}," \
     "${MODULE_PAR} module(s) in parallel x ${MUTMUT_MAX_CHILDREN} mutant worker(s)"

# 5. Run one mutation check per module with bounded parallelism. A plain
#    read loop (not xargs) so a module with an empty changed-lines JSON
#    (`[]`) can never shift the fields between invocations.
#
#    Each child records its own exit status in a file rather than relying on
#    `wait`: a bare `wait` returns 0 no matter how its children exited, so
#    the previous `wait || FAILED=1` silently passed the lane whenever a
#    surviving mutant was found by any module still running at the end.
STATUS_DIR="$(mktemp -d)"
trap 'rm -rf "$STATUS_DIR"' EXIT

idx=0
while read -r module testfile ranges; do
  idx=$((idx + 1))
  (
    if bash scripts/test/mutation.sh "$module" "$testfile" "${ranges:-[]}"; then
      echo 0 > "$STATUS_DIR/$idx"
    else
      echo "$?" > "$STATUS_DIR/$idx"
    fi
  ) &
  while [ "$(jobs -r -p | wc -l)" -ge "$MODULE_PAR" ]; do
    wait -n 2>/dev/null || true
  done
done < /tmp/mutation-modules.txt
wait

FAILED=0
for status_file in "$STATUS_DIR"/*; do
  [ -e "$status_file" ] || continue
  if [ "$(cat "$status_file")" != "0" ]; then
    FAILED=1
  fi
done
exit "$FAILED"
