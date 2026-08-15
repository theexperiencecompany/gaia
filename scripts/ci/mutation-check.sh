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

# 2. Flatten to "module testfiles changed-ranges" lines (one per line — the
#    newline matters: xargs-style grouping across concatenated lines glues
#    the JSON to the next module name when a range list is empty).
#
#    The test files are a LIST, and both list fields are compact JSON so
#    neither can contain a space and shift the fields the read below relies
#    on. A module is mutated against every test file that references it, not
#    whichever one sorted first: the choice moves the answer by orders of
#    magnitude (app/agents/tools/core/retrieval.py leaves 3 survivors under
#    the first hit and 288 under a file the gate was discarding).
#
#    Reads either key so the matrix change and this one can land
#    independently: "testfiles" is the list the matrix emits now, "testfile"
#    the single path it emitted before. Neither present is a hard error, never
#    a quietly skipped module.
python3 - << 'EOF'
import json

modules = json.load(open("/tmp/mutation-matrix.json"))
with open("/tmp/mutation-modules.txt", "w") as f:
    for m in modules:
        if "testfiles" in m:
            testfiles = m["testfiles"]
        elif "testfile" in m:
            testfiles = [m["testfile"]]
        else:
            raise SystemExit(
                f"::error::mutation gate: matrix entry for {m.get('module')} carries neither "
                "'testfiles' nor 'testfile' — nothing says what to run against it"
            )
        compact = json.dumps(testfiles, separators=(",", ":"))
        ranges = json.dumps(m["changed_lines"], separators=(",", ":"))
        f.write(f"{m['module']} {compact} {ranges}\n")
print(f"{len(modules)} module(s) to mutate")
EOF

# 3. No changed app modules — nothing to prove.
if [ ! -s /tmp/mutation-modules.txt ]; then
  echo "no changed app modules — nothing to mutate"
  exit 0
fi

# 4. Run one mutation check per module with bounded parallelism. A plain
#    read loop (not xargs) so a module with an empty changed-lines JSON
#    (`[]`) can never shift the fields between invocations.
FAILED=0
while read -r module testfiles ranges; do
  bash scripts/test/mutation.sh "$module" "$testfiles" "${ranges:-[]}" &
  if [ "$(jobs -r -p | wc -l)" -ge 4 ]; then
    wait -n || FAILED=1
  fi
done < /tmp/mutation-modules.txt
wait || FAILED=1
exit "$FAILED"
