#!/usr/bin/env bash
# changes.sh — what did this PR actually change? The one place a lane asks.
#
# Subcommands:
#   base                     The branch this PR is REALLY based on (on a
#                            merge_group run, the commit the group was built
#                            on). Resolved once per run and handed to every
#                            lane as $GAIA_PR_BASE. See the contract below.
#   base-rev                 The git revision $GAIA_PR_BASE names: origin/<branch>
#                            for a branch, the commit itself for a sha. Every
#                            diff against the base goes through it.
#   files [--task <t>] <ext> [<ext> ...]
#                            The changed files for a lane to scope to, filtered
#                            to those extensions. With --task, only those nx
#                            matched to <t>'s inputs ($TASK_FILES from detect,
#                            else nx asked), and __FULL__ when nx reached <t>
#                            through its config. See the contract below.
#   py-source [--task <t>]   Like `files py`, but drops the paths the Python
#                            tools exclude in a full scan (tests, scripts,
#                            migrations, …). Same three-state contract.
#   scoped --task <t> (--ext "<exts>" | --py-source) [--env | --full "<args>"] -- <cmd…>
#                            Run <cmd> over what `files` / `py-source` answer:
#                            the changed files appended (or as $CHANGED_FILES
#                            with --env), the --full args on a full scan, and
#                            nothing at all when no file it reads changed.
#   affected                 Which CI tasks does this change reach? Asks
#                            `nx affected --explain` (lib/nx_affected.py) and
#                            writes tasks, projects, task_files,
#                            typescript_projects and release_groups to
#                            $GITHUB_OUTPUT. Every task on a
#                            dispatch, unless --since-last-success.
#
# `base` — WHY THIS EXISTS. For a PR in a native GitHub stack, the
# `pull_request` event payload carries the STACK'S TRUNK as base.ref, not the
# PR's parent: measured 2026-09-11 on #1161/#1202/#1175, where `gh api pulls/N
# .base.ref` returned the real parent for each while `github.base_ref` inside
# every job said `master`, from the morning `gh stack link` onward. Every lane
# here scopes to that value, so all three PRs linted, type-checked and mutated
# the whole stack: #1175's plan mutated 119 modules for a one-module diff. The
# API is the only source that tells the truth, so the run asks it ONCE and
# hands the answer down as $GAIA_PR_BASE.
#
# `files` modes (signalled by a sentinel on the first line of stdout):
#
#   PUSH / FULL-SCAN MODE  (no base ref at all — i.e. not a PR)
#     Prints the single line "__FULL__" and exits 0. Callers MUST treat this
#     as "scan the whole repo with the lane's existing full command".
#
#   PR MODE  (a base ref is set — pull_request event)
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
# Workflow files (.yml) belong in a lane's extension list only when that check
# reads them (tool-pins). A workflow-only PR still validates CI itself because
# the checks that read .github name it in their nx inputs (.github/jobs/).
#
# Diff accuracy note: the merge-base ("...") diff requires the base ref to be
# present locally, so PR lanes that consume `files` must checkout with
# `fetch-depth: 0`. The script fetches the base ref defensively as well.
#
# `base` on a merge_group run — the event carries no PR number and no
# base_ref. Its base is `merge_group.base_sha`: for the second PR in the queue
# that is the FIRST PR's group commit, not master's tip, so naming the branch
# would charge it with the change ahead of it in the queue.
#
# Env contract:
#   base           MERGE_GROUP_BASE_SHA (github.event.merge_group.base_sha; wins
#                  when set), PR_NUMBER (github.event.pull_request.number),
#                  GITHUB_REPOSITORY, GITHUB_TOKEN (read-only
#                  `contents`/`pull-requests` is enough), GITHUB_BASE_REF (the
#                  fallback), GITHUB_OUTPUT (optional).
#   base-rev       GAIA_PR_BASE or GITHUB_BASE_REF.
#   files          GAIA_PR_BASE, GITHUB_BASE_REF, GITHUB_ACTIONS, NX_BASE (local).
#   py-source      as `files`; also reads pyproject.toml from the repo root.
#   affected       GITHUB_EVENT_NAME, GAIA_PR_BASE (pull_request, merge_group),
#                  NX_BASE and NX_HEAD (nrwl/nx-set-shas, on a push), GITHUB_OUTPUT.
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"

