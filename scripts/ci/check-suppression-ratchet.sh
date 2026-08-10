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
# For the suppression that genuinely cannot go, `# ratchet-allow -- <reason>` on
# the same line exempts that one line (see ALLOW_PATTERN below). The reason is
# mandatory. Prefer it to a per-file-ignores entry: this is line-scoped, where
# per-file-ignores disables the rule for every other line in the file too.
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

# The escape hatch, for the suppression that genuinely cannot be removed:
#
#   import app.config  # noqa: E402  # ratchet-allow -- sys.path bootstrap must precede app imports
#
# An allowed line is not counted, so the ratchet passes with the suppression
# still in place — line-scoped, unlike a per-file-ignores entry, which turns the
# rule off for every other line in the file too.
#
# The reason is mandatory, and this is the whole point of the marker: a bare
# `ratchet-allow` exempts nothing and keeps failing (it is reported as a warning
# below), so the price of the hatch is writing down why. Same contract as the
# evlog-map-disable directives in tools/evlog_map/directives.py.
#
# This is self-service by design — the author writes the reason and the lane
# goes green. It buys accountability, not permission: every allowance is one
# greppable line that says who decided what, and the count is printed on every
# run so they stay visible for later removal instead of going quiet once green.
ALLOW_PATTERN='ratchet-allow[[:space:]]*--[[:space:]]*[^[:space:]]'
ALLOW_BARE='ratchet-allow'

# Suppression count for one file at one revision, excluding allowed lines. A
# path that does not exist there (added file, deleted file) counts as zero.
count_at() {
  local rev="$1" path="$2" pattern="$3"
  if git cat-file -e "${rev}:${path}" 2>/dev/null; then
    git show "${rev}:${path}" \
      | { grep -E "$pattern" || true; } \
      | { grep -vcE "$ALLOW_PATTERN" || true; }
  else
    echo 0
  fi
}

# Suppression lines carrying a `ratchet-allow` with no `-- reason` after it.
# These exempt nothing; they are surfaced so the author is not left guessing why
# the marker did not work.
reasonless_at_head() {
  local pattern="$1"
  shift
  git diff --name-only --find-renames --diff-filter=d "${BASE}...HEAD" -- "$@" \
    | while IFS= read -r path; do
        [[ -n "$path" ]] || continue
        git cat-file -e "HEAD:${path}" 2>/dev/null || continue
        git show "HEAD:${path}" \
          | { grep -nE "$pattern" || true; } \
          | { grep -E "$ALLOW_BARE" || true; } \
          | { grep -vE "$ALLOW_PATTERN" || true; } \
          | while IFS= read -r hit; do
              echo "  ${path}:${hit%%:*}"
            done
      done
}

# Allowed lines at HEAD, for the always-on visibility report.
allowed_at_head() {
  local pattern="$1"
  shift
  git diff --name-only --find-renames --diff-filter=d "${BASE}...HEAD" -- "$@" \
    | while IFS= read -r path; do
        [[ -n "$path" ]] || continue
        git cat-file -e "HEAD:${path}" 2>/dev/null || continue
        local n
        n="$(git show "HEAD:${path}" \
          | { grep -E "$pattern" || true; } \
          | { grep -cE "$ALLOW_PATTERN" || true; })"
        (( n > 0 )) && echo "  ${path}: ${n}"
      done
  return 0
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

REASONLESS="$(
  printf '%s\n%s\n' \
    "$(reasonless_at_head "$PY_PATTERN" '*.py')" \
    "$(reasonless_at_head "$TS_PATTERN" '*.ts' '*.tsx' '*.js' '*.jsx' '*.mjs' '*.cjs')" \
  | sed '/^$/d'
)"

if [[ -n "$REASONLESS" ]]; then
  echo "::warning::ratchet-allow with no reason — these exempt nothing:" >&2
  echo "$REASONLESS" >&2
  echo "" >&2
  echo "Write the reason after '--', e.g. '# ratchet-allow -- why this cannot be fixed'." >&2
  echo "" >&2
fi

if [[ -n "$GROWN" ]]; then
  echo "::error::New inline lint-suppression comment(s) introduced vs ${BASE}:" >&2
  while read -r path before after; do
    echo "  ${path}: ${before} -> ${after} (+$((after - before)))" >&2
  done <<< "$GROWN"
  echo "" >&2
  echo "Existing suppressions are grandfathered, but new ones must not slip in" >&2
  echo "silently. Three ways forward, best first:" >&2
  echo "" >&2
  echo "  1. Fix the underlying issue — usually possible, and the reason this lane" >&2
  echo "     exists at all." >&2
  echo "  2. Net it out: retire another suppression in the same file." >&2
  echo "  3. If it genuinely cannot be removed, mark the line:" >&2
  echo "         # noqa: E402  # ratchet-allow -- why this cannot be fixed" >&2
  echo "     The reason is mandatory; a bare 'ratchet-allow' exempts nothing." >&2
  echo "     This is line-scoped — prefer it over a per-file-ignores entry, which" >&2
  echo "     turns the rule off for the whole file." >&2
  exit 1
fi

ALLOWED="$(
  printf '%s\n%s\n' \
    "$(allowed_at_head "$PY_PATTERN" '*.py')" \
    "$(allowed_at_head "$TS_PATTERN" '*.ts' '*.tsx' '*.js' '*.jsx' '*.mjs' '*.cjs')" \
  | sed '/^$/d'
)"

if [[ -n "$ALLOWED" ]]; then
  # Reported on green runs too: a waiver that goes quiet once it passes is one
  # nobody ever revisits.
  n_files="$(printf '%s\n' "$ALLOWED" | wc -l | tr -d ' ')"
  n_allows="$(printf '%s\n' "$ALLOWED" | awk -F': ' '{s+=$2} END {print s+0}')"
  echo "${n_allows} ratchet-allow(s) across ${n_files} changed file(s):"
  echo "$ALLOWED"
fi

echo "No new inline suppression comments vs ${BASE}."
