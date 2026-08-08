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

# 2. Flatten to "module testfile" lines.
python3 - << 'EOF'
import json

modules = json.load(open("/tmp/mutation-matrix.json"))
with open("/tmp/mutation-modules.txt", "w") as f:
    for m in modules:
        f.write(f"{m['module']} {m['testfile']} {json.dumps(m['changed_lines'], separators=(',', ':'))}")
print(f"{len(modules)} module(s) to mutate")
EOF

# 3. No changed app modules — nothing to prove.
if [ ! -s /tmp/mutation-modules.txt ]; then
  echo "no changed app modules — nothing to mutate"
  exit 0
fi

# 4. Run one mutation check per module with bounded parallelism. xargs
#    exits 123 when any invocation fails, which fails this lane.
xargs -P 4 -n 3 bash scripts/test/mutation.sh < /tmp/mutation-modules.txt
