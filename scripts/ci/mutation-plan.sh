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
#   matrix=<json array of {label, group}>
#   count=<n>
#
# `group` is a compact JSON STRING holding that shard's modules, because a
# GitHub matrix value cannot hold nested JSON.
#
# The shard count is capped at the matrix's own max-parallel. Going wider buys
# NOTHING: GitHub still runs only max-parallel jobs at a time, so the wall
# clock is identical either way — what the extra jobs actually cost is one
# check row each in the PR (a 430-module diff produced 250 of them, which no
# reviewer can read past) and one full checkout + `uv sync` each, paid per job
# instead of per lane. Same speed, unreadable result, more runner time.
#
# The heavy lifting stays in mutation-matrix.sh, which is also what fails the
# lane loudly when changed app code has no test file anywhere. That failure
# lands on THIS job, which is why the quality gate must require it: a failed
# plan skips the matrix, and a skipped lane counts as a pass.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

# Through the environment rather than a fixed /tmp path: two plans running on
# one machine would otherwise clobber each other's file, and the symptom would
# be a wrong matrix rather than an error. set -e still aborts here when the
# matrix script exits non-zero.
MATRIX_JSON="$(bash scripts/ci/mutation-matrix.sh)"
export MATRIX_JSON

python3 - << 'EOF'
import json
import os

# Match the matrix's max-parallel in code-quality.yml: more shards than can run
# at once add check rows and setup cost without shortening the lane. (It also
# stays clear of GitHub's hard 256-job matrix limit, which a one-shard-per-
# module plan blew through on the mypy-strict diff — no matrix, a skipped lane,
# and a skipped lane counts as a pass.)
MAX_SHARDS = 12

modules = json.loads(os.environ["MATRIX_JSON"])
shards: list[list[dict[str, str]]] = [[] for _ in range(min(len(modules), MAX_SHARDS))]
for index, entry in enumerate(modules):
    shards[index % len(shards)].append(
        {
            "module": entry["module"],
            "testfiles": json.dumps(entry["testfiles"], separators=(",", ":")),
            "ranges": json.dumps(entry["changed_lines"], separators=(",", ":")),
        }
    )

include = [
    {
        # The check's displayed name. A lone module names itself — the common
        # case, and the most useful thing a reviewer can read at a glance. A
        # packed shard says how many it carries, so nothing looks dropped.
        "label": (
            shard[0]["module"]
            if len(shard) == 1
            else f"shard {number}/{len(shards)} ({len(shard)} modules)"
        ),
        "group": json.dumps(shard, separators=(",", ":")),
    }
    for number, shard in enumerate(shards, start=1)
]

github_output = os.environ.get("GITHUB_OUTPUT")
if github_output:
    with open(github_output, "a") as handle:
        handle.write(f"matrix={json.dumps(include, separators=(',', ':'))}\n")
        handle.write(f"count={len(include)}\n")

if len(shards) < len(modules):
    print(f"{len(modules)} module(s) packed into {len(shards)} shards (matrix job limit)")
else:
    print(f"{len(modules)} module(s) to mutate, one shard each")
for entry in include:
    print(f"  {entry['label']}")
EOF
