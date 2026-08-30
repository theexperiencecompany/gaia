"""Tests for app.agents.core.subagents.call_record."""

from datetime import UTC, datetime
import json

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
import pytest

from app.agents.core.subagents.call_record import (
    ARG_TRUNCATION_MARKER,
    CALL_RECORD_LEAD_IN,
    EMPTY_RESULT_SUFFIX,
    MAX_RECORDED_ARG_CHARS,
    _compact_json,
    _truncated_arg,
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


def _json(call_id: str, payload: object) -> ToolMessage:
    return ToolMessage(content=json.dumps(payload), tool_call_id=call_id)


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

    @pytest.mark.parametrize(
        "payload",
        [
            {"success": False, "error": "not found"},
            {"success": False},
            {"error": "quota exceeded", "data": []},
        ],
    )
    def test_a_call_whose_ok_message_carries_an_error_envelope_is_dropped(
        self, payload: dict[str, object]
    ) -> None:
        # Regression: tools report failure in the body under a normal status,
        # so the record froze calls that never worked and the playbook replayed
        # them as if they had.
        messages: list[AnyMessage] = [
            _ai(
                _call("GMAIL_FETCH_MESSAGES", {"max_messages": 5}, "tc1"),
                _call("GMAIL_SEND_EMAIL", {"to": "a@b.c"}, "tc2"),
            ),
            _json("tc1", {"success": True, "data": {"messages": [{"id": 1}]}}),
            _json("tc2", payload),
        ]

        assert successful_call_lines(messages) == [
            'GMAIL_FETCH_MESSAGES({"max_messages":5})',
        ]

    @pytest.mark.parametrize(
        "payload",
        [
            {"success": True, "error": None, "data": [{"id": 1}]},
            {"success": True, "error": "", "data": [{"id": 1}]},
        ],
    )
    def test_an_empty_error_field_is_not_an_error(self, payload: dict[str, object]) -> None:
        messages: list[AnyMessage] = [
            _ai(_call("GMAIL_FETCH_MESSAGES", {"max_messages": 5}, "tc1")),
            _json("tc1", payload),
        ]

        assert successful_call_lines(messages) == [
            'GMAIL_FETCH_MESSAGES({"max_messages":5})',
        ]

    def test_a_result_whose_largest_list_is_empty_is_marked(self) -> None:
        # The executor is about to freeze this call; it has to see that the
        # call came back with nothing before it does.
        messages: list[AnyMessage] = [
            _ai(_call("GMAIL_FETCH_MESSAGES", {"query": "is:unread"}, "tc1")),
            _json("tc1", {"success": True, "data": {"messages": [], "total": 0}}),
        ]

        assert successful_call_lines(messages) == [
            'GMAIL_FETCH_MESSAGES({"query":"is:unread"})' + EMPTY_RESULT_SUFFIX,
        ]

    def test_a_result_with_items_is_not_marked_even_if_a_smaller_list_is_empty(self) -> None:
        messages: list[AnyMessage] = [
            _ai(_call("GMAIL_FETCH_MESSAGES", {"query": "is:unread"}, "tc1")),
            _json(
                "tc1",
                {"data": {"messages": [{"id": 1, "labels": []}, {"id": 2, "labels": []}]}},
            ),
        ]

        (line,) = successful_call_lines(messages)
        assert EMPTY_RESULT_SUFFIX not in line

    def test_a_result_with_no_list_at_all_is_not_marked(self) -> None:
        messages: list[AnyMessage] = [
            _ai(_call("GMAIL_SEND_EMAIL", {"to": "a@b.c"}, "tc1")),
            _json("tc1", {"success": True, "data": {"id": "m1"}}),
            _ai(_call("READ_SKILL", {"name": "x"}, "tc2")),
            _ok("tc2"),
        ]

        lines = successful_call_lines(messages)
        assert lines == ['GMAIL_SEND_EMAIL({"to":"a@b.c"})', 'READ_SKILL({"name":"x"})']

    def test_a_bare_empty_list_result_is_marked(self) -> None:
        messages: list[AnyMessage] = [
            _ai(_call("LIST_TODOS", {}, "tc1")),
            _json("tc1", []),
        ]

        assert successful_call_lines(messages) == ["LIST_TODOS({})" + EMPTY_RESULT_SUFFIX]

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


@pytest.mark.unit
class TestRenderingOneRecordedValue:
    def test_a_value_json_cannot_encode_is_recorded_as_its_text_form(self) -> None:
        """The record is built from whatever a tool was called with — a datetime, an
        enum, a model. Raising here loses the whole record for one odd argument."""
        assert _compact_json({"when": datetime(2026, 8, 27, 9, 0, tzinfo=UTC)}) == (
            '{"when":"2026-08-27 09:00:00+00:00"}'
        )

    def test_a_value_exactly_at_the_cap_is_kept_whole(self) -> None:
        at_cap = "x" * MAX_RECORDED_ARG_CHARS

        assert _truncated_arg(at_cap) == at_cap
        assert _truncated_arg(at_cap + "y") == at_cap + ARG_TRUNCATION_MARKER


@pytest.mark.unit
class TestCallsAreSkippedNotStoppedAt:
    def test_a_nameless_call_is_dropped_rather_than_recorded_under_a_placeholder(
        self,
    ) -> None:
        messages: list[AnyMessage] = [
            _ai(
                {"name": "", "args": {}, "id": "tc1"},
                _call("GMAIL_SEND_EMAIL", {"to": "a@b.c"}, "tc2"),
            ),
            _ok("tc1"),
            _ok("tc2"),
        ]

        assert successful_call_lines(messages) == ['GMAIL_SEND_EMAIL({"to":"a@b.c"})']

    def test_a_skipped_call_does_not_end_the_message_it_sits_in(self) -> None:
        """finish_task is usually emitted alongside the real work in one message.
        Stopping at it instead of stepping over it records an empty run."""
        messages: list[AnyMessage] = [
            _ai(
                _call(FINISH_TASK_NAME, {"result": "done"}, "tc1"),
                _call("GMAIL_SEND_EMAIL", {"to": "a@b.c"}, "tc2"),
            ),
            _ok("tc1"),
            _ok("tc2"),
        ]

        assert successful_call_lines(messages) == ['GMAIL_SEND_EMAIL({"to":"a@b.c"})']


@pytest.mark.unit
class TestTheRecordBlockIsExact:
    def test_the_lead_in_and_every_call_are_one_line_each(self) -> None:
        messages: list[AnyMessage] = [
            _ai(
                _call("GMAIL_FETCH_MESSAGES", {"max_messages": 5}, "tc1"),
                _call("GMAIL_SEND_EMAIL", {"to": "a@b.c"}, "tc2"),
            ),
            _ok("tc1"),
            _ok("tc2"),
        ]

        assert append_call_record("Subagent finished.", messages) == (
            "Subagent finished.\n\n"
            "<subagent_call_record>\n"
            + CALL_RECORD_LEAD_IN
            + "\n"
            + 'GMAIL_FETCH_MESSAGES({"max_messages":5})'
            + "\n"
            + 'GMAIL_SEND_EMAIL({"to":"a@b.c"})'
            + "\n</subagent_call_record>\n"
        )
