#!/usr/bin/env bash
# Mutation gate orchestrator: compute the changed-module list and run the
# mutation check for each (zero survivors required), with bounded
# parallelism. Fails the lane on: changed app code with no test file
# anywhere, zero mutants (tests do not cover the changed lines), any
# surviving mutant, or the lane budget being exceeded.
#
# Used by the test-mutation lane (code-quality.yml) — the workflow step is
# just `bash scripts/ci/mutation-check.sh`; all logic lives here.
#
# The lane is a matrix: MUTATION_SHARD / MUTATION_SHARDS pick this job's slice
# of the changed-module list. A runner has 4 cores and mutmut is CPU-bound, so
# in-job parallelism caps out at 4 and the only way to go faster is more
# runners. Without them a large PR does not fit the lane's timeout at all: a
# 52-module diff got through 11 modules in 30 minutes. Both vars unset means
# one shard with every module, which is what a local run wants.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

# Scratch space for the module list. Per-invocation rather than fixed paths
# under /tmp: two runs on one machine (a local check next to a sweep, two
# tests under xdist) would otherwise read each other's list and mutate the
# wrong modules.
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

# 1. Changed app modules + their test files, as JSON. The matrix script
#    fails loudly (exit 1) when a changed module has no test file.
bash scripts/ci/mutation-matrix.sh > "$WORKDIR/matrix.json"

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
#
#    Sharded: the lane runs as a matrix of MUTATION_SHARDS jobs, and this one
#    keeps every MUTATION_SHARDS-th module. Round-robin rather than contiguous
#    blocks because the matrix comes out grouped by directory, and modules in
#    one directory share test files and therefore cost — chunking would put
#    every expensive module on one shard. Unset means "one shard, all modules",
#    which is what a local run wants.
python3 - "$WORKDIR" << 'EOF'
import json
import os
import sys

workdir = sys.argv[1]

shards = int(os.environ.get("MUTATION_SHARDS", "1"))
shard = int(os.environ.get("MUTATION_SHARD", "1"))
if shards < 1 or not 1 <= shard <= shards:
    raise SystemExit(f"::error::mutation gate: MUTATION_SHARD={shard} is not in 1..{shards}")

modules = json.load(open(f"{workdir}/matrix.json"))
selected = [m for i, m in enumerate(modules) if i % shards == shard - 1]
with open(f"{workdir}/modules.txt", "w") as f:
    for m in selected:
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
print(f"shard {shard}/{shards}: {len(selected)} of {len(modules)} changed module(s) to mutate")
EOF

# 3. Nothing landed on this shard (or the PR changed no app modules at all).
if [ ! -s "$WORKDIR/modules.txt" ]; then
  echo "no modules on this shard — nothing to mutate"
  exit 0
fi

# 4. Run one mutation check per module with bounded parallelism. A plain
#    read loop (not xargs) so a module with an empty changed-lines JSON
#    (`[]`) can never shift the fields between invocations.
#
#    Every spawned job is reaped by exactly one `wait -n`, counted rather than
#    drained with a bare `wait`: bash's `wait` with no operands is DOCUMENTED to
#    return zero regardless of how its children exited, so the trailing batch's
#    failures used to be swallowed and the lane reported green on a survivor it
#    had already found. Counting also beats `wait "$oldest"` — a slow module
#    would hold the head of the line while its slot sat idle.
PARALLELISM=4
FAILED=0
SPAWNED=0
REAPED=0
while read -r module testfiles ranges; do
  bash scripts/test/mutation.sh "$module" "$testfiles" "${ranges:-[]}" &
  SPAWNED=$((SPAWNED + 1))
  if [ $((SPAWNED - REAPED)) -ge "$PARALLELISM" ]; then
    wait -n || FAILED=1
    REAPED=$((REAPED + 1))
  fi
done < "$WORKDIR/modules.txt"
while [ "$REAPED" -lt "$SPAWNED" ]; do
  wait -n || FAILED=1
  REAPED=$((REAPED + 1))
done
exit "$FAILED"
