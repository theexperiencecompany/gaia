#!/usr/bin/env bash
# mutation.sh — everything about MUTATION TESTING: is the suite strong enough
# to notice if this code were wrong?
#
# Subcommands:
#   matrix                   Emit the changed app modules + their test files as
#                            JSON — the input `plan` and `local` fan out from.
#                            Fails loudly when changed app code has no test.
#   plan                     Emit the lane's GitHub Actions matrix — one shard
#                            per changed module, capped at the matrix's own
#                            max-parallel. Writes matrix/count to $GITHUB_OUTPUT.
#   shard                    Run every module in $GROUP, in order; the shard's
#                            exit code is the worst of them.
#   module <mod> [tests] [ranges]
#                            Mutate ONE module with mutmut and require the suite
#                            to kill every mutant on the PR's changed lines.
#                            This is the engine both `shard` and `local` drive.
#   local [modules...]       Run the whole gate on this machine exactly as the
#                            lane runs it — the plan wired to the shards, sized
#                            to the local CPU budget. Logs under
#                            verify-logs/mutation/.
#   replay <verdict|dir|shard.log> <mutant-id|file.py:LINE>
#                            Re-apply ONE survivor's diff to a scratch copy of
#                            apps/api and run that module's mapped tests —
#                            killed or survived, without a lane run. mutmut's
#                            mutant numbering depends on the diff scope and
#                            cannot be regenerated locally, so the recorded diff
#                            is the only way back to a named survivor. The
#                            working tree is never touched, and that is checked.
#
# Env contract:
#   matrix  none directly; delegates the diff to `changes.sh files py`.
#   plan    GITHUB_OUTPUT (stdout-only when unset).
#   shard   GROUP (required, compact JSON array of {module,testfiles,ranges});
#           SHARD_LOG (shard.log), GITHUB_STEP_SUMMARY. Produces TWO things:
#           <shard>.verdict.json beside the log — this lane's own uncapped
#           record, what `replay` reads back — and one shared-schema verdict per
#           module, written by `verdict.py emit` into the directory
#           `verdict.py dir` reports (GAIA_VERDICT_DIR > $RUNNER_TEMP/verdicts >
#           verify-logs/verdicts), which is what the quality gate consolidates.
#   module  MUTMUT_WORKDIR_BASE, MUTMUT_MAX_CHILDREN, MUTMUT_KEEP_WORKDIR,
#           MUTATION_VERDICT_DIR (where the module RECORD lands; the shard sets
#           it to a scratch dir beside the log).
#   local   MUTATION_JOBS, MUTATION_CPU_BUDGET, MUTMUT_MAX_CHILDREN.
#   replay  none.
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"
# shellcheck source=scripts/ci/lib/cpu-slots.sh
source "$(dirname "$0")/lib/cpu-slots.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# The one test tier that cannot run without live Mongo and Redis, and so the
# one thing that decides which runner pool a shard belongs to. `plan` groups by
# it and `shard` re-derives its own pool from it — exported rather than repeated
# inside the planner's heredoc so the two can never disagree about what
# "needs services" means.
export SERVICES_TIER="tests/contracts/"

# The interpreter that has mutmut and the API's test dependencies. Both the
# mutation run and `replay` need it, and "which python" is not a question either
# of them should answer differently.
_venv_python() {
  local candidate
  for candidate in "$REPO_ROOT/.venv/bin/python" "$REPO_ROOT/apps/api/.venv/bin/python"; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  echo "ERROR: mutation.sh — venv python not found (run nx run api:sync first)." >&2
  return 1
}

# Where the shared lane verdicts go — ASKED, never derived.
#
# The answer is `verdict.py`'s to give (GAIA_VERDICT_DIR > $RUNNER_TEMP/verdicts
# > verify-logs/verdicts), and a shell copy of that order is wrong the moment it
# moves: the last copy defaulted to the checkout, where no runner reads, so
# every mutation verdict would have landed somewhere the gate calls NO VERDICT.
# One call, one answer, and a loud failure if it comes back empty — a blank
# directory here would send `rm -rf "$VERDICT_ROOT/mutation"` at "/mutation".
_verdict_root() {
  local python_bin resolved
  python_bin="$(_venv_python)" || return 1
  resolved="$("$python_bin" "$SCRIPT_DIR/verdict.py" dir)" || {
    echo "ERROR: mutation.sh — 'verdict.py dir' failed; cannot place the lane verdicts." >&2
    return 1
  }
  if [ -z "$resolved" ]; then
    echo "ERROR: mutation.sh — 'verdict.py dir' printed nothing." >&2
    return 1
  fi
  printf '%s\n' "$resolved"
}

# `app/services/x.py` -> `app_services_x`, the record file's name. Mirrors
# `module_slug` in lib/mutation_report.py: the shell side names the file, the
# python side names it in the advice it prints, and they have to agree.
_record_slug() {
  local module="${1%.py}"
  printf '%s\n' "${module//\//_}"
}

# This module's record — this lane's own schema, merged into the shard's
# verdict.json and reported to the gate by `collect`. Called from cmd_module
# only, and reads MODULE / TESTFILES / VENV_PY / WORKDIR from it: every exit
# path of that function owes the shard a record, and threading five values
# through each of them is how one path ends up not writing one.
#
#   _write_record <status> <reason> <records-tsv> <diffs-file>
_write_record() {
  local status="$1" reason="$2" records="$3" diffs="$4" testfiles_json
  testfiles_json="$(printf '%s\n' "${TESTFILES[@]+"${TESTFILES[@]}"}" | python3 -c '
import json
import sys

print(json.dumps([line for line in sys.stdin.read().splitlines() if line]))')"
  "$VENV_PY" "$SCRIPT_DIR/lib/mutation_report.py" module \
    --module "$MODULE" --path "apps/api/$MODULE" \
    --module-file "$REPO_ROOT/apps/api/$MODULE" \
    --records "$records" --diffs "$diffs" \
    --testfiles "$testfiles_json" --status "$status" --reason "$reason" \
    --out "${MUTATION_VERDICT_DIR:-$WORKDIR}/$(_record_slug "$MODULE").json" >&2
}

# Emit the mutation-check matrix: every changed app module + its test file.
#
# Used by the test-mutation lane (code-quality.yml) to run mutation testing
# per changed module in parallel GitHub jobs. Reference detection is AST-based
# (lib/mutation_matrix.py) because grep misses this codebase's patch-target
# strings and from-package submodule imports.
#
# Fails loudly when changed app code has no test file anywhere — the "no
# bullshit tests" rule enforced mechanically.
cmd_matrix() {

  cd "$REPO_ROOT"

  CHANGED_PY="$(scripts/ci/changes.sh files py)"
  if [ -z "$CHANGED_PY" ]; then
    echo '[]'
    return 0
  fi
  if [ "$CHANGED_PY" = "__FULL__" ]; then
    # Push / workflow_dispatch events have no PR diff to target mutants at, and
    # this check is inherently diff-based (lib/mutation_matrix.py mutates only
    # changed lines) — there is no "full repo" equivalent to run instead, and
    # faking one across every apps/api/app module would blow the lane's 30 min
    # budget many times over. The gate already ran against this exact diff on
    # the PR before merge; skip rather than silently report zero mutants as if
    # nothing needed proving. Logged so a push-triggered run doesn't read as
    # "nothing to mutate" when it actually means "not applicable here".
    echo "mutation matrix: push/full-scan event — skipping (diff-based check; already gated on the originating PR)" >&2
    echo '[]'
    return 0
  fi

  # Changed app modules only; entry points and __init__ files are not
  # mutation targets (nothing meaningful to mutate, no natural test).
  #
  # Each grep is guarded: it exits 1 when nothing matches, which under `pipefail`
  # failed the whole lane for any PR that changed Python outside apps/api/app/ and
  # nothing inside it (tools/, scripts/, libs/ — this file's own tests included).
  # An empty selection is a valid answer, and the orchestrator already handles it
  # ("no changed app modules — nothing to mutate"); only a real error should fail.
  printf '%s\n' "$CHANGED_PY" |
    { grep '^apps/api/app/.*\.py$' || true; } |
    { grep -v 'app/main\.py$' || true; } |
    { grep -v 'app/worker\.py$' || true; } |
    { grep -v '__init__\.py$' || true; } |
    python3 "$SCRIPT_DIR/lib/mutation_matrix.py"
}

