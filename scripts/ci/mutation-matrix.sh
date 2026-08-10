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
#
# Each grep is guarded: it exits 1 when nothing matches, which under `pipefail`
# failed the whole lane for any PR that changed Python outside apps/api/app/ and
# nothing inside it (tools/, scripts/, libs/ — this file's own tests included).
# An empty selection is a valid answer, and the orchestrator already handles it
# ("no changed app modules — nothing to mutate"); only a real error should fail.
printf '%s\n' "$CHANGED_PY" |
  { grep '^apps/api/app/.*\.py$' || true; } |
  { grep -v 'app/main\.py$' || true; } |
  { grep -v 'app/worker\.py$' || true; } |
  { grep -v '__init__\.py$' || true; } |
  python3 scripts/ci/mutation-matrix.py
