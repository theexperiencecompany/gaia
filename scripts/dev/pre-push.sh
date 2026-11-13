#!/usr/bin/env bash
# The CI lanes this push touches (mise ci:local), as git's own pre-push hook.
# Not a prek hook: prek stashes every uncommitted change around the hooks it runs,
# and an edit made during this multi-minute check was lost when the stash came back.
#   scripts/dev/pre-push.sh install   write the hook (mise run pre-commit:install does)
#   scripts/dev/pre-push.sh           run the check (what the hook calls)
set -euo pipefail

if [ "${1:-}" = "install" ]; then
  hook="$(git rev-parse --git-path hooks)/pre-push"
  mkdir -p "$(dirname "$hook")"
  # The hooks directory is shared by every worktree, so the hook runs the pushing
  # worktree's own copy and skips on a branch that predates this script.
  cat > "$hook" <<'HOOK'
#!/bin/sh
script="$(git rev-parse --show-toplevel)/scripts/dev/pre-push.sh"
if [ ! -x "$script" ]; then
  echo "pre-push: this branch predates scripts/dev/pre-push.sh; merge master to get the CI check." >&2
  exit 0
fi
exec "$script" "$@"
HOOK
  chmod +x "$hook"
  echo "pre-push hook installed at $hook"
  exit 0
fi

cat > /dev/null
cd "$(git rev-parse --show-toplevel)"
if ! git diff --quiet HEAD --; then
  echo "pre-push: these uncommitted changes are checked too, so a pass covers more than the pushed commit:" >&2
  git diff --name-only HEAD -- | sed 's/^/  /' >&2
fi
exec mise ci:local
