#!/usr/bin/env bash
# dep-marker.sh — the one place that decides when a persisted install is stale.
#
# The self-hosted workspace keeps node_modules and .venv between jobs and skips
# the install when a marker file left by the previous install still matches.
# The marker key must cover EVERY input that changes what the install produces,
# not just the lockfile: a `node-linker` flip in .npmrc / pnpm-workspace.yaml or
# a `packageManager` bump rewrites node_modules with an unchanged lockfile, and
# a pyproject edit changes the workspace uv syncs. Used by the composites
# (setup-node-pnpm, setup-python-test-env) and by infra/self-hosted-runner/
# setup.sh's warm-up, so all three agree on what "already installed" means.
#
# Usage: dep-marker.sh node|python   → prints the marker path
set -euo pipefail

kind="${1:?usage: dep-marker.sh node|python}"

key_of() {
  # Missing optional inputs hash as empty, so adding/removing one changes the key.
  for f in "$@"; do
    if [[ -f "$f" ]]; then cat "$f"; else printf '<absent:%s>' "$f"; fi
  done | sha256sum | cut -c1-16
}

case "$kind" in
  node)
    echo "node_modules/.gaia-installed-$(key_of pnpm-lock.yaml pnpm-workspace.yaml .npmrc package.json)"
    ;;
  python)
    echo ".venv/.gaia-synced-$(key_of uv.lock pyproject.toml apps/api/pyproject.toml libs/pyproject.toml .python-version)"
    ;;
  *)
    echo "dep-marker.sh: unknown kind '$kind' (node|python)" >&2
    exit 2
    ;;
esac