# The branch this PR is really based on, printed bare (no `origin/` prefix) and
# written to $GITHUB_OUTPUT as base_ref when that is set.
#
# API first, payload second, and the two are NOT interchangeable — see the note
# at the top of this file. Empty output is a valid answer: it means "no PR", and
# `files` turns that into the full-scan sentinel exactly as before.
cmd_base() {

  local resolved="${MERGE_GROUP_BASE_SHA:-}"

  if [[ -z "$resolved" && -n "${PR_NUMBER:-}" ]]; then
    # A failure here is announced, never swallowed. The fallback is today's
    # (wrong, for a stacked PR) behaviour, so a silent one would restore the
    # bug invisibly; failing the run outright on a GitHub API blip would red
    # every PR instead, which is worse than a loud over-scoped lane.
    if ! resolved="$(gh api "repos/${GITHUB_REPOSITORY}/pulls/${PR_NUMBER}" --jq .base.ref 2>&1)"; then
      echo "::warning::changes.sh base: could not read the PR's base from the API (${resolved}) — falling back to the event payload, which names the STACK TRUNK for a stacked PR and will over-scope every lane"
      resolved=""
    fi
  fi

  if [[ -z "$resolved" ]]; then
    resolved="${GITHUB_BASE_REF:-}"
  fi

  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "base_ref=${resolved}" >> "$GITHUB_OUTPUT"
  fi
  printf '%s\n' "$resolved"
}

# The base every lane scopes to: the resolved one when the run has it, the raw
# payload otherwise (a local run, or a lane that predates the resolver).
_base_ref() {
  printf '%s' "${GAIA_PR_BASE:-${GITHUB_BASE_REF:-}}"
}

# The revision a base names: the remote-tracking branch when it is a branch,
# the commit itself when it is a sha (a merge_group's base). Fails loud on
# anything else — a diff against an unresolved base is no diff at all.
_base_rev() {
  local base="$1"
  if git rev-parse --verify -q "origin/${base}^{commit}" > /dev/null; then
    printf 'origin/%s\n' "$base"
  elif git rev-parse --verify -q "${base}^{commit}" > /dev/null; then
    printf '%s\n' "$base"
  else
    echo "changes.sh: cannot resolve the base '${base}' as origin/${base} or as a commit" >&2
    return 1
  fi
}

# The base a lane diffs against: the PR's, or master for a local run (NX_BASE
# when nx-set-shas exported one). Empty only in CI off a PR.
_resolved_base() {
  local base
  base="$(_base_ref)"
  if [[ -z "$base" && -z "${GITHUB_ACTIONS:-}" ]]; then
    base="${NX_BASE:-master}"
    base="${base#origin/}"
  fi
  printf '%s' "$base"
}

cmd_base_rev() {
  local base
  base="$(_resolved_base)"
  if [[ -z "$base" ]]; then
    echo "changes.sh base-rev: no base (GAIA_PR_BASE and GITHUB_BASE_REF are both empty)" >&2
    exit 1
  fi
  _base_rev "$base"
}

