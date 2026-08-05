#!/usr/bin/env bash
#
# check-suppression-ratchet.sh — fail if the diff against a base ref/SHA
# introduces NEW inline lint-suppression comments:
#   - Python:               # noqa            , # type: ignore
#   - TypeScript/JavaScript: // biome-ignore
#
# This is a ratchet, not a ban. Suppressions already present on the base are
# grandfathered — moving, or even leaving, an existing one is fine. Only
# lines ADDED by this diff are checked, so the codebase's current baseline
# never has to be burned down before this can be enforced.
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

# Emits "path:line:content" for every line ADDED (a `+` line, not a `+++`
# file header) in the diff, restricted to the given pathspecs, then greps
# those for the given suppression pattern.
check_added_lines() {
  local pattern="$1"
  shift
  git diff --unified=0 --find-renames "${BASE}...HEAD" -- "$@" \
    | awk '
        /^\+\+\+ / {
          f = $0
          sub(/^\+\+\+ /, "", f)
          if (f == "/dev/null") { file = "" } else { sub(/^[ab]\//, "", f); file = f }
          next
        }
        /^@@/ {
          match($0, /\+[0-9]+/)
          line = substr($0, RSTART + 1, RLENGTH - 1) + 0
          next
        }
        /^\+/ {
          if (file != "") print file ":" line ":" substr($0, 2)
          line++
          next
        }
        /^-/ { next }
      ' \
    | grep -E "$pattern" || true
}

PY_HITS=$(check_added_lines '#[[:space:]]*(noqa|type:[[:space:]]*ignore)\b' '*.py')
TS_HITS=$(check_added_lines '//[[:space:]]*biome-ignore\b' '*.ts' '*.tsx' '*.js' '*.jsx' '*.mjs' '*.cjs')

HITS="$(printf '%s\n%s\n' "$PY_HITS" "$TS_HITS" | sed '/^$/d')"

if [[ -n "$HITS" ]]; then
  echo "::error::New inline lint-suppression comment(s) introduced vs ${BASE}:" >&2
  echo "$HITS" >&2
  echo "" >&2
  echo "Fix the underlying issue instead of suppressing it — existing suppressions are" >&2
  echo "grandfathered, but new ones must not slip in silently. If the suppression is" >&2
  echo "genuinely unavoidable, that's a decision to surface for review in the PR" >&2
  echo "description, not to add quietly." >&2
  exit 1
fi

echo "No new inline suppression comments vs ${BASE}."
