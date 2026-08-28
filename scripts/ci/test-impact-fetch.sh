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
mkdir -p "$MAP_DIR"

# One call: the repo-wide artifact list filtered by name carries each
# artifact's run id and head branch (walking runs and asking each for its
# artifacts cost 27 s per lane). Newest unexpired one on master or the head
# branch wins.
branches="master"
[ -n "${GITHUB_HEAD_REF:-}" ] && branches="master ${GITHUB_HEAD_REF}"
pick="$(gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts?name=${ARTIFACT}&per_page=50" \
  --jq '.artifacts[] | select(.expired == false) | "\(.created_at) \(.workflow_run.id) \(.workflow_run.head_branch)"' 2>/dev/null \
  | while read -r created id branch; do
      for b in $branches; do [ "$branch" = "$b" ] && echo "$created $id"; done
    done | sort | tail -n1 || true)"
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
