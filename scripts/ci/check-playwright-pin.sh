#!/usr/bin/env bash
# check-playwright-pin.sh — the Dockerfile's PLAYWRIGHT_VERSION and
# PATCHRIGHT_VERSION must equal the versions in uv.lock.
#
# The `browsers` stage in apps/api/Dockerfile is the ONLY place browsers are
# downloaded: it pip-installs those two exact versions and runs their
# `install chromium`. crawl4ai drives both libraries at runtime (playwright
# for normal mode, patchright for undetected mode) and each validates its own
# bundled build number — playwright 1.60.0 wants chromium build v1223,
# patchright 1.57.2 wants v1200. A drift here means /opt/browsers holds a
# revision the runtime library refuses, and Chromium fails to launch in
# production: webpage fetch and deep research silently fall back to httpx.
# Nothing downloads at runtime to cover for it, so this check is load-bearing.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DOCKERFILE="$REPO_ROOT/apps/api/Dockerfile"

fail=0
check() {
  local pkg="$1" arg="$2" lock docker
  lock="$(awk -v n="name = \"$pkg\"" '$0==n{f=1} f && /^version = /{gsub(/"/,"",$3); print $3; exit}' "$REPO_ROOT/uv.lock")"
  docker="$(sed -nE "s/^ARG $arg=(.*)\$/\1/p" "$DOCKERFILE" | head -1)"
  if [ -z "$lock" ] || [ -z "$docker" ]; then
    echo "::error::could not read $pkg version (uv.lock='$lock', Dockerfile ARG $arg='$docker')"; fail=1; return
  fi
  if [ "$lock" != "$docker" ]; then
    echo "::error::$pkg pin drift: uv.lock has $lock, apps/api/Dockerfile ARG $arg=$docker"
    echo "Update the ARG so the browsers stage downloads the revision the runtime library expects."
    fail=1; return
  fi
  echo "$pkg pin OK ($lock)"
}

check playwright PLAYWRIGHT_VERSION
check patchright PATCHRIGHT_VERSION
exit "$fail"
