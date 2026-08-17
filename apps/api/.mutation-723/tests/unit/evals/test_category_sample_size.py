"""A percentage over n=1 is not a measurement.

``expected.category`` is what the report and the baseline group on
(``runner.py:508``, ``baseline.py:93``), and several categories shipped with one
or two cases in them. "Composition 100%" was two cases; the hard tier was 17
cases spread over 14 categories, so a single case flipping moved a category by
50-100 points and the report presented that as a quality signal.

This pins the floor. It also catches the quieter version of the bug: a typo in a
``category:`` value silently creates a brand-new one-case category rather than
failing anything.

Deliberately a data-only check — it reads the YAML directly rather than through
the suites, so it stays fast and cannot be affected by a suite's import graph.
"""

from __future__ import annotations

import collections
import pathlib

import pytest
import yaml

#: Below this, report raw counts instead of a percentage (evals/CLAUDE.md).
MIN_CASES_PER_CATEGORY = 8

DATA_DIR = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "evals" / "data"

SUITES = ("capability", "quality", "comms", "safety", "hil")


def _counts(suite: str) -> collections.Counter[str]:
    counts: collections.Counter[str] = collections.Counter()
    for path in sorted((DATA_DIR / suite).glob("*.yaml")):
        for case in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            category = (case.get("expected") or {}).get("category")
            assert category, f"{suite}/{path.name}: case {case.get('id')!r} has no category"
            counts[str(category)] += 1
    return counts


@pytest.mark.parametrize("suite", SUITES)
def test_every_category_has_enough_cases_to_report_a_percentage(suite: str) -> None:
    thin = {category: n for category, n in _counts(suite).items() if n < MIN_CASES_PER_CATEGORY}
    assert not thin, (
        f"{suite}: these categories have fewer than {MIN_CASES_PER_CATEGORY} cases, so their "
        f"percentage moves by more than 12 points when one case flips: {thin}"
    )


def test_the_hard_tier_is_deep_in_every_category_it_claims() -> None:
    """The tier that separates a real assistant from a demo, and the thinnest.

    A hard category with one case does not measure difficulty — it measures
    whether that one prompt happened to land.
    """
    counts: collections.Counter[tuple[str, str]] = collections.Counter()
    for suite in SUITES:
        for path in sorted((DATA_DIR / suite).glob("*.yaml")):
            for case in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
                if "hard" in (case.get("tags") or []):
                    counts[(suite, str((case.get("expected") or {}).get("category")))] += 1
    thin = {key: n for key, n in counts.items() if n < MIN_CASES_PER_CATEGORY}
    assert not thin, f"hard-tier categories below {MIN_CASES_PER_CATEGORY} cases: {thin}"


def test_the_floor_can_actually_be_breached() -> None:
    """Mutation guard: the check must be capable of failing.

    A category name nobody uses has zero cases, so the assertion has to reject
    it — otherwise this file would pass forever regardless of the data.
    """
    counts = _counts("capability")
    counts["a_category_that_does_not_exist"] = 1
    thin = {c: n for c, n in counts.items() if n < MIN_CASES_PER_CATEGORY}
    assert thin == {"a_category_that_does_not_exist": 1}
