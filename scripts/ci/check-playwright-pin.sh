#!/usr/bin/env bash
# check-playwright-pin.sh — the Dockerfile's PLAYWRIGHT_VERSION must equal the
# playwright version in uv.lock. The browsers stage in apps/api/Dockerfile
# pre-downloads Chromium for that version so the builder's crawl4ai-setup
# skips the download; a drift means a different browser revision, and the
# ~450s download comes back silently on every build.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOCK="$(awk '/^name = "playwright"$/{f=1} f && /^version = /{gsub(/"/,"",$3); print $3; exit}' "$REPO_ROOT/uv.lock")"
DOCKER="$(sed -nE 's/^ARG PLAYWRIGHT_VERSION=(.*)$/\1/p' "$REPO_ROOT/apps/api/Dockerfile" | head -1)"
if [ -z "$LOCK" ] || [ -z "$DOCKER" ]; then
  echo "::error::could not read playwright version (uv.lock='$LOCK', Dockerfile='$DOCKER')"; exit 1
fi
if [ "$LOCK" != "$DOCKER" ]; then
  echo "::error::playwright pin drift: uv.lock has $LOCK, apps/api/Dockerfile ARG PLAYWRIGHT_VERSION=$DOCKER"
  echo "Update the ARG so the browsers stage caches the revision crawl4ai-setup expects."
  exit 1
fi
echo "playwright pin OK ($LOCK)"
