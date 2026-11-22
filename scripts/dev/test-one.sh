#!/usr/bin/env bash
# Run test files with apps/api's pytest setup, minus xdist (`mise test:one`).
#
# pytest runs from apps/api, so a path is first resolved from the directory mise
# was run in (MISE_ORIGINAL_CWD): `scripts/ci/tests/x.py` from the repo root and
# `tests/unit/x.py` from apps/api both work. A path that does not exist there
# (flags, `-k` expressions, the old apps/api-relative form from the root) is
# passed through unchanged for pytest to resolve or reject.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
caller_dir="${MISE_ORIGINAL_CWD:-$PWD}"

args=()
for arg in "$@"; do
  path="${arg%%::*}"
  if [[ "$arg" != -* && "$arg" != /* && -e "$caller_dir/$path" ]]; then
    arg="$caller_dir/$arg"
  fi
  args+=("$arg")
done

cd "$repo_root/apps/api"
exec uv run --group backend --group dev pytest -p no:xdist -q ${args[@]+"${args[@]}"}
