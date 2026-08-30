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
# Scratch lives under the job's own temp dir, never a fixed /tmp name: /tmp
# is sticky and shared by every user on a self-hosted box, so a file left
# behind by another runner user is unwritable (EACCES) for this one.
WORK=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/evlog-ratchet.XXXXXX")
# NB: keep the worktree dir name free of sensitivity terms ("checkout",
# "auth", ...) — it prefixes every base file path. The trap cleans the
# worktree up even on failure so a re-run never trips over a stale
# registration.
BASE_DIR="$WORK/obs-merge-base"
trap 'rm -rf "$WORK"; git worktree prune' EXIT
git worktree add --detach "$BASE_DIR" "$BASE_SHA"

# Same merge-base diff + ACMR filter as `changes.sh files`, plus -M and
# --name-status to see the old path of each rename.
: > "$WORK"/head-files.txt
: > "$WORK"/base-files.txt
: > "$WORK"/renames.txt
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
    echo "$head_path" >> "$WORK"/head-files.txt
  fi
  if [ -f "$BASE_DIR/$base_path" ]; then
    echo "$BASE_DIR/$base_path" >> "$WORK"/base-files.txt
    if [ "$base_path" != "$head_path" ]; then
      printf '%s\t%s\n' "$base_path" "$head_path" >> "$WORK"/renames.txt
    fi
  fi
done < <(git diff --name-status -M --diff-filter=ACMR "$BASE_SHA"...HEAD)

python3 tools/evlog_map --files-from "$WORK"/base-files.txt --json --no-write > "$WORK"/base-map.json
python3 tools/evlog_map --files-from "$WORK"/head-files.txt --no-write \
  --baseline "$WORK"/base-map.json --rename-map "$WORK"/renames.txt
