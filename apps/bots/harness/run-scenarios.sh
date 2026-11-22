#!/usr/bin/env bash
# Plays every scenario in scenarios/ against a running sim stack, one after another
# (they share the platform's bot queues), and fails if any scenario fails. Each
# scenario's transcript and bot log land in test-results/<name>.{jsonl,log}; the
# console gets its PASS/FAIL verdict and the failed assertions.
set -uo pipefail

cd "$(dirname "$0")"
mkdir -p test-results
failed=()
for scenario in scenarios/*.yaml; do
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
