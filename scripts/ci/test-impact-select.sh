#!/usr/bin/env bash
# Decide which tests this PR's slice has to run.
#
# Reads the map restored from the newest master run, diffs the PR against its
# merge-base, and writes apps/api/.test-impact/selected-<slice>.txt — either a
# list of pytest node ids or the single line ALL. run-python-slice.sh consumes
# it; every failure mode here falls back to ALL rather than skipping tests.
#
# Outputs (GITHUB_OUTPUT): mode=all|selected, summary=<one line>
set -euo pipefail

SLICE="${SLICE_NAME:?SLICE_NAME required}"
SLICE_PATHS="${SLICE_PATHS:?SLICE_PATHS required}"
BASE_REF="${BASE_REF:-master}"
MAP_DIR="${MAP_DIR:-.test-impact-map}"
OUT_DIR="apps/api/.test-impact"

mkdir -p "$OUT_DIR"
SELECTED="$OUT_DIR/selected-$SLICE.txt"

emit() {
  echo "mode=$1" >>"${GITHUB_OUTPUT:-/dev/null}"
  echo "summary=$2" >>"${GITHUB_OUTPUT:-/dev/null}"
  echo "test impact ($SLICE): $2"
  [ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo "test impact ($SLICE): $2" >>"$GITHUB_STEP_SUMMARY"
  return 0
}

MAP="$MAP_DIR/test-impact-map-$SLICE.json"
if [ ! -f "$MAP" ]; then
  echo "ALL" >"$SELECTED"
  emit all "ran ALL (no map cached for slice $SLICE yet)"
  exit 0
fi

# The merge-base, not the base tip: we only want what this PR changed.
git fetch --no-tags --depth=200 origin "$BASE_REF" >/dev/null 2>&1 || true
MERGE_BASE=$(git merge-base "origin/$BASE_REF" HEAD 2>/dev/null || true)
if [ -z "$MERGE_BASE" ]; then
  echo "ALL" >"$SELECTED"
  emit all "ran ALL (no merge-base with origin/$BASE_REF — shallow checkout?)"
  exit 0
fi
git diff --name-only "$MERGE_BASE" HEAD >"$OUT_DIR/changed-files.txt"

# tests/contracts is the API contract and always runs; the bridge slice never
# reaches this script at all (see hybrid-ci.yml).
RESTRICT=()
for p in $SLICE_PATHS; do RESTRICT+=(--restrict-to "$p"); done

python3 scripts/ci/test-impact.py select \
  --map "$MAP" \
  --changed "$OUT_DIR/changed-files.txt" \
  --out "$SELECTED" \
  --repo-root apps/api \
  --always tests/contracts \
  "${RESTRICT[@]}" >"$OUT_DIR/select.log"
cat "$OUT_DIR/select.log"

LINE=$(cat "$OUT_DIR/select.log")
if [ "$(head -n1 "$SELECTED")" = "ALL" ]; then
  emit all "$LINE"
else
  emit selected "$LINE"
fi
