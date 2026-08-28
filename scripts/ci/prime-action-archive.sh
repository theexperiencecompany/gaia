#!/usr/bin/env bash
# Pre-populate the runner's action archive cache.
#
# The runner only READS $ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE (Runner.Worker
# ActionManager.cs: "<cache>/<owner>_<repo>/<sha>.tar.gz"); it never writes to
# it. With the directory empty every job spent ~20 s re-downloading the same
# pinned action tarballs from codeload (measured 2026-08-28: five actions,
# 01:29:50→01:30:09 on one job). This fetches every SHA-pinned `uses:` in the
# repo's workflows and composites once; re-run after bumping a pin (setup.sh
# and the nightly prune timer both call it).
#
# Usage: scripts/ci/prime-action-archive.sh [cache-dir]   (needs gh auth)
#   GAIA_REPO=<checkout>  workflows to scan when the script runs from a copy
#                         outside the repo (the box keeps one in ci-cache/).
set -euo pipefail

CACHE="${1:-${ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE:-$HOME/ci-cache/actions-archive}}"
REPO_ROOT="${GAIA_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
[ -d "$REPO_ROOT/.github" ] || { echo "no workflows under $REPO_ROOT (set GAIA_REPO)" >&2; exit 1; }
mkdir -p "$CACHE"

fetched=0 present=0
while IFS= read -r ref; do
  slug="${ref%@*}"; sha="${ref#*@}"
  # Nested paths (owner/repo/sub@sha) resolve to the repo's tarball.
  repo="$(echo "$slug" | cut -d/ -f1-2)"
  dir="$CACHE/${repo//\//_}"
  file="$dir/$sha.tar.gz"
  if [ -s "$file" ]; then present=$((present + 1)); continue; fi
  mkdir -p "$dir"
  if gh api "repos/$repo/tarball/$sha" > "$file.part" 2>/dev/null && [ -s "$file.part" ]; then
    mv -f "$file.part" "$file"; fetched=$((fetched + 1)); echo "fetched $repo@$sha"
  else
    rm -f "$file.part"; echo "::warning::could not fetch $repo@$sha"
  fi
done < <(grep -rhoE '^\s*-?\s*uses:\s*[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}' \
           "$REPO_ROOT/.github" | sed -E 's/^.*uses:\s*//' | sort -u)

echo "action archive: $present present, $fetched fetched → $CACHE"
