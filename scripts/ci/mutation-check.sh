#!/usr/bin/env bash
# Mutation gate orchestrator: compute the changed-module list and run the
# mutation check for each (zero survivors required), with bounded
# parallelism. Fails the lane on: changed app code with no test file
# anywhere, zero mutants (tests do not cover the changed lines), any
# surviving mutant, or the lane budget being exceeded.
#
# Used by the test-mutation lane (code-quality.yml) — the workflow step is
# just `bash scripts/ci/mutation-check.sh [--shard 1/3]`; all logic lives here.
# Sharding: --shard N/T keeps only modules where (index % T) == (N-1), so a
# 3-shard matrix job fans the 30m budget across 3 runners (A8). Without the
# flag the script runs all modules (single-runner backwards compat).
#
# Skip rule (A8): modules with <5 changed lines are dropped in
# mutation-matrix.py before this script ever sees them — tiny diffs cannot
# justify the full mutmut cycle. This file also honors an empty list as
# "nothing to mutate" (clean exit 0).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

# --shard N/T (optional): deterministic sharding for the GitHub matrix.
SHARD_N=""
SHARD_T=""
if [[ "${1:-}" == "--shard" ]]; then
  if [[ -z "${2:-}" ]]; then
    echo "usage: $0 [--shard N/T]  e.g. --shard 1/3" >&2
    exit 2
  fi
  SHARD_SPEC="$2"
  shift 2
  SHARD_N="${SHARD_SPEC%%/*}"
  SHARD_T="${SHARD_SPEC##*/}"
  if ! [[ "$SHARD_N" =~ ^[0-9]+$ && "$SHARD_T" =~ ^[0-9]+$ && "$SHARD_N" -ge 1 && "$SHARD_T" -ge 1 && "$SHARD_N" -le "$SHARD_T" ]]; then
    echo "invalid --shard spec '$SHARD_SPEC' — expected N/T with 1 <= N <= T" >&2
    exit 2
  fi
fi
export SHARD_N SHARD_T

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
import os

shard_n = os.environ.get("SHARD_N", "")
shard_t = os.environ.get("SHARD_T", "")


modules = json.load(open("/tmp/mutation-matrix.json"))
# Shard filter (A8): keep only modules where index % T == N-1.
if shard_n and shard_t:
    n = int(shard_n)
    t = int(shard_t)
    modules = [m for i, m in enumerate(modules) if (i % t) == (n - 1)]
    print(f"shard {n}/{t}: {len(modules)} module(s) after sharding", flush=True)

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
