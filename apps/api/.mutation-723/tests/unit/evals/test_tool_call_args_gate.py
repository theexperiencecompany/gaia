"""ToolCallCorrectness must fail a call made with the wrong arguments.

The scorer's docstring has always claimed "with arg check per expected entry",
but the implementation only ever compared tool NAMES and call counts. Every
precision case in the capability suite was therefore unfalsifiable on the thing
it existed to measure: ``reminders-precision-absolute-datetime`` asserts a
reminder for 06:45 and passed with any datetime the agent chose, and
``todos-priority-fidelity`` passed with the priorities swapped.

The check is opt-in per expected entry — an entry with no ``args`` key keeps its
old name-and-count meaning, so the ~140 cases that never specified arguments do
not silently change what they measure.
"""

from __future__ import annotations

from scripts.evals.core.scorers import ToolCallCorrectness

REMINDER = "create_reminder_tool"


def _score(tool_calls: list[dict[str, object]], expected: list[dict[str, object]]) -> float:
    return (
        ToolCallCorrectness()
        .score(output="", tool_calls=tool_calls, expected={"tool_calls": expected})
        .value
    )


def test_wrong_datetime_fails_the_gate() -> None:
    """The bug: a 6:45pm reminder passed a case that demanded 06:45."""
    called_wrong_time = [
        {"name": REMINDER, "args": {"scheduled_at": "2027-01-09 18:45:00"}},
    ]
    assert (
        _score(called_wrong_time, [{"tool": REMINDER, "args": {"scheduled_at": "06:45"}}]) == 0.0
    ), "a reminder set for the wrong time satisfied a precision case"


def test_right_datetime_passes_regardless_of_format() -> None:
    """06:45 must match the stored datetime without pinning its exact format."""
    called_right_time = [
        {"name": REMINDER, "args": {"scheduled_at": "2027-01-09 06:45:00"}},
    ]
    assert _score(called_right_time, [{"tool": REMINDER, "args": {"scheduled_at": "06:45"}}]) == 1.0


def test_entry_without_args_keeps_its_old_meaning() -> None:
    """Opt-in: existing entries must still gate on name and count alone."""
    calls = [{"name": REMINDER, "args": {"scheduled_at": "whenever"}}]
    assert _score(calls, [{"tool": REMINDER}]) == 1.0
    assert _score([], [{"tool": REMINDER}]) == 0.0


def test_list_argument_matches_on_membership() -> None:
    """labels/channels/recipients are lists — the value must be one of them."""
    labelled = [{"name": "create_todo", "args": {"labels": ["finance", "urgent"]}}]
    assert _score(labelled, [{"tool": "create_todo", "args": {"labels": "finance"}}]) == 1.0
    assert _score(labelled, [{"tool": "create_todo", "args": {"labels": "personal"}}]) == 0.0


def test_missing_argument_key_fails() -> None:
    """An argument the agent never passed cannot count as a match."""
    no_priority = [{"name": "create_todo", "args": {"title": "ship the release"}}]
    assert _score(no_priority, [{"tool": "create_todo", "args": {"priority": "high"}}]) == 0.0


def test_swapped_priorities_fail() -> None:
    """The mixup todos-priority-fidelity exists to catch: two calls, values swapped."""
    swapped = [
        {"name": "create_todo", "args": {"title": "ship the release", "priority": "low"}},
        {"name": "create_todo", "args": {"title": "tidy my desk", "priority": "high"}},
    ]
    correct = [
        {"name": "create_todo", "args": {"title": "ship the release", "priority": "high"}},
        {"name": "create_todo", "args": {"title": "tidy my desk", "priority": "low"}},
    ]
    want = [
        {"tool": "create_todo", "args": {"title": "ship the release", "priority": "high"}},
        {"tool": "create_todo", "args": {"title": "tidy my desk", "priority": "low"}},
    ]
    assert _score(swapped, want) == 0.0, "swapped priorities passed a fidelity case"
    assert _score(correct, want) == 1.0


def test_min_calls_counts_only_matching_calls() -> None:
    """Two lookups of the SAME city must not satisfy 'look up two cities'."""
    same_city_twice = [
        {"name": "get_weather", "args": {"location": "Paris"}},
        {"name": "get_weather", "args": {"location": "Paris"}},
    ]
    both_cities = [
        {"name": "get_weather", "args": {"location": "Paris"}},
        {"name": "get_weather", "args": {"location": "Berlin"}},
    ]
    want = [
        {"tool": "get_weather", "args": {"location": "paris"}},
        {"tool": "get_weather", "args": {"location": "berlin"}},
    ]
    assert _score(same_city_twice, want) == 0.0, "one city answered a two-city comparison"
    assert _score(both_cities, want) == 1.0


def test_non_string_arguments_compare_by_value() -> None:
    """Numbers and booleans must compare as values, not as loose substrings."""
    bounded = [{"name": REMINDER, "args": {"max_occurrences": 10}}]
    assert _score(bounded, [{"tool": REMINDER, "args": {"max_occurrences": 10}}]) == 1.0
    assert _score(bounded, [{"tool": REMINDER, "args": {"max_occurrences": 1}}]) == 0.0, (
        "max_occurrences=10 satisfied an expectation of 1 by substring match"
    )


def test_reason_distinguishes_wrong_args_from_never_called() -> None:
    """A report reader must be able to tell the two failures apart."""
    metric = ToolCallCorrectness()
    never = metric.score(
        output="", tool_calls=[], expected={"tool_calls": [{"tool": REMINDER}]}
    ).reason
    wrong = metric.score(
        output="",
        tool_calls=[{"name": REMINDER, "args": {"scheduled_at": "18:45"}}],
        expected={"tool_calls": [{"tool": REMINDER, "args": {"scheduled_at": "06:45"}}]},
    ).reason
    assert "scheduled_at" in wrong, f"wrong-args failure did not name the argument: {wrong!r}"
    assert wrong != never
