#!/usr/bin/env bash
# Emit the test-mutation lane's GitHub Actions matrix: one shard per changed
# module.
#
# Why sharded rather than one job. mutmut re-runs a module's ENTIRE test
# selection once per mutant, so a module with a heavy selection costs tens of
# minutes on its own. Run inside a single job those costs add up, and the few
# slowest modules hold every worker while the rest never start: a 54-module PR
# was cancelled at the lane cap having completed 37 and never begun 13 — the
# gate reported failure while proving nothing. One runner per module makes the
# lane cost the SLOWEST module instead of their sum, and a module that hangs
# takes down its own shard instead of the lane.
#
# Output, appended to $GITHUB_OUTPUT:
#   matrix=<json array of {module, testfiles, ranges}>
#   count=<n>
#
# The two list arguments are emitted as compact JSON STRINGS because a GitHub
# matrix value cannot hold nested JSON — mutation.sh already parses both from
# exactly this form.
#
# The heavy lifting stays in mutation-matrix.sh, which is also what fails the
# lane loudly when changed app code has no test file anywhere. That failure
# lands on THIS job, which is why the quality gate must require it: a failed
# plan skips the matrix, and a skipped lane counts as a pass.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

bash scripts/ci/mutation-matrix.sh > /tmp/mutation-matrix.json

python3 - << 'EOF'
import json
import os

modules = json.load(open("/tmp/mutation-matrix.json"))
include = [
    {
        "module": entry["module"],
        "testfiles": json.dumps(entry["testfiles"], separators=(",", ":")),
        "ranges": json.dumps(entry["changed_lines"], separators=(",", ":")),
    }
    for entry in modules
]

github_output = os.environ.get("GITHUB_OUTPUT")
if github_output:
    with open(github_output, "a") as handle:
        handle.write(f"matrix={json.dumps(include, separators=(',', ':'))}\n")
        handle.write(f"count={len(include)}\n")

print(f"{len(include)} module(s) to mutate, one shard each")
for entry in include:
    print(f"  {entry['module']}")
EOF