cmd_plan() {

  cd "$REPO_ROOT"

  # Through the environment rather than a fixed /tmp path: two plans running on
  # one machine would otherwise clobber each other's file, and the symptom would
  # be a wrong matrix rather than an error. set -e still aborts here when the
  # matrix script exits non-zero.
  MATRIX_JSON="$(cmd_matrix)"
  export MATRIX_JSON

  python3 - << 'EOF'
import json
import os

# Bounded so the matrix stays clear of GitHub's hard 256-job limit, which a
# one-shard-per-module plan blew through on the mypy-strict diff — no matrix, a
# skipped lane, and a skipped lane counts as a pass.
#
# 6 rather than code-quality.yml's max-parallel of 4, deliberately. Sizing to
# max-parallel (4, from 2026-08-29 against a 12-runner pool)
# only holds while one wave can carry the whole diff: a 110-module diff packs 28
# modules per shard, and on run 34476365942 shards 1 and 3 drew enough slow ones
# to still be running at the step's cutoff — 25 of 28 finished, every one clean,
# so the lane went red on budget rather than on a survivor. Past that point it is
# the shard, not the wave, that has to fit. Six run as 4 + 2 and cost one extra
# wave of setup, which is worth strictly more than a red lane that proved nothing.
MAX_SHARDS = 6

# The tier that needs live Mongo and Redis (mutation.sh's SERVICES_TIER, passed
# in rather than repeated). A shard whose modules map to one of these files
# brings the services up in setup (`pool: services`); every other shard is
# `unit` and starts none, so it claims no test-services lane. A shard is
# homogeneous by construction, and its pool travels with it: the workflow
# conditions the services steps on it. (It once also chose the runner pool —
# `unit` shards ran on the lint instances — until three stacked PRs showed nine
# 30-minute shards starving every short lint lane; now all shards share the
# `gaia-home` pool and `pool` only says whether services are needed.)
SERVICES_TIER = os.environ["SERVICES_TIER"]
POOLS = ("unit", "services")

modules = json.loads(os.environ["MATRIX_JSON"])
members = {
    "services": [m for m in modules if any(f.startswith(SERVICES_TIER) for f in m["testfiles"])],
    "unit": [m for m in modules if not any(f.startswith(SERVICES_TIER) for f in m["testfiles"])],
}
live = {pool: members[pool] for pool in POOLS if members[pool]}

# MAX_SHARDS is the budget for the WHOLE plan, not per pool: the cap exists to
# stay clear of GitHub's 256-job limit and to keep the wave size honest, and two
# pools that each helped themselves to six would defeat both. Every live pool
# starts with one shard and the rest go to whichever pool is carrying the most
# modules per shard it already has, so the split follows the diff (a typical PR
# touches one or two repositories and ten other modules, and lands 1 + 5).
counts = {pool: 1 for pool in live}
while sum(counts.values()) < MAX_SHARDS:
    hungry = [pool for pool in live if counts[pool] < len(live[pool])]
    if not hungry:
        break
    counts[max(hungry, key=lambda pool: len(live[pool]) / counts[pool])] += 1

shards: list[tuple[str, list[dict[str, str]]]] = []
for pool in POOLS:
    if pool not in live:
        continue
    packed: list[list[dict[str, str]]] = [[] for _ in range(counts[pool])]
    for index, entry in enumerate(live[pool]):
        packed[index % len(packed)].append(
            {
                "module": entry["module"],
                "testfiles": json.dumps(entry["testfiles"], separators=(",", ":")),
                "ranges": json.dumps(entry["changed_lines"], separators=(",", ":")),
            }
        )
    shards.extend((pool, group) for group in packed)

include = [
    {
        # The check's displayed name. A lone module names itself — the common
        # case, and the most useful thing a reviewer can read at a glance. A
        # packed shard says how many it carries, so nothing looks dropped.
        # Either way a services shard says so: it runs on the other pool, so
        # "which shard needed Mongo" is the first question a red one raises.
        "label": (
            (shard[0]["module"] if len(shard) == 1 else f"shard {number}/{len(shards)} ({len(shard)} modules)")
            + (" (services)" if pool == "services" else "")
        ),
        "group": json.dumps(shard, separators=(",", ":")),
        # Read by the job's `runs-on` to pick the runner pool, and by
        # `mutation.sh shard` to decide whether live services are mandatory.
        "pool": pool,
    }
    for number, (pool, shard) in enumerate(shards, start=1)
]

github_output = os.environ.get("GITHUB_OUTPUT")
if github_output:
    with open(github_output, "a") as handle:
        handle.write(f"matrix={json.dumps(include, separators=(',', ':'))}\n")
        handle.write(f"count={len(include)}\n")

if len(shards) < len(modules):
    print(f"{len(modules)} module(s) packed into {len(shards)} shards (matrix job limit)")
else:
    print(f"{len(modules)} module(s) to mutate, one shard each")
for entry in include:
    print(f"  [{entry['pool']:8}] {entry['label']}")
EOF
}

