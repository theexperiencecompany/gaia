#!/usr/bin/env bash
set -euo pipefail

# Verify every Grafana alert rule the way CI does, in one command:
#
#   1. extract the Grafana A/B/C rules into Prometheus-native YAML, enforcing
#      that every rule has a promtool test file (--test-dir)
#   2. lint the extracted rules with pint (offline checks)
#   3. validate the extracted rule file with promtool check rules
#   4. prove every rule fires and stays quiet with promtool test rules
#
# The tool versions match what production and CI use. CI installs pint and
# promtool with `go install` and runs the identical commands; this script uses
# the same images so it works on a machine without a Go toolchain.
#
# Usage:
#   tools/alert-rules/verify.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if ! command -v docker >/dev/null 2>&1; then
  echo "error: docker is required for the pint/promtool stages of this script" >&2
  echo "       (CI installs the same tool versions with 'go install' instead)" >&2
  exit 1
fi

PINT_IMAGE="ghcr.io/cloudflare/pint:0.87.0"
PROMETHEUS_IMAGE="prom/prometheus:v3.1.0"

RULES="tools/alert-rules/gaia-rules.yaml"
TESTS="tools/alert-rules/tests"

# --test-dir makes the extractor fail if any rule has no test file (or any test
# file has no rule), so a rule that "provisions cleanly and never fires" can no
# longer ship quietly. --no-build forbids building sdist deps from source (the
# pinned pyyaml wheel is all this script needs).
uv run --no-build tools/alert-rules/extract_promql.py -o "$RULES" --test-dir "$TESTS"
echo "extracted + coverage-checked -> $RULES"

echo "==> pint (offline checks)"
docker run --rm -v "$PWD:/work" -w /work "$PINT_IMAGE" pint \
  --no-color --offline --config /work/config/pint.hcl lint "/work/$RULES"

echo "==> promtool check rules"
docker run --rm --entrypoint promtool -v "$PWD:/work" -w /work "$PROMETHEUS_IMAGE" \
  check rules "$RULES"

echo "==> promtool test rules"
# Expand on the host and remap to the container path; promtool takes explicit
# file arguments, and rule_files inside each test is relative to the test file.
test_args=()
for test_file in "$TESTS"/*.yaml; do
  test_args+=("/work/$test_file")
done
docker run --rm --entrypoint promtool -v "$PWD:/work" -w /work "$PROMETHEUS_IMAGE" \
  test rules "${test_args[@]}"

echo "OK: all ${#test_args[@]} alert-rule test files pass"
