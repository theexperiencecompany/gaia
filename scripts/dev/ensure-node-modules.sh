#!/usr/bin/env bash
# Install the workspace's node_modules once, in a checkout that has none.
#
# A fresh `git worktree add` checkout has no node_modules, so every commit hook
# that runs node or pnpm (biome, checks.mjs, openui) died with
# ERR_MODULE_NOT_FOUND. This runs the install CI's setup-node-pnpm composite
# runs, and trusts the same two files pnpm writes only once an install finished.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
if [ -f "$root/node_modules/.modules.yaml" ] && [ -f "$root/node_modules/.pnpm/lock.yaml" ]; then
  exit 0
fi
echo "ensure-node-modules: $root has no finished install; running pnpm install --frozen-lockfile once" >&2
exec pnpm --dir "$root" install --frozen-lockfile --prefer-offline