cmd_shard() {

  cd "$REPO_ROOT" || exit 1

  if [ -z "${GROUP:-}" ]; then
    echo "::error::mutation shard started with no GROUP — the plan job did not emit one"
    exit 1
  fi

  # Flattened to a TSV file first, and the parse checked, so an unreadable group
  # fails the shard. Reading it inline instead would leave the loop with nothing
  # to iterate and the shard would exit 0 having mutated nothing — a false green,
  # which is the one outcome this gate must never produce.
  SHARD_TSV="$(mktemp)"
  trap 'rm -f "$SHARD_TSV"' EXIT
  if ! GROUP="$GROUP" python3 -c '
import json
import os
import sys

entries = json.loads(os.environ["GROUP"])
if not entries:
    sys.exit("group is empty")
for entry in entries:
    sys.stdout.write("\t".join((entry["module"], entry["testfiles"], entry["ranges"])) + "\n")
' > "$SHARD_TSV"; then
    echo "::error::mutation shard could not read its GROUP — the plan job emitted something unusable"
    exit 1
  fi

  # Which pool this shard belongs to, read off the work itself rather than
  # trusted from the environment: `plan` groups contract-mapped modules into
  # their own shards, so the mapped test files ARE the classification, and a
  # shard cannot disagree with the runner it was sent to without saying so.
  if grep -q "$SERVICES_TIER" "$SHARD_TSV"; then
    # A contract test with no services does not fail — it SKIPS (its autouse
    # fixture calls pytest.skip), and a mutant no test exercised is reported as
    # "no covering test", which is informational and fails nothing. That is the
    # exact false green this shard split exists to remove, so it is an error
    # here rather than a degraded run.
    if [ "${USE_REAL_SERVICES:-}" != "1" ]; then
      echo "::error::this shard maps ${SERVICES_TIER} tests but USE_REAL_SERVICES is not 1 — every contract test would skip and its mutants would be reported as uncovered rather than surviving. On CI the job must run with pool=services (setup-python-test-env); locally, start the services and export USE_REAL_SERVICES=1."
      exit 1
    fi
    if ! python3 -c '
import os
import socket
import sys
from urllib.parse import urlparse

for name, fallback in (("MONGO_DB", 27017), ("REDIS_URL", 6379)):
    url = os.environ.get(name, "")
    if not url:
        sys.exit(f"{name} is unset — nothing published this lane service endpoints")
    parsed = urlparse(url)
    endpoint = (parsed.hostname or "localhost", parsed.port or fallback)
    try:
        socket.create_connection(endpoint, timeout=5).close()
    except OSError as exc:
        sys.exit(f"{name} at {endpoint[0]}:{endpoint[1]} is unreachable: {exc}")
'; then
      echo "::error::this shard maps ${SERVICES_TIER} tests and USE_REAL_SERVICES=1, but the services are not reachable — the contract tests would ERROR on connect, and an erroring test kills every mutant it touches (a green shard that proved nothing)."
      exit 1
    fi
  elif [ "${USE_REAL_SERVICES:-}" = "1" ]; then
    # The mirror image, and the reason it matters even though no contract test
    # is mapped here: tests/conftest.py swaps the GLOBAL mongodb mock for a real
    # client when the variable is 1, so a unit-only shard that inherited it from
    # a developer's shell would have every mutant killed by a connection error.
    echo "mutation shard: no ${SERVICES_TIER} tests in this shard — unsetting USE_REAL_SERVICES so the unit tiers keep their mocked services"
    unset USE_REAL_SERVICES
  fi

  # CI reads the artifact from the fixed name; the local runner overrides it so
  # shards running side by side do not interleave into one unreadable file.
  SHARD_LOG="${SHARD_LOG:-shard.log}"
  : > "$SHARD_LOG"

  # This lane's own record of the run, beside the log: every survivor with its
  # mutant id, line, one-line change and full diff — what `replay` reads back.
  # Deliberately NOT under verify-logs/verdicts/: `verdict.py consolidate` reads
  # every JSON in that tree as a lane verdict and indexes doc["lane"], so a file
  # of a different shape there does not degrade, it crashes the gate. The
  # contract is reported separately, through `verdict.py emit` (see `collect`).
  #
  # Both names derive from SHARD_LOG: `local` runs every module as its own
  # single-module shard in ONE directory, and fixed names would have those
  # shards overwrite each other's record.
  SHARD_VERDICT="${SHARD_LOG%.log}.verdict.json"
  RECORD_DIR="${SHARD_LOG%.log}.records"
  rm -rf "$RECORD_DIR"
  mkdir -p "$RECORD_DIR"
  RECORD_DIR="$(cd "$RECORD_DIR" && pwd)"
  export MUTATION_VERDICT_DIR="$RECORD_DIR"
  # module<TAB>exit-code, one row per module in the order the shard ran them.
  # The exit code is recorded rather than inferred from the log: a module whose
  # log says nothing conclusive but exited non-zero must not merge as a pass.
  SHARD_RCS="$(mktemp)"
  trap 'rm -f "$SHARD_TSV" "$SHARD_RCS"' EXIT

  # timeout(1) bounds a genuine mutmut hang from OUTSIDE the script: bash defers
  # traps while waiting on a foreground child, so an in-script watchdog can never
  # fire. It is coreutils, so it is absent on a stock macOS — resolve it here
  # rather than let every module die with "timeout: command not found" (rc 127),
  # which reads as 12 failing modules instead of one missing tool.
  TIMEOUT_CMD=()
  if command -v timeout > /dev/null 2>&1; then
    TIMEOUT_CMD=(timeout --signal=KILL 1500)
  elif command -v gtimeout > /dev/null 2>&1; then
    TIMEOUT_CMD=(gtimeout --signal=KILL 1500)
  else
    echo "NOTE: no timeout(1) — running unbounded (brew install coreutils for the CI-identical watchdog)" >&2
  fi

  # This shard's CPU appetite: mutmut forks one mutant worker per child, and its
  # own default is os.cpu_count() — 16 on the box, so four shards at max-parallel
  # would spawn 64 workers on 16 threads. Bound each shard to nproc-2 (the same
  # budget cmd_local uses; two cores left for the OS and docker) AND take that
  # many host tokens for the run, so the mutation shards queue against the box's
  # physical-core budget instead of thrashing it and the test-python/build lanes.
  # Fail-open and a no-op off the self-hosted box; MUTMUT_MAX_CHILDREN honours an
  # explicit override for the local runner.
  local NPROC BUDGET SLOTS
  NPROC="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
  BUDGET="$(( NPROC > 3 ? NPROC - 2 : 1 ))"
  export MUTMUT_MAX_CHILDREN="${MUTMUT_MAX_CHILDREN:-$BUDGET}"
  # Acquire tokens for the workers we will ACTUALLY spawn, not the default
  # budget: an explicit MUTMUT_MAX_CHILDREN override (e.g. a local runner) can
  # exceed BUDGET, and taking only BUDGET tokens would let the shard run more
  # workers than it holds slots for, weakening the host cap.
  SLOTS="$MUTMUT_MAX_CHILDREN"; [ "$SLOTS" -ge "$BUDGET" ] || SLOTS="$BUDGET"
  cpu_slots_acquire "$SLOTS"

  rc=0
  failed_modules=()
  while IFS=$'\t' read -r module testfiles ranges; do
    [ -n "$module" ] || continue
    echo "=== $module ===" >> "$SHARD_LOG"
    module_rc=0
    ${TIMEOUT_CMD[@]+"${TIMEOUT_CMD[@]}"} \
      bash "$SCRIPT_DIR/mutation.sh" module "$module" "$testfiles" "${ranges:-[]}" \
      >> "$SHARD_LOG" 2>&1 || module_rc=$?
    if [ "$module_rc" = "137" ] || [ "$module_rc" = "124" ]; then
      echo "::error::mutation for $module exceeded its timeout and was killed — see the log for the last phase reached"
    fi
    if [ "$module_rc" != "0" ]; then
      rc="$module_rc"
      failed_modules+=("$module")
    fi
    printf '%s\t%s\n' "$module" "$module_rc" >> "$SHARD_RCS"
  done < "$SHARD_TSV"
  cpu_slots_release "$SLOTS"

  # tail, NEVER cat: with mutmut's debug output on, a busy module writes a 13MB
  # shard.log, and feeding that through the runner's live-log pipe is where this
  # step used to freeze — the write blocks forever somewhere past ~13MB, and a
  # process frozen mid-syscall on the step's own log pipe cannot be killed by the
  # step abort, so the job died at its cap and GitHub destroyed the logs that
  # proved it. The full file ships as the artifact.
  echo "--- $SHARD_LOG (last 200KB; full file in the artifact) ---"
  tail -c 200000 "$SHARD_LOG"

  # Merge the module records into this lane's replay artifact, and report every
  # module to the quality gate through `verdict.py emit` — one verdict per
  # module, with a finding per surviving line and that line's diffs as its
  # detail. Reported HERE rather than inside `module` because `emit` prints the
  # ::error annotations, and a module's own output is redirected into
  # $SHARD_LOG, where an annotation is just text GitHub never sees.
  VERDICT_ROOT="$(_verdict_root)" || exit 1
  python3 "$SCRIPT_DIR/lib/mutation_report.py" collect \
    --log "$SHARD_LOG" --dir "$RECORD_DIR" --rcs "$SHARD_RCS" \
    --out "$SHARD_VERDICT" --repo-root "$REPO_ROOT" --verdict-out "$VERDICT_ROOT"
  # The records were inputs to a merge that succeeded; keeping both copies only
  # invites reading the stale one. A FAILED merge leaves them as the evidence.
  rm -rf "$RECORD_DIR"

  # The verdict, last and on its own. A shard carries several modules when the
  # diff is large, so "this check is red" has to say WHICH — otherwise the only
  # way to find out is scrolling a 200KB tail.
  if [ "${#failed_modules[@]}" -eq 0 ]; then
    echo "Mutation shard OK — every module clean"
  else
    echo "::error::mutation failed for: ${failed_modules[*]}"
  fi

  exit "$rc"
}

cmd_local() {
  # -e off for this one: the orchestrator aggregates its children's exit
  # statuses itself (`wait` returns the last failure) and must still print the
  # per-module summary afterwards. Every failure below is checked explicitly.
  set +e

  cd "$REPO_ROOT" || exit 1

  LOG_DIR="verify-logs/mutation"
  rm -rf "$LOG_DIR"
  mkdir -p "$LOG_DIR"

  # The lane verdicts live outside $LOG_DIR, in the tree `verdict.py` owns, so
  # the wipe above cannot reach them and a stale module from an earlier local
  # run would consolidate as a lane of this one. Cleared here, once, and only
  # this lane's own subdirectory — every other lane writes into the same tree.
  # The path is asked for, never derived (see `_verdict_root`).
  VERDICT_ROOT="$(_verdict_root)" || exit 1
  rm -rf "${VERDICT_ROOT:?}/mutation"

  if [ "$#" -gt 0 ]; then
    MATRIX="$(printf '%s\n' "$@" | sed 's|^apps/api/||; s|^|apps/api/|' |
      python3 "$SCRIPT_DIR/lib/mutation_matrix.py")" || exit 1
  else
    MATRIX="$(cmd_matrix)" || exit 1
  fi

  MODULE_COUNT="$(MATRIX="$MATRIX" python3 -c 'import json,os;print(len(json.loads(os.environ["MATRIX"])))')"
  if [ "$MODULE_COUNT" = "0" ]; then
    echo "mutation: no changed app modules — nothing to mutate"
    exit 0
  fi

  # One TSV row per module, the same three fields `shard` reads.
  TSV="$(mktemp)"
  trap 'rm -f "$TSV"' EXIT
  MATRIX="$MATRIX" python3 - > "$TSV" <<'PY'
import json
import os

for entry in json.loads(os.environ["MATRIX"]):
    print(
        "\t".join(
            (
                entry["module"],
                json.dumps(entry["testfiles"], separators=(",", ":")),
                json.dumps(entry["changed_lines"], separators=(",", ":")),
            )
        )
    )
