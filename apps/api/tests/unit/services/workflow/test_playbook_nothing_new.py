"""When a playbook's opening read counts as nothing new since the previous fire."""

import json

import pytest

from app.models.workflow_execution_models import RecordedCall
from app.services.workflow.playbook.nothing_new import (
    is_opening_read,
    item_fingerprint,
    item_ids,
    nothing_new,
)

INBOX = {"data": {"messages": [{"id": "m1", "subject": "a"}, {"id": "m2", "subject": "b"}]}}
INBOX_IDS = ["m1", "m2"]


def _replayed(
    ids: list[str] | None, *, tool: str = "GMAIL_FETCH_MESSAGES", **fields: object
) -> RecordedCall:
    """Return the previous fire's replay of the read, as the runner records it."""
    return RecordedCall.model_validate(
        {
            "tool_name": tool,
            "result_digest": json.dumps(INBOX),
            "replayed": True,
            "item_fingerprint": None if ids is None else item_fingerprint(frozenset(ids)),
            **fields,
        }
    )


def test_an_empty_envelope_is_nothing_new_with_no_last_run_at_all() -> None:
    empty = {"data": {"messages": [], "fetched_count": 0}}

    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, empty, []) == (
        "GMAIL_FETCH_MESSAGES returned nothing"
    )


def test_the_same_ids_in_another_order_are_nothing_new() -> None:
    reordered = {"data": {"messages": [{"id": "m2"}, {"id": "m1"}]}}

    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, reordered, [_replayed(INBOX_IDS)]) == (
        "GMAIL_FETCH_MESSAGES returned the same 2 items as the last run"
    )


def test_one_new_id_is_new() -> None:
    grown = {"data": {"messages": [{"id": "m3"}, {"id": "m1"}, {"id": "m2"}]}}

    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, grown, [_replayed(INBOX_IDS)]) is None


def test_ids_the_last_run_recorded_from_its_whole_result_are_not_a_subset_of_todays() -> None:
    """Review of #1621: a digest that shed [c] from [a, b, c] must never match today's [a, b]."""
    fewer = {"data": {"messages": [{"id": "m1"}, {"id": "m2"}]}}

    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, fewer, [_replayed(["m1", "m2", "m3"])]) is None


def test_a_last_run_without_recorded_ids_is_no_baseline() -> None:
    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, INBOX, [_replayed(None)]) is None


def test_an_agent_runs_call_of_the_same_tool_is_no_baseline() -> None:
    """Review of #1621: an agent probe of the tool, with its own filters, says nothing about the step."""
    assert (
        nothing_new("GMAIL_FETCH_MESSAGES", {}, INBOX, [_replayed(INBOX_IDS, replayed=False)])
        is None
    )


def test_the_same_read_as_another_account_is_no_baseline() -> None:
    work = {"tool_name": "GMAIL_FETCH_MESSAGES", "data": {}, "account": "work@acme.com"}
    home = {"tool_name": "GMAIL_FETCH_MESSAGES", "data": {}, "account": "me@home.com"}

    assert (
        nothing_new("execute", work, INBOX, [_replayed(INBOX_IDS, tool="execute", args=home)])
        is None
    )
    assert nothing_new(
        "execute", work, INBOX, [_replayed(INBOX_IDS, tool="execute", args=work)]
    ) == ("GMAIL_FETCH_MESSAGES returned the same 2 items as the last run")


def test_the_same_tool_read_with_other_args_is_no_baseline() -> None:
    """Review of #1621: yesterday's window returning a recurring event's same id says nothing about today's."""
    today = {"timeMin": "2026-11-04T00:00:00Z"}
    yesterday = {"timeMin": "2026-11-03T00:00:00Z"}

    assert (
        nothing_new("GMAIL_FETCH_MESSAGES", today, INBOX, [_replayed(INBOX_IDS, args=yesterday)])
        is None
    )
    assert nothing_new(
        "GMAIL_FETCH_MESSAGES",
        today,
        INBOX,
        [_replayed(INBOX_IDS, args=yesterday), _replayed(INBOX_IDS, args=today)],
    ) == ("GMAIL_FETCH_MESSAGES returned the same 2 items as the last run")


def test_the_last_runs_read_is_found_past_its_other_calls_and_through_execute() -> None:
    proxied = _replayed(
        INBOX_IDS, tool="execute", args={"tool_name": "GMAIL_FETCH_MESSAGES", "data": {}}
    )
    previous = [_replayed(["t1"], tool="list_todos"), proxied]

    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, INBOX, previous) == (
        "GMAIL_FETCH_MESSAGES returned the same 2 items as the last run"
    )


@pytest.mark.parametrize(
    ("tool", "args", "reads"),
    [
        ("GMAIL_FETCH_MESSAGES", {}, True),
        ("list_todos", {}, True),
        ("search_memory", {}, True),
        ("GMAIL_SEND_EMAIL", {}, False),
        # Review of #1621: no read verb, so nothing vouches that it does not write.
        ("file_notes", {}, False),
        ("execute", {"tool_name": "GMAIL_CREATE_EMAIL_DRAFT", "data": {}}, False),
    ],
)
def test_only_a_call_named_as_a_read_opens_a_run_it_may_end(
    tool: str, args: dict[str, object], reads: bool
) -> None:
    assert is_opening_read(tool, args) is reads


def test_ids_are_read_off_the_largest_list_past_the_envelope() -> None:
    assert item_ids(INBOX) == frozenset(INBOX_IDS)


def test_elements_without_ids_or_with_an_empty_one_have_no_identity() -> None:
    assert item_ids({"events": [{"title": "standup"}]}) is None
    assert item_ids({"items": [{"id": "m1"}, {"id": ""}]}) is None


def test_a_fingerprint_is_order_free_counts_its_ids_and_stays_one_size() -> None:
    """Review of #1621: a read of ten thousand ids is recorded at the same size as one of two."""
    many = frozenset(f"m{index}" for index in range(10_000))

    assert item_fingerprint(frozenset({"a", "b"})) == item_fingerprint(frozenset({"b", "a"}))
    assert item_fingerprint(frozenset({"a", "b"})) != item_fingerprint(frozenset({"a", "c"}))
    assert item_fingerprint(many).startswith("10000:")
    assert len(item_fingerprint(many)) == len("10000:") + 64
    RecordedCall(tool_name="t", item_fingerprint=item_fingerprint(many))
