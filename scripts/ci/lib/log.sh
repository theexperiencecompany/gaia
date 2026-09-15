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
#
# A GATED lane says the same thing through the verdict contract instead, so
# that the annotation, the step summary and the machine-readable file are one
# call and cannot drift apart:
#
#   ci_verdict     --lane X --status pass --summary "..."
#   ci_verdict_die --lane X --status fail --summary "..." --finding f.py:12:msg
#
# All the logic lives in scripts/ci/verdict.py (see its header). `emit` always
# exits 0 because it reports rather than decides — the dying is right here, so
# a call site reads as one of the two and never as a silent third thing.

ci_group() { printf '::group::%s\n' "$*"; }

ci_endgroup() { printf '::endgroup::\n'; }

ci_ok() { printf '%s\n' "$*"; }

ci_warn() { printf '::warning::%s\n' "$*" >&2; }

ci_die() {
  printf '::error::%s\n' "$*" >&2
  exit 1
}

# Resolved when SOURCED, not when called: lanes `cd` into worktrees and
# scratch dirs after sourcing (regression-proof, mutation.sh), and a path
# built from ${BASH_SOURCE[0]} at call time is relative to wherever the
# caller is standing by then — "can't open …/../../scripts/ci/lib/../verdict.py"
# killed regression-proof on #1202 exactly so.
_CI_VERDICT_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/verdict.py"
ci_verdict() { python3 "$_CI_VERDICT_PY" emit "$@"; }

ci_verdict_die() {
  ci_verdict "$@"
  exit 1
}
