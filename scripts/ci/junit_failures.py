#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["defusedxml==0.7.1"]
# ///
"""Print a failing-test summary from a pytest JUnit XML file.

Usage:
    uv run scripts/ci/junit_failures.py [--passed] path/to/pytest.xml

Default prints `module::test` lines for failed/error cases plus counts.
`--passed` prints passed cases instead (used by the regression-proof job to
name the tests that pass on base).
"""

from __future__ import annotations

import sys

from defusedxml.ElementTree import parse as parse_xml


def main() -> int:
    args = sys.argv[1:]
    passed_only = "--passed" in args
    args = [a for a in args if a != "--passed"]
    if not args:
        print("usage: junit_failures.py [--passed] <junit.xml>", file=sys.stderr)
        return 2
    path = args[0]
    try:
        root = parse_xml(path).getroot()
    except FileNotFoundError:
        # Quiet when the suite never ran (the calling step uses if: always()).
        return 0

    failed = errors = skipped = passed = 0
    for case in root.iter("testcase"):
        name = case.get("name", "")
        classname = case.get("classname", "")
        label = f"{classname}::{name}" if classname else name
        if case.find("failure") is not None:
            failed += 1
            if not passed_only:
                print(label)
        elif case.find("error") is not None:
            errors += 1
            if not passed_only:
                print(label)
        elif case.find("skipped") is not None:
            skipped += 1
        else:
            passed += 1
            if passed_only:
                print(label)

    print(f"summary: {passed} passed, {failed} failed, {errors} errors, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
