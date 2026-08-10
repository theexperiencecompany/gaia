#!/usr/bin/env bash
#
# evlog-ratchet.sh — per-file observability ratchet for the changed Python files.
#
# Run from a PR checkout (fetch-depth: 0). Scores each changed file with the
# HEAD scanner at the merge-base and at HEAD, then fails if any file's score
# dropped. Legacy debt never blocks; regressions always do. A file with no
# baseline must reach the "good"-grade floor (70). Rename-aware: a renamed file
# ratchets against its OLD path rather than being treated (and floor-gated) as
# brand-new.
set -euo pipefail

BASE_SHA=$(git merge-base "origin/$GITHUB_BASE_REF" HEAD)
# NB: keep the worktree dir name free of sensitivity terms ("checkout",
# "auth", ...) — it prefixes every base file path. A per-PID suffix keeps
# parallel runs from colliding, and the trap cleans the worktree up even on
# failure so a re-run never trips over a stale registration.
BASE_DIR="/tmp/obs-merge-base-$$"
trap 'rm -rf "$BASE_DIR"; git worktree prune' EXIT
git worktree add --detach "$BASE_DIR" "$BASE_SHA"

# Same merge-base diff + ACMR filter as changed-files.sh, plus -M and
# --name-status to see the old path of each rename.
: > /tmp/head-files.txt
: > /tmp/base-files.txt
: > /tmp/renames.txt
while IFS=$'\t' read -r status p1 p2; do
  case "$status" in
    R*)
      head_path="$p2"
      base_path="$p1"
      ;;
    *)
      head_path="$p1"
      base_path="$p1"
      ;;
  esac
  case "$head_path" in
    *.py) ;;
    *) continue ;;
  esac
  if [ -f "$head_path" ]; then
    echo "$head_path" >> /tmp/head-files.txt
  fi
  if [ -f "$BASE_DIR/$base_path" ]; then
    echo "$BASE_DIR/$base_path" >> /tmp/base-files.txt
    if [ "$base_path" != "$head_path" ]; then
      printf '%s\t%s\n' "$base_path" "$head_path" >> /tmp/renames.txt
    fi
  fi
done < <(git diff --name-status -M --diff-filter=ACMR "$BASE_SHA"...HEAD)

python3 tools/evlog_map --files-from /tmp/base-files.txt --json --no-write > /tmp/base-map.json
python3 tools/evlog_map --files-from /tmp/head-files.txt --no-write \
  --baseline /tmp/base-map.json --rename-map /tmp/renames.txt