cmd_files() {

  FULL_SENTINEL="__FULL__"

  local task=""
  if [[ "${1:-}" == "--task" ]]; then
    task="${2:?changes.sh files --task needs a project:target}"
    shift 2
  fi

  # Push / non-PR event inside CI: no base ref to diff against → signal full scan.
  # The GITHUB_ACTIONS guard matters: on a push to master, HEAD *is* origin/master,
  # so falling through to the base-ref diff below would compare the tree against
  # itself, print nothing, and every scoped lane would report "no changed files —
  # skipping" — a vacuous green precisely when master needs scanning. Local runs
  # keep the fallback because there a diff against origin/master is exactly what
  # a pre-commit / local lane invocation wants.
  #
  # BASE, not GITHUB_BASE_REF: on a stacked PR the payload names the stack's
  # trunk and only $GAIA_PR_BASE (resolved from the API by `base`) names the
  # parent. Lanes that never see the variable keep the old behaviour exactly.
  local BASE
  BASE="$(_resolved_base)"
  if [[ -z "$BASE" ]]; then
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
    fetch --no-tags origin "$BASE" 2>/dev/null || true

  # `...HEAD` diffs against the merge-base of the base ref and HEAD — the same set
  # of files GitHub shows as "Files changed" in the PR. --diff-filter=ACMR drops
  # deletions so we never hand a tool a path that no longer exists.
  # `|| true` on grep: a PR that changes zero matching files is a valid "skip"
  # case, not an error. Without it, grep's no-match exit 1 + `set -o pipefail`
  # would make this script exit 1 and fail the lane's `FILES=$(...)` step.
  # The existence guard is a full `if` on purpose: `[[ -f ]] && printf` leaves
  # the loop (and via pipefail, the whole script) with exit 1 when the LAST
  # path fails the test — turning one dead symlink into a hard lane failure.
  local REV
  REV="$(_base_rev "$BASE")"

  # --task <project:target>: the changed files nx matched to that task's
  # inputs (detect's $TASK_FILES, else nx asked here), so a tool is handed only
  # what its check reads; __FULL__ when nx reached it through config instead.
  if [[ -n "$task" ]]; then
    local scoped
    scoped="$(python3 "$(dirname "$0")/lib/nx_affected.py" --files-for "$task" \
      --base "$(git merge-base "$REV" HEAD)")"
    if [[ "$scoped" == "$FULL_SENTINEL" ]]; then
      printf '%s\n' "$FULL_SENTINEL"
      exit 0
    fi
    printf '%s\n' "$scoped" | { grep -E "$ext_regex" || true; } \
      | while IFS= read -r f; do
          if [[ -f "$f" ]]; then
            printf '%s\n' "$f"
          fi
        done
    return 0
  fi

  git diff --name-only --diff-filter=ACMR "${REV}...HEAD" \
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
  FILES="$(cmd_files "$@" py)"

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

# One check's whole step: every lane used to spell out the three states of
# `files` in its own shell block.
cmd_scoped() {
  local task="" exts="" source="files" mode="args" full=""
  while (($#)); do
    case "$1" in
      --task) task="$2"; shift 2 ;;
      --ext) exts="$2"; shift 2 ;;
      --py-source) source="py-source"; shift ;;
      --env) mode="env"; shift ;;
      --full) full="$2"; shift 2 ;;
      --) shift; break ;;
      *) echo "changes.sh scoped: unknown flag $1" >&2; exit 2 ;;
    esac
  done
  (($#)) || { echo "changes.sh scoped: no command after --" >&2; exit 2; }
  local files
  if [[ "$source" == py-source ]]; then
    files="$(cmd_py_source --task "${task:?--task is required}")"
  else
    # shellcheck disable=SC2086 # --ext is a space-separated extension list
    files="$(cmd_files --task "${task:?--task is required}" ${exts:?--ext or --py-source is required})"
  fi
  # The lists split on whitespace, never glob: xenon's `-e apps/api/tests/**` is a pattern for xenon.
  set -f
  if [[ "$files" == "__FULL__" ]]; then
    # shellcheck disable=SC2086 # --full is the full scan's argument list
    exec "$@" $full
  elif [[ -z "$files" ]]; then
    ci_ok "$task: no file it reads changed — nothing to check"
  elif [[ "$mode" == env ]]; then
    CHANGED_FILES="$files" exec "$@"
  else
    # shellcheck disable=SC2086 # one path per line, none with spaces
    exec "$@" $files
  fi
}

# A PR and a merge group measure from the base `base` resolved, like `files`:
# nx-set-shas reads the event payload, which names a stack's trunk, and on a
# merge group would charge the PR with the group queued ahead of it.
cmd_affected() {
  local event="${GITHUB_EVENT_NAME:?GITHUB_EVENT_NAME is required}" base
  # build.yml measures every event from nx-set-shas: a dispatched redeploy
  # ships what changed since the last good run, not every image.
  [[ "${1:-}" == "--since-last-success" ]] && event=push
  case "$event" in
    workflow_dispatch)
      python3 "$(dirname "$0")/lib/nx_affected.py" --all
      ;;
    pull_request | merge_group)
      base="$(git merge-base "$(cmd_base_rev)" HEAD)"
      python3 "$(dirname "$0")/lib/nx_affected.py" --base "$base" --head HEAD
      ;;
    *)
      python3 "$(dirname "$0")/lib/nx_affected.py" \
        --base "${NX_BASE:?NX_BASE is required (nrwl/nx-set-shas)}" --head "${NX_HEAD:-HEAD}"
      ;;
  esac
}

usage() {
  sed -n '2,31p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    base)          cmd_base "$@" ;;
    base-rev)      cmd_base_rev "$@" ;;
    files)         cmd_files "$@" ;;
    py-source)     cmd_py_source "$@" ;;
    affected)      cmd_affected "$@" ;;
    scoped)        cmd_scoped "$@" ;;
    *)
      echo "changes.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
