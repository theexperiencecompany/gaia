#!/usr/bin/env bash
# Fetch the newest test-impact map for a slice into $MAP_DIR.
#
# Maps are uploaded as workflow artifacts by master / dispatch runs (main.yml
# "Upload test impact map"), not actions/cache: a pull_request run may only
# restore caches written on its own merge ref or on the default branch, so a
# map recorded by a dispatch run on the PR's head branch was invisible to the
# PR — measured: four maps in the cache, every lane "ran ALL". Artifacts are
# fetched by run, which any job with actions:read may do.
#
# Newest wins between the PR's head branch (a dispatch run on the branch
# records the branch's own tests) and master. Every failure mode leaves no map,
# and test-impact-select.sh then runs the whole slice.
#
# Env: SLICE_NAME, GITHUB_REPOSITORY, GITHUB_TOKEN (actions:read),
#      GITHUB_HEAD_REF (PR head branch, optional), MAP_DIR (default .test-impact-map)
set -euo pipefail

SLICE="${SLICE_NAME:?SLICE_NAME required}"
MAP_DIR="${MAP_DIR:-.test-impact-map}"
ARTIFACT="test-impact-map-${SLICE}"
WORKFLOW="main.yml"
mkdir -p "$MAP_DIR"

# Newest completed run on a branch that carries the artifact: "<created_at> <run_id>".
newest_run_with_map() {
  local branch="$1"
  gh api "repos/${GITHUB_REPOSITORY}/actions/workflows/${WORKFLOW}/runs?branch=${branch}&status=completed&per_page=15" \
    --jq '.workflow_runs[] | "\(.created_at) \(.id)"' 2>/dev/null \
  | while read -r created id; do
      if gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${id}/artifacts" \
           --jq ".artifacts[] | select(.name == \"${ARTIFACT}\" and .expired == false) | .id" 2>/dev/null | grep -q .; then
        echo "$created $id"
        return 0
      fi
    done
  return 0
}

candidates="$(newest_run_with_map master)"
if [ -n "${GITHUB_HEAD_REF:-}" ]; then
  candidates="$(printf '%s\n%s\n' "$candidates" "$(newest_run_with_map "$GITHUB_HEAD_REF")")"
fi
pick="$(echo "$candidates" | grep -E '^[0-9]{4}-' | sort | tail -n1 || true)"
if [ -z "$pick" ]; then
  echo "test impact ($SLICE): no map artifact on master or ${GITHUB_HEAD_REF:-<no head ref>} yet"
  exit 0
fi
run_id="${pick##* }"
if gh run download "$run_id" --repo "$GITHUB_REPOSITORY" --name "$ARTIFACT" --dir "$MAP_DIR" > /dev/null 2>&1 \
   && [ -s "$MAP_DIR/${ARTIFACT}.json" ]; then
  echo "test impact ($SLICE): map from run ${run_id} (${pick%% *})"
else
  rm -f "$MAP_DIR/${ARTIFACT}.json"
  echo "::warning::test impact ($SLICE): could not download ${ARTIFACT} from run ${run_id}; running the whole slice"
fi
