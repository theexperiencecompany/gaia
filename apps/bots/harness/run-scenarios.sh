#!/usr/bin/env bash
# Plays every scenario in scenarios/ against a running sim stack, one after another
# (they share the platform's bot queues), and fails if any scenario fails. Each
# scenario's transcript and bot log land in test-results/<name>.{jsonl,log}; the
# console gets its PASS/FAIL verdict and the failed assertions.
#
# --shard=<current>/<total> plays one contiguous slice of the sorted scenarios, sized
# the way Playwright's --shard sizes its shards (the remainder goes to the first
# ones), so CI can spread them over several stacks. A shard left empty passes.
set -uo pipefail

cd "$(dirname "$0")" || exit 1

shard_current=1
shard_total=1
for arg in "$@"; do
  case "$arg" in
    --shard=*/*)
      shard_current="${arg#--shard=}"
      shard_current="${shard_current%/*}"
      shard_total="${arg#*/}"
      ;;
    *)
      echo "usage: run-scenarios.sh [--shard=<current>/<total>]" >&2
      exit 2
      ;;
  esac
done
if ! [[ "$shard_current" =~ ^[1-9][0-9]*$ && "$shard_total" =~ ^[1-9][0-9]*$ ]] ||
  ((shard_current > shard_total)); then
  echo "run-scenarios.sh: --shard must be <current>/<total> with 1 <= current <= total" >&2
  exit 2
fi

shopt -s nullglob
all=(scenarios/*.yaml)
if ((${#all[@]} == 0)); then
  echo "run-scenarios.sh: no scenarios in scenarios/" >&2
  exit 1
fi
size=$((${#all[@]} / shard_total))
remainder=$((${#all[@]} % shard_total))
from=$(((shard_current - 1) * size + (shard_current - 1 < remainder ? shard_current - 1 : remainder)))
count=$((size + (shard_current - 1 < remainder ? 1 : 0)))
echo "shard $shard_current/$shard_total: $count of ${#all[@]} scenarios"
((count > 0)) || exit 0
mine=("${all[@]:from:count}")

mkdir -p test-results
failed=()
for scenario in "${mine[@]}"; do
  name="$(basename "$scenario" .yaml)"
  started=$SECONDS
  pnpm tsx src/cli.ts run "$scenario" --out "test-results/$name.jsonl" > /dev/null 2> "test-results/$name.log"
  code=$?
  echo "$name: $((SECONDS - started))s"
  grep -E '^(PASS|FAIL|  - |gaia-sim failed)' "test-results/$name.log"
  ((code == 0)) || failed+=("$name")
done
if ((${#failed[@]} > 0)); then
  echo "failed scenarios: ${failed[*]}" >&2
  exit 1
fi
