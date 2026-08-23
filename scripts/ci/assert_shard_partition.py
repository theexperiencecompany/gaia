#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["defusedxml==0.7.1"]
# ///
"""Fail if the pytest-split shards did not partition the suite.

pytest-split slices the *collected order* into N groups, so every plugin that
reorders collection must produce the same order in all N shards. When it does
not (pytest-randomly seeding itself per shard was the real case: 4832 of 14076
tests never ran and 3897 ran twice), each shard still reports "all passed" and
coverage silently drops for whatever nobody executed.

A duplicated test id across shards is the observable symptom: the groups are
equal-sized, so every test counted twice is another test counted zero times.

Usage:
    uv run --no-project scripts/ci/assert_shard_partition.py <junit.xml> ...
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys

from defusedxml.ElementTree import parse as parse_xml


def test_ids(junit_xml: Path) -> list[str]:
    root = parse_xml(junit_xml).getroot()
    return [f"{case.get('classname')}::{case.get('name')}" for case in root.iter("testcase")]


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv]
    if not paths:
        print("::error::assert_shard_partition: no junit files given", file=sys.stderr)
        return 1

    counts: Counter[str] = Counter()
    for path in paths:
        counts.update(test_ids(path))

    total = sum(counts.values())
    repeated = {tid: n for tid, n in counts.items() if n > 1}
    if repeated:
        unrun = total - len(counts)
        print(
            f"::error::Shards are not a partition: {len(repeated)} test(s) ran in more "
            f"than one shard, so ~{unrun} of {total} ran in none. The shards disagree "
            "on collection order — every plugin that reorders collection must be "
            "disabled or seeded identically in each shard.",
            file=sys.stderr,
        )
        for tid, n in sorted(repeated.items())[:10]:
            print(f"  ran {n}x: {tid}", file=sys.stderr)
        return 1

    print(f"shard partition: OK ({total} tests across {len(paths)} shards, no overlap)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
