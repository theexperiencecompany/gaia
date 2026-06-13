#!/usr/bin/env bash
#
# changed-files.sh — emit the list of changed files for a CI lane to scope to.
#
# Usage:
#   scripts/ci/changed-files.sh <ext> [<ext> ...]
#   e.g. scripts/ci/changed-files.sh ts tsx js jsx json css
#        scripts/ci/changed-files.sh py
#
# Modes (signalled to callers via a sentinel on the first line of stdout):
#
#   PUSH / FULL-SCAN MODE  ($GITHUB_BASE_REF is empty — i.e. not a PR)
#     Prints the single line "__FULL__" and exits 0. Callers MUST treat this
#     as "scan the whole repo with the lane's existing full command".
#
#   PR MODE  ($GITHUB_BASE_REF is set — pull_request event)
#     Prints one path per line: files changed vs the PR base (merge-base diff),
#     filtered to the requested extensions and to files that still exist on
#     HEAD (added / copied / modified / renamed; deletions excluded). When the
#     PR changes zero matching files this prints NOTHING and exits 0 — callers
#     MUST treat empty (but not "__FULL__") output as "no work, skip & pass".
#
# Caller contract (the three states):
#   FILES=$(scripts/ci/changed-files.sh <exts>)
#   if [ "$FILES" = "__FULL__" ]; then  <full command>          # push
#   elif [ -z "$FILES" ]; then          echo "skip"; exit 0     # PR, nothing relevant
#   else                                <tool> $FILES           # PR, diff-scoped
#   fi
#
# Diff accuracy note: the merge-base ("...") diff requires the base ref to be
# present locally, so PR lanes that consume this script must checkout with
# `fetch-depth: 0`. The script fetches the base ref defensively as well.
set -euo pipefail

FULL_SENTINEL="__FULL__"

# Push / non-PR event: no base ref to diff against → signal full scan.
if [[ -z "${GITHUB_BASE_REF:-}" ]]; then
  printf '%s\n' "$FULL_SENTINEL"
  exit 0
fi

if [[ "$#" -eq 0 ]]; then
  echo "changed-files.sh: at least one extension argument is required" >&2
  exit 2
fi

# Build an alternation of the requested extensions: ts|tsx|js → \.(ts|tsx|js)$
ext_alt=""
for ext in "$@"; do
  if [[ -z "$ext_alt" ]]; then
    ext_alt="$ext"
  else
    ext_alt="$ext_alt|$ext"
  fi
done
ext_regex="\.(${ext_alt})$"

# Ensure the PR base ref is available for the merge-base diff. Best-effort:
# on a fetch-depth:0 checkout this is a cheap no-op; on a shallow one it
# unshallows just enough to resolve the base.
#
# Hard timeout + low-speed guard so a stalled HTTPS connection fails fast
# instead of hanging until the job's timeout-minutes cap (which surfaces as a
# `cancelled` lane and fails the quality gate). If the fetch dies, the diff
# below falls back to whatever base ref is already local.
timeout 60 git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 \
  fetch --no-tags --depth=1 origin "$GITHUB_BASE_REF" 2>/dev/null || true

# `...HEAD` diffs against the merge-base of the base ref and HEAD — the same set
# of files GitHub shows as "Files changed" in the PR. --diff-filter=ACMR drops
# deletions so we never hand a tool a path that no longer exists.
# `|| true` on grep: a PR that changes zero matching files is a valid "skip"
# case, not an error. Without it, grep's no-match exit 1 + `set -o pipefail`
# would make this script exit 1 and fail the lane's `FILES=$(...)` step.
git diff --name-only --diff-filter=ACMR "origin/${GITHUB_BASE_REF}...HEAD" \
  | { grep -E "$ext_regex" || true; } \
  | while IFS= read -r f; do
      [[ -f "$f" ]] && printf '%s\n' "$f"
    done
