"""ToolCallCorrectness accepts a list of tool names as "any of these".

Tracked-todo notes are files the agent edits with either ``edit`` or ``write``;
a case that pins one of them fails a correct run that picked the other. A list
counts calls to any listed name towards ``min_calls``.
"""

from __future__ import annotations

from scripts.evals.core.scorers import ToolCallCorrectness


def _score(tool_calls: list[dict[str, object]], expected: list[dict[str, object]]) -> float:
    return (
        ToolCallCorrectness()
        .score(output="", tool_calls=tool_calls, expected={"tool_calls": expected})
        .value
    )


def test_any_listed_tool_satisfies_the_entry() -> None:
    assert _score([{"name": "edit", "args": {}}], [{"tool": ["edit", "write"]}]) == 1.0
    assert _score([{"name": "write", "args": {}}], [{"tool": ["edit", "write"]}]) == 1.0


def test_calls_to_different_listed_tools_add_up_to_min_calls() -> None:
    calls = [{"name": "edit", "args": {}}, {"name": "write", "args": {}}]
    assert _score(calls, [{"tool": ["edit", "write"], "min_calls": 2}]) == 1.0
    assert _score(calls[:1], [{"tool": ["edit", "write"], "min_calls": 2}]) == 0.0


def test_an_unlisted_tool_does_not_count() -> None:
    assert _score([{"name": "bash", "args": {}}], [{"tool": ["edit", "write"]}]) == 0.0


def test_args_check_applies_across_the_listed_tools() -> None:
    calls = [{"name": "write", "args": {"content": "MOT runs out in November"}}]
    assert _score(calls, [{"tool": ["edit", "write"], "args": {"content": "November"}}]) == 1.0
    assert _score(calls, [{"tool": ["edit", "write"], "args": {"content": "December"}}]) == 0.0
