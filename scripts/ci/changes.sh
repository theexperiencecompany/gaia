#!/usr/bin/env bash
# changes.sh — what did this PR actually change? The one place a lane asks.
#
# Subcommands:
#   files <ext> [<ext> ...]  The changed files for a lane to scope to, filtered
#                            to those extensions. See the contract below.
#   py-source                Like `files py`, but drops the paths the Python
#                            tools exclude in a full scan (tests, scripts,
#                            migrations, …). Same three-state contract.
#   docker-inputs            Does this PR touch anything the api image build
#                            depends on? Writes build=true|false to
#                            $GITHUB_OUTPUT.
#
# `files` modes (signalled by a sentinel on the first line of stdout):
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
#   FILES=$(scripts/ci/changes.sh files <exts>)
#   if [ "$FILES" = "__FULL__" ]; then  <full command>          # push
#   elif [ -z "$FILES" ]; then          echo "skip"; exit 0     # PR, nothing relevant
#   else                                <tool> $FILES           # PR, diff-scoped
#   fi
#
# Workflow files (.yml) belong ONLY in the code-quality.yml `changes` job's
# superset detect lists, never in a lane's scoping list: a workflow-only PR
# must light the lanes up (so CI changes get validated) while every lane
# self-skips when its own ext list matches nothing.
#
# Diff accuracy note: the merge-base ("...") diff requires the base ref to be
# present locally, so PR lanes that consume `files` must checkout with
# `fetch-depth: 0`. The script fetches the base ref defensively as well.
#
# Env contract:
#   files          GITHUB_BASE_REF, GITHUB_ACTIONS, NX_BASE (local fallback).
#   py-source      as `files`; also reads pyproject.toml from the repo root.
#   docker-inputs  BASE_BRANCH (github.base_ref), GITHUB_OUTPUT.
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"

cmd_files() {

  FULL_SENTINEL="__FULL__"

  # Push / non-PR event inside CI: no base ref to diff against → signal full scan.
  # The GITHUB_ACTIONS guard matters: on a push to master, HEAD *is* origin/master,
  # so falling through to the base-ref diff below would compare the tree against
  # itself, print nothing, and every scoped lane would report "no changed files —
  # skipping" — a vacuous green precisely when master needs scanning. Local runs
  # keep the fallback because there a diff against origin/master is exactly what
  # a pre-commit / local lane invocation wants.
  if [[ -z "${GITHUB_BASE_REF:-}" ]]; then
    if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
      printf '%s\n' "$FULL_SENTINEL"
      exit 0
    fi
    # Fall back to NX_BASE (set by nrwl/nx-set-shas) or origin/master for local runs
    if [[ -n "${NX_BASE:-}" ]]; then
      GITHUB_BASE_REF="${NX_BASE#origin/}"
    else
      GITHUB_BASE_REF="master"
    fi
  fi
  # Still empty (should not happen) → full scan
  if [[ -z "${GITHUB_BASE_REF:-}" ]]; then
    printf '%s\n' "$FULL_SENTINEL"
    exit 0
  fi

  if [[ "$#" -eq 0 ]]; then
    echo "changes.sh files: at least one extension argument is required" >&2
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
  # unshallows the base.
  #
  # MUST NOT use `--depth=1`: a depth-limited fetch records the fetched tip in
  # .git/shallow even when the repository already has full history, and once the
  # base ref is shallow `git diff origin/$BASE...HEAD` fails with "no merge
  # base" — turning a quiet no-op fetch into four red lanes (file-size,
  # types-location, components-per-file, observability). A full-depth fetch is
  # bounded by the timeout below either way.
  #
  # Hard timeout + low-speed guard so a stalled HTTPS connection fails fast
  # instead of hanging until the job's timeout-minutes cap (which surfaces as a
  # `cancelled` lane and fails the quality gate). If the fetch dies, the diff
  # below falls back to whatever base ref is already local.
  timeout 60 git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 \
    fetch --no-tags origin "$GITHUB_BASE_REF" 2>/dev/null || true

  # `...HEAD` diffs against the merge-base of the base ref and HEAD — the same set
  # of files GitHub shows as "Files changed" in the PR. --diff-filter=ACMR drops
  # deletions so we never hand a tool a path that no longer exists.
  # `|| true` on grep: a PR that changes zero matching files is a valid "skip"
  # case, not an error. Without it, grep's no-match exit 1 + `set -o pipefail`
  # would make this script exit 1 and fail the lane's `FILES=$(...)` step.
  # The existence guard is a full `if` on purpose: `[[ -f ]] && printf` leaves
  # the loop (and via pipefail, the whole script) with exit 1 when the LAST
  # path fails the test — turning one dead symlink into a hard lane failure.
  git diff --name-only --diff-filter=ACMR "origin/${GITHUB_BASE_REF}...HEAD" \
    | { grep -E "$ext_regex" || true; } \
    | while IFS= read -r f; do
        if [[ -f "$f" ]]; then
          printf '%s\n' "$f"
        fi
      done
}

