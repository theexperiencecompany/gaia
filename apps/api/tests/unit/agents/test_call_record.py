"""Tests for app.agents.core.subagents.call_record."""

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
import pytest

from app.agents.core.subagents.call_record import (
    ARG_TRUNCATION_MARKER,
    MAX_RECORDED_ARG_CHARS,
    append_call_record,
    successful_call_lines,
)
from app.constants.general import FINISH_TASK_NAME


def _ai(*calls: dict[str, object]) -> AIMessage:
    return AIMessage(content="", tool_calls=list(calls))


def _call(name: str, args: dict[str, object], call_id: str) -> dict[str, object]:
    return {"name": name, "args": args, "id": call_id}


def _ok(call_id: str) -> ToolMessage:
    return ToolMessage(content="ok", tool_call_id=call_id)


def _failed(call_id: str) -> ToolMessage:
    return ToolMessage(content="boom", tool_call_id=call_id, status="error")


@pytest.mark.unit
class TestSuccessfulCallLines:
    def test_successful_calls_render_in_order_with_exact_names_and_args(self) -> None:
        messages: list[AnyMessage] = [
            _ai(_call("GMAIL_FETCH_MESSAGES", {"max_messages": 5, "query": "is:unread"}, "tc1")),
            _ok("tc1"),
            _ai(_call("GMAIL_SEND_EMAIL", {"to": "a@b.c"}, "tc2")),
            _ok("tc2"),
        ]

        assert successful_call_lines(messages) == [
            'GMAIL_FETCH_MESSAGES({"max_messages":5,"query":"is:unread"})',
            'GMAIL_SEND_EMAIL({"to":"a@b.c"})',
        ]

    def test_a_failed_call_is_dropped(self) -> None:
        messages: list[AnyMessage] = [
            _ai(
                _call("GMAIL_FETCH_MESSAGES", {"max_messages": 5}, "tc1"),
                _call("GMAIL_SEND_EMAIL", {"to": "a@b.c"}, "tc2"),
            ),
            _ok("tc1"),
            _failed("tc2"),
        ]

        assert successful_call_lines(messages) == [
            'GMAIL_FETCH_MESSAGES({"max_messages":5})',
        ]

    def test_an_unanswered_call_is_dropped(self) -> None:
        messages: list[AnyMessage] = [
            _ai(_call("GMAIL_FETCH_MESSAGES", {"max_messages": 5}, "tc1")),
        ]

        assert successful_call_lines(messages) == []

    def test_finish_task_is_dropped_even_when_it_succeeded(self) -> None:
        messages: list[AnyMessage] = [
            _ai(
                _call("GMAIL_FETCH_MESSAGES", {"max_messages": 5}, "tc1"),
                _call(FINISH_TASK_NAME, {"result": "done"}, "tc2"),
            ),
            _ok("tc1"),
            _ok("tc2"),
        ]

        assert successful_call_lines(messages) == [
            'GMAIL_FETCH_MESSAGES({"max_messages":5})',
        ]

    def test_a_long_string_arg_is_truncated_with_the_marker(self) -> None:
        long_value = "x" * (MAX_RECORDED_ARG_CHARS + 50)
        messages: list[AnyMessage] = [
            _ai(_call("NOTION_CREATE_PAGE", {"body": long_value, "title": "t"}, "tc1")),
            _ok("tc1"),
        ]

        (line,) = successful_call_lines(messages)
        assert "x" * MAX_RECORDED_ARG_CHARS + ARG_TRUNCATION_MARKER in line
        assert long_value not in line
        # Only the oversized value is cut — the short arg survives verbatim.
        assert '"title":"t"' in line

    def test_a_long_structured_arg_is_truncated_in_serialized_form(self) -> None:
        long_list = list(range(MAX_RECORDED_ARG_CHARS))
        messages: list[AnyMessage] = [
            _ai(_call("SHEETS_APPEND", {"rows": long_list}, "tc1")),
            _ok("tc1"),
        ]

        (line,) = successful_call_lines(messages)
        assert ARG_TRUNCATION_MARKER in line
        assert len(line) < MAX_RECORDED_ARG_CHARS * 2

    def test_a_short_arg_is_not_truncated(self) -> None:
        messages: list[AnyMessage] = [
            _ai(_call("GMAIL_FETCH_MESSAGES", {"query": "is:unread"}, "tc1")),
            _ok("tc1"),
        ]

        (line,) = successful_call_lines(messages)
        assert ARG_TRUNCATION_MARKER not in line


@pytest.mark.unit
class TestAppendCallRecord:
    def test_appends_a_wrapped_record_block_after_the_text(self) -> None:
        messages: list[AnyMessage] = [
            _ai(_call("GMAIL_FETCH_MESSAGES", {"max_messages": 5}, "tc1")),
            _ok("tc1"),
        ]

        result = append_call_record("Subagent finished.", messages)

        assert result.startswith("Subagent finished.\n\n<subagent_call_record>\n")
        assert result.rstrip().endswith("</subagent_call_record>")
        assert 'GMAIL_FETCH_MESSAGES({"max_messages":5})' in result
        # The lead-in tells the model what the record is for.
        assert "nested steps" in result

    def test_text_is_untouched_when_no_call_succeeded(self) -> None:
        messages: list[AnyMessage] = [
            _ai(_call("GMAIL_SEND_EMAIL", {"to": "a@b.c"}, "tc1")),
            _failed("tc1"),
        ]

        assert append_call_record("Subagent finished.", messages) == "Subagent finished."

    def test_text_is_untouched_when_the_run_made_no_calls(self) -> None:
        assert append_call_record("Subagent finished.", []) == "Subagent finished."
