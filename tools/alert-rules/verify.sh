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
# The tool versions are tools/alert-rules/tool-versions.env, what production
# runs. CI runs this script with the pinned binaries installed; elsewhere it
# runs the same versions' images, so it works on a machine without them.
#
# Usage:
#   tools/alert-rules/verify.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# shellcheck source=tools/alert-rules/tool-versions.env
source tools/alert-rules/tool-versions.env

# The binary on PATH when there is one (CI installs the pinned release with
# `scripts/ci/audit.sh alert-rule-tools`), else the same version's image.
run_tool() {
  local tool="$1"
  shift
  if type -P "$tool" >/dev/null; then
    "$tool" "$@"
    return
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "error: $tool is not on PATH and docker is not available to run its image" >&2
    exit 1
  fi
  case "$tool" in
    pint) docker run --rm -v "$PWD:/work" -w /work "ghcr.io/cloudflare/pint:$PINT_VERSION" pint "$@" ;;
    promtool) docker run --rm --entrypoint promtool -v "$PWD:/work" -w /work "prom/prometheus:v$PROMETHEUS_VERSION" "$@" ;;
  esac
}

RULES="tools/alert-rules/gaia-rules.yaml"
TESTS="tools/alert-rules/tests"

# --test-dir makes the extractor fail if any rule has no test file (or any test
# file has no rule), so a rule that "provisions cleanly and never fires" can no
# longer ship quietly. --no-build forbids building sdist deps from source (the
# pinned pyyaml wheel is all this script needs).
uv run --no-build tools/alert-rules/extract_promql.py -o "$RULES" --test-dir "$TESTS"
echo "extracted + coverage-checked -> $RULES"

echo "==> pint (offline checks)"
run_tool pint --no-color --offline --config config/pint.hcl lint "$RULES"

echo "==> promtool check rules"
run_tool promtool check rules "$RULES"

echo "==> promtool test rules"
# rule_files inside each test is relative to the test file, so paths stay repo-relative.
test_files=("$TESTS"/*.yaml)
run_tool promtool test rules "${test_files[@]}"

echo "OK: all ${#test_files[@]} alert-rule test files pass"
