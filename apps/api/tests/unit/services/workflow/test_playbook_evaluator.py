"""Resolving a playbook step's placeholders against the run that is happening.

The asymmetry is the whole point and every test here defends one half of it: an
unresolvable ``$last_run`` is a first replay with no history and must resolve to
``None``, while an unresolvable ``$steps`` / ``$trigger`` / ``$user`` means the
playbook is stale and must stop the run by name.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.models.workflow_execution_models import RecordedCall
from app.services.workflow.playbook.evaluator import (
    PlaceholderError,
    PlaybookUser,
    RunContext,
    StepResult,
    last_run_index,
    resolve_args,
    resolve_value,
)

NOW = datetime(2026, 3, 14, 9, 30, tzinfo=ZoneInfo("Europe/Berlin"))


def _context(
    *,
    steps: dict[str, StepResult] | None = None,
    trigger: dict[str, object] | None = None,
    last_run: dict[str, object] | None = None,
    asks: dict[str, str] | None = None,
    user: PlaybookUser | None = None,
) -> RunContext:
    return RunContext(
        user=user or PlaybookUser(email="ada@example.com", name="Ada", timezone="Europe/Berlin"),
        now=NOW,
        trigger=trigger or {},
        steps=steps or {},
        last_run=last_run or {},
        asks=asks or {},
    )


def test_now_and_today_render_the_workflow_zone() -> None:
    context = _context()
    assert resolve_value("$now", context) == "2026-03-14T09:30:00+01:00"
    assert resolve_value("$today", context) == "2026-03-14"


def test_time_offsets_move_forward_and_back() -> None:
    context = _context()
    assert resolve_value("$today + 1d", context) == "2026-03-15"
    assert resolve_value("$now - 2h", context) == "2026-03-14T07:30:00+01:00"


def test_user_fields_resolve_from_the_profile() -> None:
    context = _context()
    assert resolve_value("$user.email", context) == "ada@example.com"
    assert resolve_value("$user.name", context) == "Ada"
    assert resolve_value("$user.timezone", context) == "Europe/Berlin"


def test_trigger_resolves_a_nested_json_path() -> None:
    context = _context(trigger={"events": [{"id": "evt_9"}]})
    assert resolve_value("$trigger.events.0.id", context) == "evt_9"


def test_steps_resolve_by_id_and_by_file() -> None:
    context = _context(
        steps={"inbox": StepResult(value={"count": 12}, file="/workspace/inbox.json")}
    )
    assert resolve_value("$steps.inbox.count", context) == 12
    assert resolve_value("$steps.inbox.file", context) == "/workspace/inbox.json"


def test_ask_resolves_the_text_the_model_wrote() -> None:
    context = _context(asks={"body": "Here is your morning digest."})
    assert resolve_value("$ask.body", context) == "Here is your morning digest."


def test_last_run_resolves_a_cursor_from_the_previous_run() -> None:
    context = _context(last_run={"GMAIL_FETCH": {"next_page": "tok_2"}})
    assert resolve_value("$last_run.GMAIL_FETCH.next_page", context) == "tok_2"


def test_unresolvable_last_run_is_none_not_an_error() -> None:
    """A first replay follows an agentic run, so there is nothing to look back at."""
    context = _context(last_run={})
    assert resolve_value("$last_run.GMAIL_FETCH.next_page", context) is None
    assert resolve_value("$last_run.GMAIL_FETCH", context) is None


def test_unresolvable_last_run_field_on_a_known_tool_is_also_none() -> None:
    context = _context(last_run={"GMAIL_FETCH": {"other": 1}})
    assert resolve_value("$last_run.GMAIL_FETCH.next_page", context) is None


def test_unresolvable_step_raises_and_names_the_placeholder() -> None:
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$steps.missing.count", _context())
    assert "$steps.missing.count" in caught.value.message


def test_unresolvable_step_field_raises_and_names_the_placeholder() -> None:
    context = _context(steps={"inbox": StepResult(value={"count": 12})})
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$steps.inbox.total", context)
    assert "$steps.inbox.total" in caught.value.message


def test_unresolvable_trigger_raises_and_names_the_placeholder() -> None:
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$trigger.email.subject", _context(trigger={"events": []}))
    assert "$trigger.email.subject" in caught.value.message


def test_empty_user_field_raises_and_names_the_placeholder() -> None:
    blank = PlaybookUser(email="", name="Ada", timezone="UTC")
    with pytest.raises(PlaceholderError) as caught:
        resolve_value("$user.email", _context(user=blank))
    assert "$user.email" in caught.value.message


def test_whole_value_placeholder_preserves_the_resolved_type() -> None:
    context = _context(
        steps={"inbox": StepResult(value={"count": 12, "ids": ["a", "b"], "done": True})}
    )
    resolved = resolve_args(
        {
            "max_results": "$steps.inbox.count",
            "ids": "$steps.inbox.ids",
            "flag": "$steps.inbox.done",
        },
        context,
    )
    assert resolved["max_results"] == 12
    assert resolved["ids"] == ["a", "b"]
    assert resolved["flag"] is True


def test_embedded_placeholder_interpolates_into_the_surrounding_string() -> None:
    context = _context(steps={"inbox": StepResult(value={"count": 12})})
    resolved = resolve_value("Found $steps.inbox.count messages on $today", context)
    assert resolved == "Found 12 messages on 2026-03-14"


def test_embedded_unresolvable_last_run_leaves_nothing_behind() -> None:
    resolved = resolve_value("cursor=$last_run.GMAIL_FETCH.next_page", _context())
    assert resolved == "cursor="


def test_non_string_and_plain_string_values_pass_through_untouched() -> None:
    context = _context()
    resolved = resolve_args(
        {"limit": 25, "enabled": False, "ratio": 0.5, "label": "daily digest", "none": None},
        context,
    )
    assert resolved == {
        "limit": 25,
        "enabled": False,
        "ratio": 0.5,
        "label": "daily digest",
        "none": None,
    }


def test_placeholders_nested_in_lists_and_dicts_resolve() -> None:
    context = _context(trigger={"to": "team@example.com"})
    resolved = resolve_args(
        {"message": {"recipients": ["$trigger.to"], "sent_on": "$today"}}, context
    )
    assert resolved == {"message": {"recipients": ["team@example.com"], "sent_on": "2026-03-14"}}


def test_an_offset_on_a_non_time_root_is_rejected() -> None:
    with pytest.raises(PlaceholderError):
        resolve_value("$trigger.at + 1d", _context(trigger={"at": "x"}))


def test_last_run_index_keeps_the_most_recent_call_per_tool() -> None:
    index = last_run_index(
        [
            RecordedCall(tool_name="GMAIL_FETCH", result_digest='{"next_page": "tok_1"}'),
            RecordedCall(tool_name="GMAIL_FETCH", result_digest='{"next_page": "tok_2"}'),
            RecordedCall(tool_name="SLACK_POST", result_digest="posted"),
        ]
    )
    assert index["GMAIL_FETCH"] == {"next_page": "tok_2"}
    assert index["SLACK_POST"] == "posted"