PY

  echo "mutation: $MODULE_COUNT module(s), logs in $LOG_DIR/"

  # Each module is its own single-module shard: same runner as CI, so a local
  # pass and a lane pass mean the same thing.
  run_one() {
    local module="$1" testfiles="$2" ranges="$3"
    local slug="${module//\//_}"
    GROUP="$(module="$module" testfiles="$testfiles" ranges="$ranges" python3 -c '
import json
import os

print(
    json.dumps(
        [{k: os.environ[k] for k in ("module", "testfiles", "ranges")}],
        separators=(",", ":"),
    )
)')" \
      SHARD_LOG="$LOG_DIR/$slug.log" \
      bash "$SCRIPT_DIR/mutation.sh" shard > "$LOG_DIR/$slug.out" 2>&1
    local rc=$?
    # Recorded to a file, not inferred from the log afterwards: a clean run that
    # generated no mutants at all (decorated functions, changed lines that hold
    # only imports) never prints a verdict line, so grepping for one reports a
    # pass as a crash. The exit code is the only honest signal.
    if [ "$rc" = "0" ]; then
      echo "pass" > "$LOG_DIR/$slug.status"
      echo "  pass      $module"
    elif grep -q "MUTATION FAILED" "$LOG_DIR/$slug.log" 2> /dev/null; then
      echo "survivors" > "$LOG_DIR/$slug.status"
      echo "  SURVIVORS $module  ($LOG_DIR/$slug.log)"
    else
      # mutmut never produced a result — a crash, or the suite's pytest-timeout
      # firing under load. Reporting this as "survivors" would send you hunting
      # for a test gap that does not exist.
      echo "error" > "$LOG_DIR/$slug.status"
      echo "  ERROR     $module  (run produced no result; $LOG_DIR/$slug.log)"
    fi
    return $rc
  }

  # Size the run to the machine. Two levels of parallelism multiply here:
  # modules run concurrently, and mutmut forks --max-children mutant workers
  # inside each. Handing both `nproc` would oversubscribe 16 cores by an order
  # of magnitude and thrash — split one budget between them instead. Two cores
  # are left for the OS and docker. Most runs touch one or two modules, so the
  # weighting favours mutmut's children over module fan-out.
  NPROC="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
  BUDGET="${MUTATION_CPU_BUDGET:-$(( NPROC > 3 ? NPROC - 2 : 1 ))}"
  JOBS="${MUTATION_JOBS:-$MODULE_COUNT}"
  [ "$JOBS" -gt 4 ] && JOBS=4
  [ "$JOBS" -gt "$BUDGET" ] && JOBS="$BUDGET"
  [ "$JOBS" -lt 1 ] && JOBS=1
  CHILDREN=$(( BUDGET / JOBS ))
  [ "$CHILDREN" -lt 1 ] && CHILDREN=1
  export MUTMUT_MAX_CHILDREN="${MUTMUT_MAX_CHILDREN:-$CHILDREN}"
  echo "mutation: $MODULE_COUNT module(s) on $NPROC vCPUs — budget $BUDGET, $JOBS in parallel x $MUTMUT_MAX_CHILDREN mutant worker(s)"

  # Batch-and-wait rather than `wait -n`: macOS ships bash 3.2, where `wait -n`
  # does not exist. It fails instantly there, so the scheduler never waits, the
  # summary races the jobs still writing their results, and every run reports
  # whatever happened to be on disk at that moment.
  running=0
  while IFS=$'\t' read -r module testfiles ranges; do
    [ -n "$module" ] || continue
    run_one "$module" "$testfiles" "$ranges" &
    running=$((running + 1))
    if [ "$running" -ge "$JOBS" ]; then
      wait
      running=0
    fi
  done < "$TSV"
  wait

  # The verdict comes from the per-module status files the jobs wrote.
  failed=""
  errored=""
  while IFS=$'\t' read -r module _ _; do
    [ -n "$module" ] || continue
    slug="${module//\//_}"
    case "$(cat "$LOG_DIR/$slug.status" 2> /dev/null)" in
      pass) ;;
      survivors) failed="$failed $module" ;;
      *) errored="$errored $module" ;;
    esac
  done < "$TSV"

  if [ -n "$errored" ]; then
    echo
    echo "mutation: module(s) produced NO result (crash or timeout, not survivors):"
    for m in $errored; do echo "  $m"; done
    echo "  Retry these with MUTATION_JOBS=1 before believing anything about them."
  fi
  if [ -n "$failed" ]; then
    echo
    echo "mutation: module(s) with survivors on changed lines:"
    for m in $failed; do echo "  $m"; done
  fi
  if [ -n "$failed" ] || [ -n "$errored" ]; then
    exit 1
  fi
  echo "mutation: all $MODULE_COUNT module(s) clean"
}

cmd_module() {

  MODULE="${1:?usage: mutation.sh module <module> [test-file] (e.g. app/services/foo.py)}"
  case "$MODULE" in
    apps/api/app/*) MODULE="${MODULE#apps/api/}" ;;
    app/*) : ;;
    *) echo "module must be under app/ (e.g. app/services/foo.py)" >&2; exit 2 ;;
  esac

  TESTFILE_ARG="${2:-}"
  if [ -z "$TESTFILE_ARG" ]; then
    # Derive the natural test file: unit tests mirror app/ with a test_ prefix.
    REL="${MODULE#app/}"
    TESTFILE_ARG="tests/unit/$(dirname "$REL")/test_$(basename "$REL" .py).py"
  fi
  # PR-changed line ranges for this module ([[start,end],...], compact JSON).
  # The gate is diff-driven: survivors on lines the PR did not touch are noted,
  # not failures. The CI lane passes them; omit the argument and they are derived
  # from the same code the lane uses (lib/mutation_matrix.py --scope), so a local run
  # scopes identically instead of defaulting to a scope that cannot fail.
  CHANGED_RANGES="${3-}"

  cd "$REPO_ROOT/apps/api"

  if [ -z "$CHANGED_RANGES" ]; then
    CHANGED_RANGES="$(cd "$REPO_ROOT" && python3 "$SCRIPT_DIR/lib/mutation_matrix.py" --scope "$MODULE")" || exit 1
  fi
  # An empty scope buckets EVERY survivor as out-of-scope, so the run prints "no
  # survivors" and exits 0 no matter how broken the module is. That false green
  # is the one result this gate must never produce — refuse instead.
  if [ "$CHANGED_RANGES" = "[]" ] || [ -z "$CHANGED_RANGES" ]; then
    echo "mutation: empty line scope for $MODULE — refusing to run." >&2
    echo "  An empty scope classifies every survivor as out-of-scope and exits 0," >&2
    echo "  which reports a pass it did not earn. Pass explicit ranges as argument 3," >&2
    echo "  or let them be derived (omit it) from the diff against the base branch." >&2
    exit 2
  fi

  # Argument 2 is either ONE path — what a human types, and what the derived
  # default above produces — or a compact JSON array of them, which is how the CI
  # lane passes every test file that references the module instead of whichever
  # one happened to sort first. A leading '[' is the discriminator; no real path
  # starts with one. Both forms are supported on purpose: the single-path form is
  # the documented local usage, and breaking it to serve CI would be the trade
  # backwards.
  TESTFILES=()
  case "$TESTFILE_ARG" in
    \[*)
      TESTFILES_RAW="$(python3 - "$TESTFILE_ARG" << 'EOF'
import json
import sys

try:
    files = json.loads(sys.argv[1])
except json.JSONDecodeError as exc:
    raise SystemExit(f"argument 2 starts with '[' but is not valid JSON: {exc}")
if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
    raise SystemExit("argument 2 must be a JSON array of path strings")
if not files:
    raise SystemExit("argument 2 is an empty JSON array — no test file to run")
print("\n".join(files))
EOF
  )" || exit 2
      while IFS= read -r testfile; do
        if [ -n "$testfile" ]; then
          TESTFILES+=("$testfile")
        fi
      done <<< "$TESTFILES_RAW"
      ;;
    *) TESTFILES=("$TESTFILE_ARG") ;;
  esac
  # Named individually: "one of these does not exist" is useless when the list
  # came from a generator.
  for testfile in "${TESTFILES[@]}"; do
    if [ ! -f "$testfile" ]; then
      echo "test file not found: $testfile — pass it explicitly as the second argument." >&2
      exit 2
    fi
  done

  VENV_PY="$(_venv_python)" || exit 1

  # Per-invocation workdir: parallel-safe isolation for the config swap, the
  # mutants/ dir, and the pytest run. Absolute path: the trap runs after
  # `cd "$WORKDIR"`, so a relative path would delete the wrong directory.
  #
  # Placed on tmpfs when the machine offers one. Each invocation copies ~65 MB
  # of app + tests + scripts and then has mutmut write a whole mutants/ tree
  # beside it; with several modules in flight those writes, not the mutation
  # work, set the pace. /dev/shm keeps all of it in RAM. Falls back to the
  # working directory on machines without tmpfs (macOS) or when it is nearly
  # full, so a constrained box degrades in speed rather than failing.
  #
  # Real copies, not hardlinks (`cp -al`): the changed-line scoping below
  # rewrites $MODULE in place, and a hardlink shares its inode with the file in
  # the developer's checkout — the pragma stamping would edit the real source.
  # Not symlinks either: a symlinked workdir/app resolves to the SAME inode as
  # apps/api/app — if both ever land on sys.path, CPython raises "cannot load
  # module more than once per process" when the same file is imported under two
  # paths (observed in CI for app.db.chroma).
  WORKDIR_BASE="${MUTMUT_WORKDIR_BASE:-}"
  if [ -z "$WORKDIR_BASE" ]; then
    WORKDIR_BASE="$(pwd)"
    if [ -d /dev/shm ] && [ -w /dev/shm ]; then
      # Need room for the copy plus mutmut's mutants/ tree; 1 GiB is a
      # comfortable ceiling for a single module.
      SHM_FREE_KB="$(df -Pk /dev/shm 2>/dev/null | awk 'NR==2{print $4}')"
      if [ -n "${SHM_FREE_KB:-}" ] && [ "$SHM_FREE_KB" -gt 1048576 ]; then
        WORKDIR_BASE=/dev/shm
      fi
    fi
  fi
  # Named .mutation-$$ so apps/api/.gitignore covers a SIGKILLed run's leftovers.
  WORKDIR="$WORKDIR_BASE/.mutation-$$"

  # Phase tracking.
  #
  # The lane bounds this script with `timeout` (see the test-mutation step in
  # code-quality.yml) rather than an in-script watchdog: bash does not run a trap
  # while it is waiting on a foreground child, so a signal sent to this script
  # would queue behind whatever is stuck. What this side owes is a breadcrumb —
  # a killed run's last printed phase is what turns "it hung" into "it hung in
  # <phase>".
  PHASE_FILE="$(mktemp)"
  START_EPOCH="$(date +%s)"
  _phase() {
    printf '%s' "$1" > "$PHASE_FILE"
    echo "[phase +$(( $(date +%s) - START_EPOCH ))s] $1" >&2
  }
  # pkill -P first: killing the subshell alone orphans its `sleep`, which keeps
  # the inherited stdout/stderr open and hangs any pipeline reading this script
  # long after it has finished.
  # Retire the watchdog by removing its sentinel and waiting for it to notice —
  # no signals, so bash never prints a "Terminated: sleep" notice into the lane
  # log, and nothing can outlive this script holding its stdout open.
  _cleanup() {
    rm -f "$PHASE_FILE"
    # Explicit if, not `&&`: a short-circuit here returns 1 when the keep-var is
    # set, and an EXIT trap's failing last command clobbers the script's exit
    # status — a passing verdict would report EXIT=1.
    if [ -z "${MUTMUT_KEEP_WORKDIR:-}" ]; then
      rm -rf "$WORKDIR"
    fi
  }
  trap _cleanup EXIT
  # EXIT alone does not run on a signal, so a killed run would leave its scratch
  # copy of app/ + tests/ on disk. `exit` re-enters the EXIT trap, so cleanup
  # happens exactly once either way. (A SIGKILL from `timeout` skips both, which
  # is what .mutation-*/ in apps/api/.gitignore covers.)
  trap 'exit 143' TERM INT
  _phase "copy workdir"
  mkdir -p "$WORKDIR"
  cp -r app "$WORKDIR/app"
  cp -r tests "$WORKDIR/tests"
  cp -r scripts "$WORKDIR/scripts"
  cp -f pyproject.toml "$WORKDIR/pyproject.toml"
  # pytest.ini carries asyncio_mode=auto. Under apps/api the workdir found it by
  # walking up; under /dev/shm there is nothing above, and without it every
  # async test fails with "async def functions are not natively supported".
  cp -f pytest.ini "$WORKDIR/pytest.ini"
  cd "$WORKDIR"

  # mutmut 3.x scopes mutation and test selection only via config — point both
  # at the module + its test file(s) for this run (the workdir copy is disposable).
  # Per-mutant test timeout. NOT the suite's 300s: a mutant that induces an
  # infinite loop or a deadlock costs this much wall-clock EACH, and enough of
  # them exhaust the per-module budget below and take the whole module down with
  # them as "not checked" — which fails the lane for a reason that is not a test
  # weakness (measured: app/agents/tools/core/retrieval.py reached 186 of 348
  # mutants in CI with 33 timeouts, and completes in 76s with zero on a
  # developer machine). The whole hermetic suite runs in under 300s with xdist,
  # so a single test in a per-mutant selection needs seconds; 45 leaves ~45x
  # headroom while capping a hang at a fifteenth of what it used to cost.
  # A mutant that times out proves nothing either way and is already excluded
  # from the verdict — this only stops it consuming the module's budget too.
  MUTANT_TEST_TIMEOUT=45
  python3 - "$MODULE" "$MUTANT_TEST_TIMEOUT" "${TESTFILES[@]}" << 'EOF'
