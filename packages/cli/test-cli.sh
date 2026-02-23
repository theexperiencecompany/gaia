#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLI_ENTRY="$ROOT_DIR/packages/cli/dist/index.js"
PACKAGE_JSON="$ROOT_DIR/packages/cli/package.json"

if [[ ! -f "$CLI_ENTRY" ]]; then
  echo "Missing built CLI at $CLI_ENTRY"
  echo "Run: pnpm -C packages/cli build"
  exit 1
fi

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"

  if [[ "$haystack" != *"$needle"* ]]; then
    echo "Assertion failed: $message"
    echo "Expected to find: $needle"
    exit 1
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"

  if [[ "$haystack" == *"$needle"* ]]; then
    echo "Assertion failed: $message"
    echo "Did not expect to find: $needle"
    exit 1
  fi
}

PACKAGE_VERSION="$(node -e "console.log(require(process.argv[1]).version)" "$PACKAGE_JSON")"
CLI_VERSION="$(node "$CLI_ENTRY" --version)"

assert_contains "$CLI_VERSION" "$PACKAGE_VERSION" "CLI version should match package.json version"
echo "Version check passed: $CLI_VERSION"

HELP_OUTPUT="$(node "$CLI_ENTRY" --help)"
assert_contains "$HELP_OUTPUT" "dev [profile]" "help should list dev command"
assert_contains "$HELP_OUTPUT" "logs" "help should list logs command"
assert_contains "$HELP_OUTPUT" "stop" "help should list stop command"
echo "Global help check passed"

STOP_HELP_OUTPUT="$(node "$CLI_ENTRY" stop --help)"
assert_contains "$STOP_HELP_OUTPUT" "--force-ports" "stop help should include --force-ports"
echo "Stop help check passed"

set +e
INVALID_PROFILE_OUTPUT="$(node "$CLI_ENTRY" dev wrong-profile 2>&1)"
INVALID_PROFILE_EXIT="$?"
set -e
if [[ "$INVALID_PROFILE_EXIT" -eq 0 ]]; then
  echo "Expected non-zero exit for invalid dev profile"
  exit 1
fi
assert_contains "$INVALID_PROFILE_OUTPUT" "Invalid developer profile" "invalid profile should be rejected"
echo "Invalid dev profile check passed"

set +e
FULL_PROFILE_OUTPUT="$(node "$CLI_ENTRY" dev full 2>&1)"
FULL_PROFILE_EXIT="$?"
set -e
if [[ "$FULL_PROFILE_EXIT" -eq 0 ]]; then
  echo "Expected non-zero exit for dev full outside a GAIA repo"
  exit 1
fi
assert_not_contains "$FULL_PROFILE_OUTPUT" "Invalid developer profile" "dev full should be accepted as a valid profile"
echo "Dev full profile routing check passed"

echo "CLI smoke tests passed"
