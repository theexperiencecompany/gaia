#!/usr/bin/env bash
# log.sh — the log-readability convention of .github/CLAUDE.md, as four calls.
#
# Every consolidated scripts/ci entrypoint sources this so the lanes read the
# same way for humans and for agents: raw tool output inside a collapsible
# ::group::, and the LAST line a one-line verdict. Sourced, never executed —
# it defines functions and touches nothing at source time.
#
#   ci_group "Ruff output"   → opens a collapsible section (stdout)
#   ci_endgroup              → closes it
#   ci_ok  "ruff: OK (12 files)"  → the one-line verdict, last line of a step
#   ci_warn "..."            → ::warning:: annotation, keeps going
#   ci_die  "..."            → ::error:: annotation, exits 1 (fail loud)
#
# ::group::/::warning::/::error:: are GitHub Actions workflow commands; off a
# runner they are still readable plain text, so scripts behave locally too.

ci_group() { printf '::group::%s\n' "$*"; }

ci_endgroup() { printf '::endgroup::\n'; }

ci_ok() { printf '%s\n' "$*"; }

ci_warn() { printf '::warning::%s\n' "$*" >&2; }

ci_die() {
  printf '::error::%s\n' "$*" >&2
  exit 1
}
