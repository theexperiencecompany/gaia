#!/usr/bin/env bash
# Run one shard of the mutation lane: every module in $GROUP, in order.
#
# A shard is normally ONE module — mutation-plan.sh only packs several together
# when a diff has more modules than a GitHub matrix can hold. Every module in
# the group runs even after one fails, because the gate's value is the complete
# list; the shard's exit code is the worst of them.
#
# $GROUP is a compact JSON array of {module, testfiles, ranges}, exactly the
# shape mutation.sh already parses its own two list arguments from.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

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

rc=0
failed_modules=()
while IFS=$'\t' read -r module testfiles ranges; do
  [ -n "$module" ] || continue
  echo "=== $module ===" >> shard.log
  # timeout(1) bounds a genuine mutmut hang from OUTSIDE the script: bash defers
  # traps while waiting on a foreground child, so an in-script watchdog can
  # never fire. 1500s is ~25x the slowest module measured.
  module_rc=0
  timeout --signal=KILL 1500 \
    bash scripts/test/mutation.sh "$module" "$testfiles" "${ranges:-[]}" \
    >> shard.log 2>&1 || module_rc=$?
  if [ "$module_rc" = "137" ] || [ "$module_rc" = "124" ]; then
    echo "::error::mutation for $module exceeded its timeout and was killed — see the log for the last phase reached"
  fi
  if [ "$module_rc" != "0" ]; then
    rc="$module_rc"
    failed_modules+=("$module")
  fi
done < "$SHARD_TSV"

# tail, NEVER cat: with mutmut's debug output on, a busy module writes a 13MB
# shard.log, and feeding that through the runner's live-log pipe is where this
# step used to freeze — the write blocks forever somewhere past ~13MB, and a
# process frozen mid-syscall on the step's own log pipe cannot be killed by the
# step abort, so the job died at its cap and GitHub destroyed the logs that
# proved it. The full file ships as the artifact.
echo "--- shard.log (last 200KB; full file in the artifact) ---"
tail -c 200000 shard.log

# The verdict, last and on its own. A shard carries several modules when the
# diff is large, so "this check is red" has to say WHICH — otherwise the only
# way to find out is scrolling a 200KB tail.
if [ "${#failed_modules[@]}" -eq 0 ]; then
  echo "Mutation shard OK — every module clean"
else
  echo "::error::mutation failed for: ${failed_modules[*]}"
  {
    echo "### Mutation failures"
    echo
    for module in "${failed_modules[@]}"; do echo "- \`$module\`"; done
  } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
fi

exit "$rc"
