#!/usr/bin/env bash
# Emit the mutation-check matrix: every changed app module + its test file.
#
# Used by the test-mutation lane (code-quality.yml) to run mutation testing
# per changed module in parallel GitHub jobs. Reference detection is AST-based
# (scripts/ci/mutation-matrix.py) because grep misses this codebase's
# patch-target strings and from-package submodule imports.
#
# Fails loudly when changed app code has no test file anywhere — the "no
# bullshit tests" rule enforced mechanically.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

CHANGED_PY="$(scripts/ci/changed-files.sh py)"
if [ -z "$CHANGED_PY" ] || [ "$CHANGED_PY" = "__FULL__" ]; then
  echo '[]'
  exit 0
fi

# Changed app modules only; entry points and __init__ files are not
# mutation targets (nothing meaningful to mutate, no natural test).
printf '%s\n' "$CHANGED_PY" |
  grep '^apps/api/app/.*\.py$' |
  grep -v 'app/main\.py$' |
  grep -v 'app/worker\.py$' |
  grep -v '__init__\.py$' |
  python3 scripts/ci/mutation-matrix.py
