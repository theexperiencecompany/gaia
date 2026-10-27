#!/usr/bin/env bash
# runner-host.sh — "is this job on the home box?", the one answer every script uses.
#
#   ci_on_the_box   succeeds on a home-box runner, fails anywhere else.
#
# The box's runners are named gaia-home-<n> (gaia-infra:self-hosted-runner/
# setup.sh RUNNER_NAME_PREFIX), so the runner name is the signal. Never the
# runner kind: Blacksmith overflow runners report self-hosted too, and every
# box-only assumption keyed on it (persistent workspace, shared services,
# setup.sh-installed tools) broke there. Workflow expressions spell the same
# test as startsWith(runner.name, 'gaia-home-').
#
# Sourced, never executed: it defines a constant and a function, nothing else.

GAIA_BOX_RUNNER_PREFIX="gaia-home-"

ci_on_the_box() { [[ "${RUNNER_NAME:-}" == "${GAIA_BOX_RUNNER_PREFIX}"* ]]; }
