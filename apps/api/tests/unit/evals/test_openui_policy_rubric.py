"""OpenUI rubrics must be derived from the shipped prompt, not paraphrased.

A hand-written rubric is a copy of the spec, and copies drift: someone edits
`OPENUI_SURFACE_POLICY`, nobody updates the eval, and the suite keeps happily
grading a policy the product no longer ships — green while wrong, which is the
worst state an eval can be in.

So the criteria are composed by quoting the real policy, and these tests pin
the two properties that make that worth anything: the quoted text really is the
shipped text, and a structural change to the prompt breaks loudly at load time
instead of silently degrading.
"""

from __future__ import annotations

import pytest
from scripts.evals.suites.quality import (
    OPENUI_POLICY_DIRECTIONS,
    _apply_openui_policy_criteria,
    _policy_rule,
    openui_policy_criteria,
)


def _policy() -> str:
    from app.agents.prompts.openui_prompts import OPENUI_SURFACE_POLICY

    return OPENUI_SURFACE_POLICY


def test_criteria_quote_the_shipped_policy_verbatim() -> None:
    """The rubric's quoted text must appear in the real prompt, character for character."""
    policy = " ".join(_policy().split())
    for direction in OPENUI_POLICY_DIRECTIONS:
        quoted = [
            c.split('verbatim: "', 1)[1].rsplit('"', 1)[0]
            for c in openui_policy_criteria(direction)
            if 'verbatim: "' in c
        ]
        assert quoted, f"{direction} derived no quoted policy text"
        for fragment in quoted:
            assert fragment in policy, (
                f"{direction} rubric quotes text absent from the shipped policy: {fragment[:120]!r}"
            )


def test_required_rubric_carries_the_forcing_clause() -> None:
    """Rule 5's real content is in sub-bullets.

    A line-only parse quotes the bare header "Structured data shown inline:"
    and grades nothing at all — the rubric looks populated while asserting
    nothing. This pins the sub-bullet that actually states the rule.
    """
    first = openui_policy_criteria("required")[0]

    assert "forcing rule" in first, "rule 5 was quoted without its forcing clause"
    assert ":::openui" in first
    assert "stats/KPIs" in first


def test_suppressed_rubric_lists_the_live_tool_set() -> None:
    """The suppressed-tool list must come from `tool_fields`, never a copy."""
    from app.agents.prompts.openui_prompts import OPENUI_SUPPRESSED_TOOLS

    text = " ".join(openui_policy_criteria("suppressed"))
    assert OPENUI_SUPPRESSED_TOOLS, "no suppressed tools resolved"
    for tool in OPENUI_SUPPRESSED_TOOLS:
        assert tool in text, f"{tool} missing from the suppressed rubric"


def test_a_renumbered_policy_breaks_loudly() -> None:
    """If the prompt loses a rule, loading must raise — not grade a stale spec."""
    with pytest.raises(ValueError, match="no rule 9"):
        _policy_rule(_policy(), 9)


def test_unknown_direction_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown openui_policy"):
        openui_policy_criteria("mandatory")


def test_case_criteria_are_appended_not_replaced() -> None:
    """Case-specific criteria say what THIS request is; imported ones say what
    the product promises. Losing the first would make every openui case
    identical."""
    expected: dict[str, object] = {
        "openui_policy": "forbidden",
        "judge": {"criteria": ["case-specific thing"]},
    }
    _apply_openui_policy_criteria("case-x", expected)

    criteria = expected["judge"]["criteria"]  # type: ignore[index]
    assert criteria[0] == "case-specific thing"
    assert len(criteria) > 1


def test_case_without_the_key_is_untouched() -> None:
    """Mutation guard: the 90 non-openui cases must not gain openui criteria."""
    expected: dict[str, object] = {"judge": {"criteria": ["only this"]}}
    _apply_openui_policy_criteria("case-y", expected)

    assert expected["judge"]["criteria"] == ["only this"]  # type: ignore[index]
