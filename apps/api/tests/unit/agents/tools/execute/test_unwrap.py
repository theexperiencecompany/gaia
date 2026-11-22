"""execute_call_note: the account or amends text an execute call carries, or None."""

import pytest

from app.agents.tools.execute.unwrap import execute_call_note
from app.constants.execute import EXECUTE_TOOL_NAME


def test_an_execute_call_carries_the_note_it_names() -> None:
    args: dict[str, object] = {"tool_name": "GMAIL_SEND_EMAIL", "amends": "ap_1"}
    assert execute_call_note(EXECUTE_TOOL_NAME, args, "amends") == "ap_1"


@pytest.mark.parametrize("value", ["", 7, None], ids=["blank", "not_a_string", "absent"])
def test_an_unusable_note_is_none(value: object) -> None:
    args: dict[str, object] = {"tool_name": "GMAIL_SEND_EMAIL", "account": value}
    assert execute_call_note(EXECUTE_TOOL_NAME, args, "account") is None


def test_a_direct_call_carries_no_note() -> None:
    assert execute_call_note("send_email", {"account": "work@acme.com"}, "account") is None
