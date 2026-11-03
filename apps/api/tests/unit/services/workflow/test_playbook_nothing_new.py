"""When a playbook's opening read counts as nothing new since the last run."""

import json

import pytest

from app.models.workflow_execution_models import RecordedCall
from app.services.workflow.playbook.nothing_new import is_opening_read, item_ids, nothing_new

INBOX = {"data": {"messages": [{"id": "m1", "subject": "a"}, {"id": "m2", "subject": "b"}]}}


def _last_run(result: object, *, tool: str = "GMAIL_FETCH_MESSAGES", **flags: bool) -> RecordedCall:
    return RecordedCall(tool_name=tool, result_digest=json.dumps(result), **flags)


def test_an_empty_envelope_is_nothing_new_with_no_last_run_at_all() -> None:
    empty = {"data": {"messages": [], "fetched_count": 0}}

    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, empty, []) == (
        "GMAIL_FETCH_MESSAGES returned nothing"
    )


def test_the_same_ids_in_another_order_are_nothing_new() -> None:
    reordered = {"data": {"messages": [{"id": "m2"}, {"id": "m1"}]}}

    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, reordered, [_last_run(INBOX)]) == (
        "GMAIL_FETCH_MESSAGES returned the same 2 items as the last run"
    )


def test_one_new_id_is_new() -> None:
    grown = {"data": {"messages": [{"id": "m3"}, {"id": "m1"}, {"id": "m2"}]}}

    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, grown, [_last_run(INBOX)]) is None


def test_a_last_run_whose_record_shed_items_never_matches_the_full_list() -> None:
    """A digest that kept fewer elements than the tool returned must read as different, never as the same."""
    shed = {"data": {"messages": [{"id": "m1"}]}}

    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, INBOX, [_last_run(shed)]) is None


def test_elements_without_ids_are_never_the_same() -> None:
    events = {"events": [{"title": "standup"}]}

    assert nothing_new("list_events", {}, events, [_last_run(events, tool="list_events")]) is None


def test_a_failed_last_call_is_no_baseline() -> None:
    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, INBOX, [_last_run(INBOX, failed=True)]) is None


def test_a_read_through_execute_is_compared_with_the_same_tool_run_directly() -> None:
    proxied = {"tool_name": "GMAIL_FETCH_MESSAGES", "data": {"query": "in:inbox"}}

    assert is_opening_read("execute", proxied)
    assert nothing_new("execute", proxied, INBOX, [_last_run(INBOX)]) == (
        "GMAIL_FETCH_MESSAGES returned the same 2 items as the last run"
    )


@pytest.mark.parametrize(
    ("tool", "args", "reads"),
    [
        ("GMAIL_FETCH_MESSAGES", {}, True),
        ("list_todos", {}, True),
        ("GMAIL_SEND_EMAIL", {}, False),
        ("execute", {"tool_name": "GMAIL_CREATE_EMAIL_DRAFT", "data": {}}, False),
    ],
)
def test_only_a_call_that_changes_nothing_opens_a_run_it_may_end(
    tool: str, args: dict[str, object], reads: bool
) -> None:
    assert is_opening_read(tool, args) is reads


def test_ids_are_read_off_the_largest_list_past_the_envelope() -> None:
    assert item_ids(INBOX) == frozenset({"m1", "m2"})


def test_the_last_runs_read_is_found_past_its_other_calls_and_through_execute() -> None:
    proxied = RecordedCall(
        tool_name="execute",
        args={"tool_name": "GMAIL_FETCH_MESSAGES", "data": {}},
        result_digest=json.dumps(INBOX),
    )
    previous = [RecordedCall(tool_name="list_todos", result_digest="[]"), proxied]

    assert nothing_new("GMAIL_FETCH_MESSAGES", {}, INBOX, previous) == (
        "GMAIL_FETCH_MESSAGES returned the same 2 items as the last run"
    )


def test_an_element_with_an_empty_id_has_no_identity() -> None:
    assert item_ids({"items": [{"id": "m1"}, {"id": ""}]}) is None
