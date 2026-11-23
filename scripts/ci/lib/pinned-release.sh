#!/usr/bin/env bash
# pinned-release.sh — the one way a CI script downloads a pinned release asset.
#
# Sourced after lib/log.sh. Functions:
#   digest_matches <algo> <digest> <file>   sha256/sha512 check; sha*sum, else macOS shasum.
#   fetch_verified <name> <url> <algo> <digest> <dest>
#                                           Download <url> to <dest> and check it,
#                                           fetching again while it fails; the last
#                                           mismatch fails the lane.

# A corrupt 278 MB Fortress archive ejected four merge groups (9-11 Nov) while the asset matched its pin.
DOWNLOAD_ATTEMPTS=3

digest_matches() {
  local algo="$1" digest="$2" file="$3"
  if command -v "${algo}sum" > /dev/null; then
    echo "$digest  $file" | "${algo}sum" -c - > /dev/null 2>&1
  else
    echo "$digest  $file" | shasum -a "${algo#sha}" -c - > /dev/null 2>&1
  fi
}

fetch_verified() {
  local name="$1" url="$2" algo="$3" digest="$4" dest="$5" attempt
  for ((attempt = 1; attempt <= DOWNLOAD_ATTEMPTS; attempt++)); do
    if curl -fsSL -o "$dest" "$url" && digest_matches "$algo" "$digest" "$dest"; then
      return 0
    fi
    ci_warn "$name: download ${attempt}/${DOWNLOAD_ATTEMPTS} failed or does not match its pinned ${algo}"
  done
  ci_die "$name does not match its pinned ${algo} after ${DOWNLOAD_ATTEMPTS} downloads"
}