# Passing explicit files to interrogate/xenon/bandit bypasses their config
# excludes, so a changed test file gets scanned on a PR when a full scan would
# skip it. The exclude list is read from pyproject's [tool.interrogate].exclude
# so there is a single source of truth.
cmd_py_source() {

  # A subshell, so the `exit 0` cmd_files uses for its two sentinel states ends
  # the substitution rather than this script.
  local FILES
  FILES="$(cmd_files py)"

  if [[ "$FILES" == "__FULL__" || -z "$FILES" ]]; then
    printf '%s\n' "$FILES"
    return 0
  fi

  # Program via -c so the file list can be piped on stdin. Each exclude glob
  # reduces to a path segment (**/tests) or a basename (**/conftest.py).
  printf '%s\n' "$FILES" | python3 -c '
import pathlib
import sys
import tomllib

patterns = tomllib.loads(pathlib.Path("pyproject.toml").read_text())[
    "tool"
]["interrogate"]["exclude"]

segments, basenames = set(), set()
for pat in patterns:
    core = pat.strip("/")
    if core.startswith("**/"):
        core = core[3:]
    if core.endswith("/**"):
        core = core[:-3]
    core = core.strip("/")
    if "/" in core or "*" in core:
        continue
    (basenames if core.endswith(".py") else segments).add(core)

for line in filter(None, sys.stdin.read().splitlines()):
    parts = line.split("/")
    if segments & set(parts) or parts[-1] in basenames:
        continue
    print(line)
'
}

cmd_docker_inputs() {

  BASE_BRANCH="${BASE_BRANCH:?BASE_BRANCH is required (github.base_ref)}"
  IMAGE_INPUTS=(
    apps/api/Dockerfile
    .dockerignore
    uv.lock
    pyproject.toml
    apps/api/pyproject.toml
    libs/pyproject.toml
    # The pin gate that keeps the browsers stage honest lives in here now.
    scripts/ci/audit.sh
    # The per-Dockerfile ignore file decides what enters the build CONTEXT, so
    # editing it changes the image as surely as editing the Dockerfile — a
    # newly-excluded path silently drops out of the layer while this said
    # "image inputs unchanged" and skipped the build. The ROOT .dockerignore was
    # listed from the start; apps/api/Dockerfile.dockerignore, which is the one
    # BuildKit actually reads for this image, was not. A glob, so a second
    # image's ignore file is covered the day it is added, not the day someone
    # notices it is missing.
    '*Dockerfile.dockerignore'
  )

  # No --depth: it re-shallows the box's persistent workspace, and the next
  # checkout then re-unshallows from GitHub (100 s).
  git fetch -q --no-tags origin "$BASE_BRANCH"
  CHANGED="$(git diff --name-only "origin/$BASE_BRANCH" HEAD -- "${IMAGE_INPUTS[@]}")"

  if [[ -n "$CHANGED" ]]; then
    echo "build=true" >> "$GITHUB_OUTPUT"
    echo "image inputs changed:"
    echo "$CHANGED"
  else
    echo "build=false" >> "$GITHUB_OUTPUT"
    echo "image inputs unchanged against origin/$BASE_BRANCH — skipping the build"
  fi
}

usage() {
  sed -n '2,13p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    files)         cmd_files "$@" ;;
    py-source)     cmd_py_source "$@" ;;
    docker-inputs) cmd_docker_inputs "$@" ;;
    *)
      echo "changes.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
