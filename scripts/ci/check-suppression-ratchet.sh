#!/usr/bin/env bash
#
# check-suppression-ratchet.sh — fail if the diff against a base ref/SHA
# introduces NEW inline lint-suppression comments:
#   - Python:               # noqa            , # type: ignore
#   - TypeScript/JavaScript: // biome-ignore
#
# This is a ratchet, not a ban. Suppressions already present on the base are
# grandfathered, so the codebase's current baseline never has to be burned
# down before this can be enforced.
#
# It compares, per file, HOW MANY suppressions the base has against how many
# HEAD has. A file that grows fails and is named; a file that stays level or
# shrinks passes. Counting rather than diffing added lines is what makes
# "already there" actually mean already there: reformatting a suppressed line,
# moving it as surrounding code shifts, or narrowing `# type: ignore` to
# `# type: ignore[prop-decorator]` all rewrite the line, so a line-based check
# reports them as new holes — and punishes the narrowing, which is a
# tightening. Only a real increase is a real new hole.
#
# The trade-off, taken deliberately: deleting one suppression and adding a
# different one in the same file nets to zero and passes. That is the price of
# not crying wolf on every touched line, and the added one is still visible in
# review as a changed line.
#
# Two independent passes, each scoped to its own file types by pathspec, so
# prose that happens to mention these words in docs/config/yaml (e.g. this
# repo's own pyproject.toml ruff-rationale comments, or this very script) can
# never trip the check — only files where the suppression syntax is
# meaningful are scanned.
#
# Usage:
#   scripts/ci/check-suppression-ratchet.sh <base-ref-or-sha>
#
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "usage: check-suppression-ratchet.sh <base-ref-or-sha>" >&2
  exit 2
fi

BASE="$1"

PY_PATTERN='#[[:space:]]*(noqa|type:[[:space:]]*ignore)\b'
TS_PATTERN='//[[:space:]]*biome-ignore\b'

# Suppression count for one file at one revision. A path that does not exist
# there (added file, deleted file) counts as zero.
count_at() {
  local rev="$1" path="$2" pattern="$3"
  if git cat-file -e "${rev}:${path}" 2>/dev/null; then
    git show "${rev}:${path}" | grep -cE "$pattern" || true
  else
    echo 0
  fi
}

# Names every file the diff touched under the given pathspecs whose
# suppression count went up, as "path base_count head_count".
grown_files() {
  local pattern="$1"
  shift
  local merge_base
  merge_base="$(git merge-base "$BASE" HEAD)"

  git diff --name-only --find-renames --diff-filter=d "${BASE}...HEAD" -- "$@" \
    | while IFS= read -r path; do
        [[ -n "$path" ]] || continue
        local before after
        before="$(count_at "$merge_base" "$path" "$pattern")"
        after="$(count_at HEAD "$path" "$pattern")"
        if (( after > before )); then
          echo "${path} ${before} ${after}"
        fi
      done
}

PY_GROWN=$(grown_files "$PY_PATTERN" '*.py')
TS_GROWN=$(grown_files "$TS_PATTERN" '*.ts' '*.tsx' '*.js' '*.jsx' '*.mjs' '*.cjs')

GROWN="$(printf '%s\n%s\n' "$PY_GROWN" "$TS_GROWN" | sed '/^$/d')"

if [[ -n "$GROWN" ]]; then
  echo "::error::New inline lint-suppression comment(s) introduced vs ${BASE}:" >&2
  while read -r path before after; do
    echo "  ${path}: ${before} -> ${after} (+$((after - before)))" >&2
  done <<< "$GROWN"
  echo "" >&2
  echo "Fix the underlying issue instead of suppressing it — existing suppressions are" >&2
  echo "grandfathered, but new ones must not slip in silently. If the suppression is" >&2
  echo "genuinely unavoidable, that's a decision to surface for review in the PR" >&2
  echo "description, not to add quietly." >&2
  exit 1
fi

echo "No new inline suppression comments vs ${BASE}."