import json
import pathlib
import re
import sys

module, mutant_test_timeout, testfiles = sys.argv[1], sys.argv[2], sys.argv[3:]
path = pathlib.Path("pyproject.toml")
text = path.read_text()
selection = ", ".join(json.dumps(testfile) for testfile in testfiles)
replacement = (
    f'[tool.mutmut]\n'
    f'source_paths = ["{module}"]\n'
    f'also_copy = ["app", "tests", "scripts", "pytest.ini"]\n'
    # 20, not 8: the trampoline drops a test from a mutant's stats when the
    # mutated module has more frames than this on the stack, so a depth-8 cap
    # silently unlinked every test that reaches a worker entry point through
    # its own call chain (execute_workflow_by_id -> _run_workflow -> ...) and
    # those mutants survived with green tests pointing right at them.
    f'max_stack_depth = 20\n'
    # The pragma stamping below appends `# pragma: no mutate` to every
    # unchanged line. mutmut's AST visitor only honors that comment on
    # simple statement lines, so interior lines of multi-line statements
    # would still be mutated; the pattern matcher keys on line CONTENT and
    # catches every stamped line — this is what makes the diff-driven
    # scoping actually work.
    f'do_not_mutate_patterns = ["# pragma: no mutate"]\n'
    f'debug = true\n'
    f'pytest_add_cli_args_test_selection = [{selection}]\n'
    f'pytest_add_cli_args = ["-p", "no:xdist", "-o", '
    f'\'addopts=-m "not composio and not model_onboarding and not schemathesis" --strict-markers --timeout={mutant_test_timeout}\']\n'
)
text = re.sub(r"(?ms)^\[tool\.mutmut\].*?(?=^\[|\Z)", replacement, text)
path.write_text(text)
EOF

  _phase "mutmut run"
  echo "mutating $MODULE (tests: ${TESTFILES[*]}) ..."

  # Diff-driven scoping: only the PR's changed lines get mutants, so a 1-line
  # change costs seconds instead of a full-module run. mutmut has no config for
  # it but it does have the mechanism — scripts/test/mutmut_diff_scope.py, loaded
  # into the mutmut process below, reads these two env vars. The survivor-verdict
  # layer further down stays as defense-in-depth.
  # Contract tests hit real Redis, and their teardown flushes a DB keyed on
  # PYTEST_XDIST_WORKER — which mutmut never sets, so every mutant child would
  # land on one DB and flush each other's keys mid-test. A test failed by a
  # neighbour's flush is counted as a kill, and a false kill is a false green.
  # One mutant worker for these modules: a repository's contract suite is ~2s,
  # so serial is cheap exactly where parallel would be wrong.
  for tf in ${TESTFILES[@]+"${TESTFILES[@]}"}; do
    case "$tf" in
      tests/contracts/*)
        export MUTMUT_MAX_CHILDREN=1
        echo "mutation: $MODULE maps a contract test — one mutant worker so real-Redis teardown cannot race" >&2
        break
        ;;
    esac
  done
  export MUTMUT_CHANGED_RANGES="$CHANGED_RANGES"
  export MUTMUT_SCOPED_MODULE="$MODULE"
  MUTMUT_RC=0
  # timeout: mutmut can finish its work and then hang at interpreter teardown
  # (threads from C-extension-heavy test runs keep the process alive — seen
  # with the chroma tests), so the pipeline never completes and the lane
  # hangs. 15 minutes covers even a full-module local run; scoped CI runs
  # finish in well under a minute. A hang past the cap leaves the state for
  # the verdict below to judge (not-checked mutants fail it loudly). The
  # wrapper is a portable `timeout`: GNU coreutils' binary is missing on
  # macOS, and the process-group kill takes mutmut's mutant children with it.
  # The decorated-function patch (mutmut_decorated_patch.py) is imported
  # first so endpoints and other decorated functions become mutation targets,
  # and mutmut_diff_scope.py scopes generation to the PR's changed lines.
  MUTMUT_PATCH_DIR="$REPO_ROOT/scripts/test"
  # Absolute: the run cd's into $WORKDIR, so a relative path resolves nowhere.
  CLASSIFIER="$REPO_ROOT/scripts/test/mutation_classify.py"
  "$VENV_PY" -c "
import os
import signal
import subprocess
import sys

env = dict(os.environ)
# USE_REAL_SERVICES is inherited from the job, not stripped. It used to be
# popped here so the contract tier would skip under mutmut — sized for a
# 2-core Dagger runner where per-mutant real-DB calls blew the timeout. The
# cost of that was invisible: repository code is tested THROUGH Mongo in
# tests/contracts, so with the tier skipped every changed repository method
# reported 'no covering test' and the gate passed on it (users.py, 19 lines,
# on one PR). The home box runs the services per runner instance already
# (setup-python-test-env brings them up, namespaced by RUNNER_INDEX), the
# contract suite for a repository runs in ~2s, and the host CPU governor
# bounds the parallelism the old comment feared. Locally the variable is
# simply whatever the developer exported, as in every other lane.
patch_dir = sys.argv[1]
env['PYTHONPATH'] = patch_dir + os.pathsep + env.get('PYTHONPATH', '')
max_children = os.environ.get('MUTMUT_MAX_CHILDREN', '')
run_args = ['run'] + (['--max-children', max_children] if max_children else [])
# Pre-import the C-extension-heavy modules in the MUTMUT process BEFORE it
# starts: the covered-lines coverage pass unloads every module imported
# during the stats run, and numpy/PyO3 extensions cannot be re-imported in
# one process. Anything imported here is in the baseline snapshot and never
# unloaded.
child_code = (
    'import mutmut_decorated_patch; '
    'import mutmut_diff_scope; '
    'import sys as _sys; '
    f'_sys.argv += {run_args!r}; '
    'from mutmut.__main__ import cli; cli()'
)
proc = subprocess.Popen(
    [sys.executable, '-c', child_code],
    env=env,
    start_new_session=True,
)
try:
    # 12 minutes per module. This was 45, sized for when a module paid ~30s of
    # fresh-process startup per mutant; with the selection scoped to unit tests
    # the SLOWEST real module measured on CI is 1.2 minutes, so 12 is ~10x the
    # worst honest case and anything beyond it is a hang, not slow work.
    #
    # The cap length is load-bearing for the whole lane, not just one module:
    # the orchestrator runs N modules concurrently, so N hung modules occupy
    # every worker and NOTHING else starts. That is what happened — four
    # modules hung, four workers, and the lane was cancelled at its 90-minute
    # budget having never started 13 of the 54 modules. A hang must surface as
    # a fast, named failure rather than eating the whole budget silently.
    proc.communicate(timeout=720)
except subprocess.TimeoutExpired:
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()
    sys.exit(124)
finally:
    # Reap the detached session on EVERY path, not just timeout. mutmut runs
    # in its own session (start_new_session above) so killpg can take the
    # mutant brood down as one unit — but that same detachment hides any
    # straggler from a CI runner's step-abort, which signals the step's
    # process group and walks its tree. A leaked child in the detached
    # session survived the in-script watchdog, timeout(1) --signal=KILL, AND
    # GitHub's own step timeout, holding the rate_limiting shard open to the
    # job cap six runs in a row — and a job cancelled at its cap keeps no
    # logs, which is why there was never any evidence.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
sys.exit(proc.returncode)
" "$MUTMUT_PATCH_DIR" 2>&1 | tee "$WORKDIR/mutmut.log" >&2 || MUTMUT_RC=$?
  if [ "$MUTMUT_RC" -ne 0 ]; then
    # "No mutant had covering tests" is two different facts wearing one
    # message, and they need opposite answers. Either the changed lines hold
    # nothing a test could pin — imports, constants, docstrings, decorators,
    # or code inside a decorated function, which mutmut 3.7 never mutates
    # (verified in its file_mutation.py) — and silence is right; or they are
    # executable code inside a function that NO test reaches, which is the
    # exact gap this lane exists to catch and used to exit 0 on. One PR had
    # 39 of these SKIPs; 10 were the second kind, and the message pointed at
    # a diff-cover lane that does not run on PRs as the reason not to worry.
    # lib/mutation_gap.py draws the line; only the second kind fails.
    if grep -q "could not find any test case for any mutant" "$WORKDIR/mutmut.log"; then
      GAP_LINES="$("$VENV_PY" "$SCRIPT_DIR/lib/mutation_gap.py" "$REPO_ROOT/apps/api/$MODULE" "$CHANGED_RANGES" | tr '\n' ' ')"
      if [ -n "${GAP_LINES// /}" ]; then
        echo "MUTATION FAILED — changed code no test reaches in $MODULE:" >&2
        echo "      line(s) $GAP_LINES" >&2
        echo "      These are executable lines inside a function that this PR added or" >&2
        echo "      changed, and none of the module's mapped tests execute them, so no" >&2
        echo "      mutant there could ever be killed. Write a test that runs them and" >&2
        echo "      asserts what they do — or, if they are only reachable through the" >&2
        echo "      contract tier, say so: that tier does not run in this lane." >&2
        exit 1
      fi
      echo "SKIP: $MODULE — nothing on the changed lines for a test to pin" >&2
      echo "      (imports, constants, docstrings, decorators, or code inside a" >&2
      echo "      decorated function, which mutmut 3.7 cannot mutate)." >&2
      exit 0
    fi
    # mutmut's stats/clean/mutant phases share ONE process, so module-level
    # state (singletons, caches) can leak between phases and break the clean
    # run even though the tests are fine. Self-verify: run the same selection
    # in the plain workdir copy. Passes there -> mutmut-phase artifact, skip
    # with a reason. Fails there too -> a real breakage, fail loudly.
    if grep -q "Failed to run clean test" "$WORKDIR/mutmut.log"; then
      if "$VENV_PY" -m pytest -q "${TESTFILES[@]}" -p no:randomly -p no:random-order \
          -o 'addopts=-m "not composio and not model_onboarding and not schemathesis" --strict-markers --timeout=300' \
          > "$WORKDIR/plain-check.log" 2>&1; then
        echo "SKIP: $MODULE — the tests pass in the plain copy but fail under"
        echo "      mutmut's single-process phase transitions. Module-level state"
        echo "      (singletons/caches) does not survive stats->clean->mutants in"
        echo "      one process — a documented mutmut 3.7 limitation for such modules."
        exit 0
      fi
      echo "REAL FAILURE: $MODULE's tests fail in the plain copy too — see" >&2
      echo "  $WORKDIR/plain-check.log (and mutmut's output above)." >&2
      exit 1
    fi
    # A BadTestExecutionCommandsException is pytest exit 4 (usage/collection
    # error) inside mutmut's IN-PROCESS stats run. That is the documented mutmut
    # 3.7 limitation only when the identical pytest invocation, on mutmut's own
    # instrumented tree, passes OUT of process — i.e. the tests and the mutants are
    # fine and only mutmut's in-process tracer breaks (seen with modules that do
    # work at import time, e.g. `settings = get_settings()`: conftest then fails
    # to import under the tracer with FileNotFoundError '<frozen importlib._bootstrap>').
    # The original pytest error is in mutmut's output above (debug = true).
    if grep -q "BadTestExecutionCommandsException" "$WORKDIR/mutmut.log"; then
      if [ -d "$WORKDIR/mutants" ] && (cd "$WORKDIR/mutants" && "$VENV_PY" -m pytest -q "${TESTFILES[@]}" \
          --rootdir=. -p no:randomly -p no:random-order -p no:xdist \
          -o 'addopts=-m "not composio and not model_onboarding and not schemathesis" --strict-markers --timeout=300' \
          > "$WORKDIR/mutants-tree-check.log" 2>&1); then
        echo "SKIP: $MODULE — the same pytest run passes on mutmut's instrumented tree"
        echo "      out of process, but fails inside mutmut's in-process stats tracer"
        echo "      (see the pytest error in mutmut's output above). Import-time work in"
        echo "      the module trips the tracer — a documented mutmut 3.7 limitation."
        exit 0
      fi
      echo "REAL FAILURE: mutmut could not run ${TESTFILES[*]} (pytest usage/collection error)" >&2
      echo "  and the same run also fails on the instrumented tree out of process — see" >&2
      echo "  mutmut's output above and $WORKDIR/mutants-tree-check.log." >&2
      exit 1
    fi
    # A nonzero exit AFTER the mutants ran is usually the loguru teardown
    # crash (forked children + the app's loop-bound redis client write to a
    # closed stream at interpreter shutdown) — the verdict below is the
    # source of truth, and an incomplete run is caught by the not-checked
    # check. Fail only if mutmut produced nothing at all.
    # mutmut's trampoline resolves the CALLER frame with
    # Path(filename).resolve(strict=True). A module that calls one of its own
    # mutated functions at import time is entered from <frozen
    # importlib._bootstrap>, which is not a real path, so the stats phase dies
    # before a single test runs. Same class of tool limitation as the two above —
    # the module's own tests pass normally — so skip with a reason rather than
    # reporting a test weakness that is not there.
    if grep -q "No such file or directory: '<frozen importlib._bootstrap>'" "$WORKDIR/mutmut.log"; then
      echo "SKIP: $MODULE — mutmut cannot collect stats for a module that invokes its" >&2
      echo "      own function at import time: the trampoline resolves the calling" >&2
      echo "      frame, which during import is <frozen importlib._bootstrap>." >&2
      exit 0
    fi
    if [ ! -f "$WORKDIR/mutants/mutmut-stats.json" ]; then
      echo "MUTATION RUN FAILED (no state produced) — see mutmut's output above." >&2
      exit 1
    fi
  fi

  # Only two of mutmut's statuses are a VERDICT: killed (the suite caught the
  # bug) and survived (it did not). Everything else — suspicious, no tests,
  # timeout, skipped, not checked — means no verdict was reached, which is not
  # the same thing as no failure. "not checked" mutants mean the run was
  # interrupted; that IS a failure (incomplete evidence). Survivors are then
  # classified: cast()-arg changes are provably equivalent (typing.cast returns
  # its argument unchanged at runtime), so are falsy .get() defaults nothing
  # but a truthiness test consumes (see _unobservable_get_default), and — the
  # diff-driven gate — survivors on lines the PR did not change are noted,
  # not failures.
  #
  # `results --all True` lists EVERY mutant with its status, one line each;
  # plain `results` omits the killed ones, and whether anything was killed at
  # all is exactly what says the run proved something. Its failure is NOT
  # swallowed: an unreadable read used to be indistinguishable from a clean
  # run, which is the same silence-read-as-success bug the no-verdict guard
  # below exists to stop.
  _phase "collect results"
  if ! RESULTS="$("$VENV_PY" -m mutmut results --all True 2>"$WORKDIR/results-err.log")"; then
    echo "MUTATION RESULTS UNREADABLE — 'mutmut results' failed for $MODULE:" >&2
    cat "$WORKDIR/results-err.log" >&2
    exit 1
  fi
  # Anchored on the status suffix: with killed mutants now in the listing, a
  # bare substring match would miscount any mutant whose own name contains a
  # status word.
  TOTAL="$(printf '%s\n' "$RESULTS" | grep -c . || true)"
  KILLED="$(printf '%s\n' "$RESULTS" | grep -c ": killed$" || true)"
  SUSPICIOUS="$(printf '%s\n' "$RESULTS" | grep -c ": suspicious$" || true)"
  SURVIVORS="$(printf '%s\n' "$RESULTS" | grep ": survived$" || true)"
  SURVIVED="$(printf '%s\n' "$SURVIVORS" | grep -c . || true)"
  NO_TESTS_LIST="$(printf '%s\n' "$RESULTS" | grep ": no tests$" || true)"
  NO_TESTS="$(printf '%s\n' "$NO_TESTS_LIST" | grep -c . || true)"
  NOT_CHECKED="$(printf '%s\n' "$RESULTS" | grep -c ": not checked$" || true)"
  TIMEOUT="$(printf '%s\n' "$RESULTS" | grep -c ": timeout$" || true)"
  SEGFAULT="$(printf '%s\n' "$RESULTS" | grep -c ": segfault$" || true)"
  SKIPPED="$(printf '%s\n' "$RESULTS" | grep -c ": skipped$" || true)"
  TYPECHECK="$(printf '%s\n' "$RESULTS" | grep -c ": caught by type check$" || true)"
  # NOTHING came back. Every guard below needs TOTAL > 0 to fire, so a run that
  # produced no results at all used to fall straight through them and print
  # "Mutation: OK" — a module reported as proven by a mutmut that never ran.
  # That is not hypothetical: a stray double quote in a comment inside the
  # bash-quoted python child truncated the program, so the child exited 0 having
  # printed nothing, and every module in the lane reported OK for a day.
  #
  # Keyed on the three facts together — no results, an empty log, no mutants
  # tree — so that this cannot swallow the legitimate zero-mutant case below,
  # where mutmut ran, said so, and simply found nothing to mutate.
  if [ "${TOTAL:-0}" -eq 0 ] && [ ! -s "$WORKDIR/mutmut.log" ] && [ ! -d "$WORKDIR/mutants" ]; then
    echo "MUTATION RUN PRODUCED NO RESULTS — the mutmut child did not run." >&2
    echo "  No results, an empty mutmut.log, and no mutants/ tree: nothing was" >&2
    echo "  mutated and nothing was proven about $MODULE. Reporting this as OK is" >&2
    echo "  the false green this guard exists to stop. Check the mutmut invocation" >&2
    echo "  itself (its python program is a bash-quoted string — an unescaped \" or" >&2
    echo "  \$ inside it truncates the program and the child exits 0 in silence)." >&2
    _write_record error "mutmut produced no results — the child did not run" /dev/null /dev/null
    exit 1
  fi
  if [ "${TOTAL:-0}" -eq 0 ]; then
    echo "SKIP: $MODULE — mutmut ran and generated no mutants on the changed lines." >&2
    echo "      Nothing was proven here either way; it is not a pass." >&2
    _write_record skip "mutmut generated no mutants on the changed lines of $MODULE" \
      /dev/null /dev/null
    exit 0
  fi
  if [ "${NOT_CHECKED:-0}" -gt 0 ]; then
    echo "MUTATION RUN INCOMPLETE — $NOT_CHECKED mutant(s) were never checked;" >&2
    echo "the run was interrupted. See mutmut's output above." >&2
    exit 1
  fi
  # A crashed child proves nothing, and a status outside every counted bucket
  # is the same silence-read-as-success this gate exists to stop. Seen live:
  # 371 mutants segfaulted in a fork-unsafe macOS proxy lookup, mutmut's
  # progress line has no slot for the segfault status, and the verdict below
  # then read "no survivors" off a run that graded barely half the mutants.
  ACCOUNTED=$((KILLED + SURVIVED + SUSPICIOUS + NO_TESTS + NOT_CHECKED + TIMEOUT + SEGFAULT + SKIPPED + TYPECHECK))
  if [ "${SEGFAULT:-0}" -gt 0 ] || [ "$((TOTAL - ACCOUNTED))" -ne 0 ]; then
    echo "MUTATION RUN INCOMPLETE — $SEGFAULT segfault(s) and $((TOTAL - ACCOUNTED)) unbucketed" >&2
    echo "mutant(s) of $TOTAL reached NO verdict. A crashed or uncounted child" >&2
    echo "proves nothing; fix the crash (on macOS see the NO_PROXY note in" >&2
    echo "tests/conftest.py) and re-run." >&2
    exit 1
  fi
  if [ "${SUSPICIOUS:-0}" -gt 0 ]; then
    echo "NOTE: $SUSPICIOUS of $TOTAL mutant(s) came back 'suspicious' — mutmut's" >&2
    echo "      bucket for a test process that exited in none of the ways it knows" >&2
    echo "      how to read. A suspicious mutant proves NOTHING: it was neither" >&2
    echo "      killed nor shown to survive. Do not read this count as good or bad." >&2
    echo "      It is NOT a timeout — mutmut buckets those separately, and does so" >&2
    echo "      correctly. The cause is the forked child dying on SIGTRAP (exit" >&2
    echo "      code -5) before writing a byte, when the test file is re-run inside" >&2
    echo "      the fork. Reproducible without mutmut: fork at pytest_sessionfinish" >&2
    echo "      and call pytest.main() on the same file — the bare fork is clean," >&2
    echo "      the re-run is what dies." >&2
    echo "" >&2
    echo "      The fork-hostile dependency is chromadb: constructing a client" >&2
    echo "      (chromadb.EphemeralClient()) is enough, importing it is not, and" >&2
    echo "      chromadb 1.x runs a Rust/tokio core that does not survive fork()." >&2
    echo "      Bisected with a three-way probe (no import / import / construct):" >&2
    echo "      only the construct case dies. Any test file that builds a chroma" >&2
    echo "      client makes every mutant of its module unreadable this way." >&2
  fi
  # The no-verdict guard. Reaching zero survivors because every mutant was
  # killed and reaching it because no mutant reached a verdict at all are
  # opposite outcomes, and the old check — which counted only survivors — could
  # not tell them apart. Observed on app/override/langgraph_bigtool/create_agent.py
  # against tests/integration/agents/test_harness_completion.py: 210 mutants,
  # 0 killed, 0 survived, 210 suspicious, and the gate printed OK with rc=0.
  # The one carve-out from the guard below: mutmut cannot grade ANY module whose
  # tests build a chromadb client, because it re-runs the test file inside a fork
  # and that client's Rust core dies there (see the NOTE above). Keyed on the full
  # signature — every mutant suspicious AND the child's -5 exit in the log — so a
  # genuinely weak suite still fails loudly. Same treatment as the two other
  # documented mutmut limitations handled earlier in this script.
  # Deliberately keyed on "no mutant reached a verdict" + the fork-crash exit
  # codes, NOT on mutmut's bucket name: the same fork failure lands in different
  # buckets per platform (suspicious on macOS, timeout on Linux), and keying on
  # the name is what made the first version of this miss CI entirely.
  if [ "${TOTAL:-0}" -gt 0 ] && [ "${KILLED:-0}" -eq 0 ] && [ "${SURVIVED:-0}" -eq 0 ] &&
     grep -qE "worker exit code (-5|-24)" "$WORKDIR/mutmut.log" 2>/dev/null; then
    echo "MUTATION SKIPPED — $MODULE was NOT graded." >&2
    echo "  All $TOTAL mutant(s) died in the fork, not in a test: the test set for" >&2
    echo "  this module builds a chromadb client, whose Rust core cannot survive" >&2
    echo "  fork(), and mutmut re-runs the file inside one. This is a tool limit," >&2
    echo "  not a test weakness — the module's own tests pass normally." >&2
    echo "  Two manifestations of the one cause, both matched here:" >&2
    echo "    macOS — child crashes on SIGTRAP, worker exit -5, bucket 'suspicious'" >&2
    echo "    Linux — child deadlocks, killed on CPU limit, exit -24, bucket 'timeout'" >&2
    echo "  Buckets seen: $SUSPICIOUS suspicious, $TIMEOUT timeout, of $TOTAL." >&2
    exit 0
  fi
  if [ "${KILLED:-0}" -eq 0 ] && [ "${SURVIVED:-0}" -eq 0 ] && [ "${TOTAL:-0}" -gt 0 ]; then
    echo "MUTATION PROVED NOTHING — all $TOTAL mutant(s) of $MODULE ran and not one" >&2
    echo "was killed or survived, so the suite was never shown to catch OR miss a" >&2
    echo "bug here. Buckets: $SUSPICIOUS suspicious, $NO_TESTS no tests," >&2
    echo "$((TOTAL - SUSPICIOUS - NO_TESTS)) other. Passing this as OK is the false" >&2
    echo "green this guard exists to stop — fix the run or pick a test file that" >&2
    echo "actually exercises the module." >&2
    exit 1
  fi
  REAL_SURVIVORS=""
  EQUIVALENT=""
  UNCHANGED=""
  LOGGING=""
  # One row per survivor — name, mutmut's status, the classifier's verdict
  # (CHANGED:<line> / LOGGING:<line> / UNCHANGED:<line> / EQUIV) — for
  # lib/mutation_report.py to turn into verdict.json. The line number is the
  # classifier's, resolved against the REAL module, and it is the whole reason
  # survivors can be grouped by source line instead of listed by mutant id.
  RECORDS="$WORKDIR/survivor-records.tsv"
  : > "$RECORDS"
  _phase "classify survivors"
  if [ -n "$SURVIVORS" ]; then
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      # The classifier exits 1 for a verdict the lane must act on and 0 for
      # EQUIV, so set -e would kill the gate mid-classification: capture the
      # status instead of swallowing it. An unrecognised verdict is a classifier
      # failure and fails the lane below — a mutant that quietly leaves every
      # bucket is the same silence-read-as-success this gate exists to stop.
      CLASSIFIER_RC=0
      VERDICT="$("$VENV_PY" "$CLASSIFIER" "$line" "$WORKDIR" "$CHANGED_RANGES" "$MODULE")" || CLASSIFIER_RC=$?
      case "$VERDICT" in
        EQUIV)
          EQUIVALENT="$EQUIVALENT
  $line" ;;
        CHANGED:*)
          REAL_SURVIVORS="$REAL_SURVIVORS
  $line" ;;
        UNCHANGED:*)
          UNCHANGED="$UNCHANGED
  $line" ;;
        LOGGING:*)
          LOGGING="$LOGGING
  $line" ;;
        *)
          echo "MUTATION CLASSIFIER FAILED on: $line" >&2
          echo "  exit=$CLASSIFIER_RC verdict='$VERDICT'" >&2
          echo "  A survivor with no verdict must not vanish from every bucket." >&2
          echo "  Re-run: $VENV_PY $CLASSIFIER '$line' '$WORKDIR' '$CHANGED_RANGES' '$MODULE'" >&2
          exit 1 ;;
      esac
      SURVIVOR_NAME="${line#"${line%%[![:space:]]*}"}"
      printf '%s\t%s\t%s\n' "${SURVIVOR_NAME%%:*}" "survived" "$VERDICT" >> "$RECORDS"
    done <<< "$SURVIVORS"
  fi
  NO_TESTS_CHANGED=""
  if [ -n "$NO_TESTS_LIST" ]; then
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      CLASSIFIER_RC=0
      VERDICT="$("$VENV_PY" "$CLASSIFIER" "$line" "$WORKDIR" "$CHANGED_RANGES" "$MODULE")" || CLASSIFIER_RC=$?
      case "$VERDICT" in
        CHANGED:*)
          NO_TESTS_CHANGED="$NO_TESTS_CHANGED
  $line" ;;
        UNCHANGED:*|LOGGING:*|EQUIV) ;;
        *)
          echo "MUTATION CLASSIFIER FAILED on: $line" >&2
          echo "  exit=$CLASSIFIER_RC verdict='$VERDICT'" >&2
          echo "  A survivor with no verdict must not vanish from every bucket." >&2
          echo "  Re-run: $VENV_PY $CLASSIFIER '$line' '$WORKDIR' '$CHANGED_RANGES' '$MODULE'" >&2
          exit 1 ;;
      esac
    done <<< "$NO_TESTS_LIST"
  fi
  if [ -n "$NO_TESTS_CHANGED" ]; then
    NO_TESTS_CHANGED_COUNT=$(printf '%s\n' "$NO_TESTS_CHANGED" | grep -c . || true)
    echo "NOTE: $NO_TESTS_CHANGED_COUNT mutant(s) ON CHANGED LINES have NO covering test." >&2
    echo "      Not survivors, and not a pass either: nothing exercises them, so this" >&2
    echo "      lane can say nothing about that code. A changed line landing here is a" >&2
    echo "      coverage hole wearing a clean result. Printed before the verdict" >&2
    echo "      because a FAILING run is when it is easiest to miss:" >&2
    echo "$NO_TESTS_CHANGED" >&2
  fi
  if [ "${NO_TESTS:-0}" -gt 0 ]; then
    echo "NOTE: $NO_TESTS mutant(s) had no covering test across the WHOLE module" >&2
    echo "      (the line above is the subset on changed lines, which is the one" >&2
    echo "      this PR owns; generation is scoped to a changed line's NODE, so a" >&2
    echo "      multi-line statement contributes its untouched lines too)." >&2
  fi
  if [ -n "$UNCHANGED" ]; then
    echo "NOTE: survivor(s) on lines the PR did not touch (diff-driven gate):" >&2
    echo "$UNCHANGED" >&2
  fi
  if [ -n "$EQUIVALENT" ]; then
    echo "NOTE: provably equivalent mutant(s) — a cast() type argument (a runtime" >&2
    echo "      no-op by typing.cast contract), or a falsy .get() default that only" >&2
    echo "      ever reaches a truthiness test ('x or y', 'if x:', 'x if x else y'," >&2
    echo "      or code such a test guards), where every falsy value takes the same" >&2
    echo "      branch. Truthy defaults are NOT covered: d.get(k, 1) or 0 really" >&2
    echo "      does return 1 when the key is missing. Two further one-offs:" >&2
    echo "      json.dumps' ensure_ascii, which json documents as a truth value," >&2
    echo "      and a case-ONLY rewrite of a header name in an x.headers.get()" >&2
    echo "      lookup, which every .headers mapping resolves case-insensitively" >&2
    echo "      (RFC 9110 5.1); asking for a DIFFERENT header still fails." >&2
    echo "      Also the argument of a Starlette call_next(): BaseHTTPMiddleware" >&2
    echo "      closes over the request's own scope/receive/send and never reads" >&2
    echo "      that parameter, so call_next(None) is the same program." >&2
    echo "$EQUIVALENT" >&2
  fi
  if [ -n "$LOGGING" ]; then
    LOGGING_COUNT=$(printf '%s\n' "$LOGGING" | grep -c . || true)
    echo "NOTE: $LOGGING_COUNT mutant(s) excluded as logging-only — the mutation lands" >&2
    echo "      inside a log.debug/log.info call, the only two levels that never reach" >&2
    echo "      the wide event (wide_events.py: they emit a loguru line and stop, while" >&2
    echo "      warning/error/critical/exception _append msg AND kwargs to" >&2
    echo "      warnings[]/errors[], where a test can and should assert them). Counted" >&2
    echo "      only for mutants on lines the PR changed, and printed before the" >&2
    echo "      verdict so an exclusion is never invisible, including on a failing run:" >&2
    echo "$LOGGING" >&2
  fi
  # Every survivor's diff, uncapped. The old cap was 40, which on a real run
  # left 39 survivors carrying a name and nothing else — and a mutant id with no
  # diff is not actionable, since the numbering depends on the diff scope and
  # cannot be regenerated locally. A survivor's diff is ~12 lines: even a
  # hundred of them is noise-free next to the 190k-line log they sit in.
  # `mutmut show` is the same call the log already made, so this costs nothing
  # extra per mutant; its output is captured to a file because it is also what
  # the structured verdict and `replay` read.
  SURVIVOR_DIFFS="$WORKDIR/survivor-diffs.txt"
  : > "$SURVIVOR_DIFFS"
  if [ -n "$REAL_SURVIVORS" ]; then
    _phase "collect survivor diffs"
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      name="${line#"${line%%[![:space:]]*}"}"
      name="${name%: survived}"
      "$VENV_PY" -m mutmut show "$name" >> "$SURVIVOR_DIFFS" 2>&1 ||
        echo "  (diff of $name unavailable)" >&2
    done <<< "$REAL_SURVIVORS"
    cat "$SURVIVOR_DIFFS" >&2
  fi

  # The lane verdict + the grouped human report. Written on the passing path
  # too: "this module was checked and came back clean" is a fact the gate must
  # read, not an absence it has to infer.
  MODULE_STATUS=pass
  [ -n "$REAL_SURVIVORS" ] && MODULE_STATUS=survivors
  _write_record "$MODULE_STATUS" "" "$RECORDS" "$SURVIVOR_DIFFS"

  if [ -n "$REAL_SURVIVORS" ]; then
    exit 1
  fi
  echo "Mutation: OK — no survivors on changed lines in $MODULE"
}

# Reproduce ONE survivor on this machine: apply its recorded diff to a scratch
# copy of apps/api and run the module's mapped tests there. Nothing under the
# working tree is written — the copy is the whole point, and the replay checks
# `git status --porcelain` before and after to prove it.
cmd_replay() {
  local source="${1:-}" selector="${2:-}"
  if [ -z "$source" ] || [ -z "$selector" ]; then
    echo "usage: mutation.sh replay <verdict.json|shard.log> <mutant-id|file.py:LINE>" >&2
    exit 2
  fi
  local venv_py
  venv_py="$(_venv_python)" || exit 1
  "$venv_py" "$SCRIPT_DIR/lib/mutation_report.py" replay "$source" "$selector" \
    --repo-root "$REPO_ROOT" --api-root "$REPO_ROOT/apps/api" --python "$venv_py"
}

usage() {
  sed -n '2,41p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    matrix) cmd_matrix "$@" ;;
    plan)   cmd_plan "$@" ;;
    shard)  cmd_shard "$@" ;;
    module) cmd_module "$@" ;;
    local)  cmd_local "$@" ;;
    replay) cmd_replay "$@" ;;
    *)
      echo "mutation.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
