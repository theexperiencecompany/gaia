"""OpenUI rubrics must be derived from the shipped prompt, not paraphrased.

A hand-written rubric is a copy of the spec, and copies drift: someone edits
OPENUI_SURFACE_POLICY, nobody updates the eval, and the suite keeps grading
a policy the product no longer ships — green while wrong.

So the criteria are composed by quoting the real policy. This file pins
what the rubric must say; test_prompt_contracts_wiring.py pins that it is
composed rather than written, and that a prompt edit reaches it. These
criteria used to be sliced out by a suite-local numbered-rule regex beside a
second, general clause registry; that parser is gone and every criterion is
now a registered clause in scripts/evals/core/prompt_contracts.py.
"""

from __future__ import annotations

from typing import Any

import pytest
from scripts.evals.suites.quality import (
    _apply_openui_policy_criteria,
    openui_policy_criteria,
)


def test_required_rubric_carries_the_forcing_clause() -> None:
    """Rule 5's real content is in sub-bullets; a line-only parse quotes the bare header and grades nothing at all."""
    first = openui_policy_criteria("required")[0]

    assert "forcing rule" in first, "rule 5 was quoted without its forcing clause"
    assert ":::openui" in first
    assert "stats/KPIs" in first


def test_suppressed_rubric_lists_the_live_tool_set() -> None:
    """The suppressed-tool list must come from tool_fields, never a copy."""
    from app.agents.prompts.openui_prompts import OPENUI_SUPPRESSED_TOOLS

    text = " ".join(openui_policy_criteria("suppressed"))
    assert OPENUI_SUPPRESSED_TOOLS, "no suppressed tools resolved"
    for tool in OPENUI_SUPPRESSED_TOOLS:
        assert tool in text, f"{tool} missing from the suppressed rubric"


def test_unknown_direction_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown openui_policy"):
        openui_policy_criteria("mandatory")


def test_case_criteria_are_appended_not_replaced() -> None:
    """Case-specific criteria say what this request is; imported ones say what the product promises — losing either flattens cases."""
    expected: dict[str, Any] = {
        "openui_policy": "forbidden",
        "judge": {"criteria": ["case-specific thing"]},
    }
    _apply_openui_policy_criteria("case-x", expected)

    criteria = expected["judge"]["criteria"]
    assert criteria[0] == "case-specific thing"
    assert len(criteria) > 1


def test_case_without_the_key_is_untouched() -> None:
    """Mutation guard: the 90 non-openui cases must not gain openui criteria."""
    expected: dict[str, Any] = {"judge": {"criteria": ["only this"]}}
    _apply_openui_policy_criteria("case-y", expected)

    assert expected["judge"]["criteria"] == ["only this"]
