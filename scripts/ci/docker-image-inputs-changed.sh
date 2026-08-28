#!/usr/bin/env bash
# docker-image-inputs-changed.sh — does this PR touch anything the api image
# build depends on? Writes build=true|false to $GITHUB_OUTPUT.
#
# Only PR runs call this (master always builds). The diff is two-dot against
# the base branch tip: HEAD on a pull_request run is the merge commit, so
# `origin/<base>..HEAD` is exactly the PR's change set, and it works in the
# GitHub-hosted depth-1 checkout where a merge-base does not exist. An earlier
# version fell back to HEAD~1 and `|| true`, which on a shallow clone diffed
# nothing and skipped the build — vacuously green. Every command here is
# fail-loud: an unreadable diff must fail the lane, not skip it.
#
# Env: BASE_BRANCH (github.base_ref), GITHUB_OUTPUT.
set -euo pipefail

BASE_BRANCH="${BASE_BRANCH:?BASE_BRANCH is required (github.base_ref)}"
IMAGE_INPUTS=(
  apps/api/Dockerfile
  .dockerignore
  uv.lock
  pyproject.toml
  apps/api/pyproject.toml
  libs/pyproject.toml
  scripts/ci/check-playwright-pin.sh
)

# No --depth: it re-shallows the box's persistent workspace, and the next
# checkout then re-unshallows from GitHub (100 s).
git fetch -q --no-tags origin "$BASE_BRANCH"
CHANGED="$(git diff --name-only "origin/$BASE_BRANCH" HEAD -- "${IMAGE_INPUTS[@]}")"

if [[ -n "$CHANGED" ]]; then
  echo "build=true" >> "$GITHUB_OUTPUT"
  echo "image inputs changed:"
  echo "$CHANGED"
else
  echo "build=false" >> "$GITHUB_OUTPUT"
  echo "image inputs unchanged against origin/$BASE_BRANCH — skipping the build"
fi
