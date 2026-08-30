#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["defusedxml==0.7.1"]
# ///
"""Decide whether a regression-proof run actually proved anything.

Reads the JUnit XML of the base-revision run (see scripts/ci/pytest.sh regression-proof)
and applies one rule per `@pytest.mark.regression` test:

    it must FAIL — an assertion that goes red without the fix.

PASSED is the obvious rejection: a test green on base does not pin the bug it
claims to. ERROR-only is rejected too, and that is the subtler half. An error is
a test that never reached its assertions — a missing fixture, an import of a
symbol the base does not have, a service that would not start. It looks like
proof in a summary line ("did not pass") while proving nothing about the bug,
which is exactly how this gate spent its life reporting success it had not
earned. A test that both fails and then errors in teardown is fine: the
assertion still ran.

Usage:
    uv run --no-project scripts/ci/regression_proof_verdict.py <junit.xml>
"""

from __future__ import annotations

from collections import defaultdict
import sys

from defusedxml.ElementTree import parse as parse_xml


def main() -> int:
    """Exit 0 when every regression test failed on base, 1 otherwise."""
    if len(sys.argv) != 2:
        print("usage: regression_proof_verdict.py <junit.xml>", file=sys.stderr)
        return 2
    try:
        root = parse_xml(sys.argv[1]).getroot()
    except OSError as exc:
        print(f"ERROR: regression-proof — cannot read the JUnit report: {exc}", file=sys.stderr)
        return 1

    # One test can emit several <testcase> entries (call + teardown), so fold
    # them together and ask what happened across all of them.
    failed: dict[str, bool] = defaultdict(bool)
    errored: dict[str, bool] = defaultdict(bool)
    for case in root.iter("testcase"):
        name = f"{case.get('classname', '')}::{case.get('name', '')}".lstrip(":")
        failed[name] |= case.find("failure") is not None
        errored[name] |= case.find("error") is not None

    if not failed:
        print("ERROR: regression-proof — the JUnit report lists no tests at all.")
        print("       The run did not execute; that is a failure, not a pass.")
        return 1

    passed_on_base = sorted(n for n in failed if not failed[n] and not errored[n])
    errored_only = sorted(n for n in failed if errored[n] and not failed[n])
    proven = sorted(n for n in failed if failed[n])

    if passed_on_base:
        print(f"ERROR: regression-proof — {len(passed_on_base)} test(s) PASS on base:")
        for name in passed_on_base:
            print(f"  {name}")
        print("       A regression test must go red without its fix. Either the fix is")
        print("       not needed, or the test does not exercise the bug it names.")
        return 1

    if errored_only:
        print(f"ERROR: regression-proof — {len(errored_only)} test(s) ERRORED on base:")
        for name in errored_only:
            print(f"  {name}")
        print("       An error is not proof: the test never reached its assertions, so")
        print("       it shows the harness broke, not that the bug is caught. Make it")
        print("       runnable against the base revision — assert on behavior rather")
        print("       than importing symbols the fix introduces.")
        return 1

    print(f"regression-proof: {len(proven)} regression test(s) fail on base as required")
    for name in proven:
        print(f"  FAILED {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
