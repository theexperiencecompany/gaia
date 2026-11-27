"""provider_transcript: every tool call reaches a provider followed by exactly its results."""

from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompt_values import StringPromptValue
import pytest

from app.agents.llm.transcript import UNFINISHED_TOOL_RESULT, provider_input, provider_transcript
from app.constants.log_tags import LogTag
from tests.helpers import captured_wide_event

RESHAPED = f"{LogTag.AGENT} Reshaped the tool results a thread held out of place"


def _calling(*call_ids: str, content: str = "") -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=[{"id": call_id, "name": "web_search", "args": {}} for call_id in call_ids],
    )


def _result(call_id: str, content: str = "found") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call_id)


def _shape(messages: list[AnyMessage]) -> list[tuple[str, str | None]]:
    return [
        (type(m).__name__, m.tool_call_id if isinstance(m, ToolMessage) else None) for m in messages
    ]


def _reshaped(moved: int = 0, unfinished: int = 0, dropped: int = 0) -> list[dict[str, Any]]:
    return [
        {
            "msg": RESHAPED,
            "moved_tool_results": moved,
            "unfinished_tool_calls": unfinished,
            "dropped_tool_results": dropped,
        }
    ]


async def _shaped_and_warnings(
    thread: list[AnyMessage],
) -> tuple[list[AnyMessage], list[dict[str, Any]]]:
    async with captured_wide_event() as event:
        shaped = provider_transcript(thread)
    return shaped, event.get("warnings", [])


@pytest.mark.unit
class TestProviderTranscript:
    async def test_a_valid_thread_comes_back_unchanged_and_unlogged(self) -> None:
        thread: list[AnyMessage] = [
            SystemMessage(content="sys"),
            HumanMessage(content="hi"),
            _calling("a", "b"),
            _result("a"),
            _result("b"),
            AIMessage(content="done"),
        ]

        shaped, warnings = await _shaped_and_warnings(thread)

        assert shaped == thread
        assert warnings == []

    async def test_a_result_written_after_later_turns_moves_back_beside_its_call(self) -> None:
        late = _result("a", content="the real result")
        thread: list[AnyMessage] = [
            HumanMessage(content="research"),
            _calling("a"),
            HumanMessage(content="add a todo"),
            AIMessage(content="todo added"),
            late,
        ]

        shaped, warnings = await _shaped_and_warnings(thread)

        assert _shape(shaped) == [
            ("HumanMessage", None),
            ("AIMessage", None),
            ("ToolMessage", "a"),
            ("HumanMessage", None),
            ("AIMessage", None),
        ]
        assert shaped[2] is late
        assert warnings == _reshaped(moved=1)

    async def test_results_follow_the_order_of_their_calls(self) -> None:
        thread: list[AnyMessage] = [_calling("a", "b"), _result("b"), _result("a")]

        shaped, warnings = await _shaped_and_warnings(thread)

        assert _shape(shaped)[1:] == [("ToolMessage", "a"), ("ToolMessage", "b")]
        assert warnings == []  # reordered within its slot: nothing moved, answered or dropped

    async def test_an_unanswered_call_is_answered_as_unfinished(self) -> None:
        thread: list[AnyMessage] = [_calling("a", content="let me look"), HumanMessage(content="?")]

        shaped, warnings = await _shaped_and_warnings(thread)

        assert _shape(shaped) == [
            ("AIMessage", None),
            ("ToolMessage", "a"),
            ("HumanMessage", None),
        ]
        unfinished = shaped[1]
        assert isinstance(unfinished, ToolMessage)
        assert (unfinished.content, unfinished.status, unfinished.name) == (
            UNFINISHED_TOOL_RESULT,
            "error",
            "web_search",
        )
        assert shaped[0] is thread[0]
        assert warnings == _reshaped(unfinished=1)

    async def test_an_unparsed_call_is_answered_too(self) -> None:
        """OpenAI is sent invalid_tool_calls as tool calls, so they need a result as well."""
        broken = AIMessage(
            content="",
            invalid_tool_calls=[{"id": "x", "name": "web_search", "args": "{", "error": "json"}],
        )

        shaped, warnings = await _shaped_and_warnings([broken])

        assert _shape(shaped) == [("AIMessage", None), ("ToolMessage", "x")]
        assert warnings == _reshaped(unfinished=1)

    async def test_a_call_without_an_id_gets_no_result(self) -> None:
        nameless = AIMessage(
            content="",
            invalid_tool_calls=[{"id": None, "name": "web_search", "args": "{", "error": "json"}],
        )

        shaped, warnings = await _shaped_and_warnings([nameless])

        assert shaped == [nameless]
        assert warnings == []

    async def test_a_result_with_no_call_is_dropped(self) -> None:
        thread: list[AnyMessage] = [HumanMessage(content="hi"), _result("gone")]

        shaped, warnings = await _shaped_and_warnings(thread)

        assert _shape(shaped) == [("HumanMessage", None)]
        assert warnings == _reshaped(dropped=1)

    async def test_a_second_result_for_one_call_is_dropped(self) -> None:
        first = _result("a", content="first")
        thread: list[AnyMessage] = [_calling("a"), first, _result("a", content="again")]

        shaped, warnings = await _shaped_and_warnings(thread)

        assert shaped == [thread[0], first]
        assert warnings == _reshaped(dropped=1)

    async def test_every_repair_is_counted_in_one_warning(self) -> None:
        thread: list[AnyMessage] = [
            _calling("a", "b"),
            HumanMessage(content="?"),
            _result("a"),
            _result("orphan"),
            _result("other-orphan"),
        ]

        shaped, warnings = await _shaped_and_warnings(thread)

        assert _shape(shaped) == [
            ("AIMessage", None),
            ("ToolMessage", "a"),
            ("ToolMessage", "b"),
            ("HumanMessage", None),
        ]
        assert warnings == _reshaped(moved=1, unfinished=1, dropped=2)

    async def test_a_result_written_before_its_call_moves_after_it(self) -> None:
        thread: list[AnyMessage] = [HumanMessage(content="hi"), _result("a"), _calling("a")]

        shaped, warnings = await _shaped_and_warnings(thread)

        assert _shape(shaped) == [("HumanMessage", None), ("AIMessage", None), ("ToolMessage", "a")]
        assert warnings == _reshaped(moved=1)

    async def test_a_result_behind_an_orphan_and_a_turn_is_moved(self) -> None:
        thread: list[AnyMessage] = [
            _calling("a"),
            _result("orphan"),
            HumanMessage(content="?"),
            _result("a"),
        ]

        shaped, warnings = await _shaped_and_warnings(thread)

        assert _shape(shaped) == [("AIMessage", None), ("ToolMessage", "a"), ("HumanMessage", None)]
        assert warnings == _reshaped(moved=1, dropped=1)

    async def test_each_moved_result_and_unfinished_call_is_counted(self) -> None:
        thread: list[AnyMessage] = [
            _calling("a", "b", "c", "d"),
            HumanMessage(content="?"),
            _result("a"),
            _result("b"),
        ]

        shaped, warnings = await _shaped_and_warnings(thread)

        assert [m.tool_call_id for m in shaped if isinstance(m, ToolMessage)] == list("abcd")
        assert warnings == _reshaped(moved=2, unfinished=2)

    async def test_a_call_after_an_id_less_one_is_still_answered(self) -> None:
        broken = AIMessage(
            content="",
            invalid_tool_calls=[
                {"id": None, "name": "web_search", "args": "{", "error": "json"},
                {"id": "y", "name": "web_search", "args": "{", "error": "json"},
            ],
        )

        shaped, _ = await _shaped_and_warnings([broken])

        assert _shape(shaped) == [("AIMessage", None), ("ToolMessage", "y")]

    def test_the_thread_itself_is_not_modified(self) -> None:
        thread: list[AnyMessage] = [_calling("a"), HumanMessage(content="?")]

        provider_transcript(thread)

        assert len(thread) == 2


@pytest.mark.unit
class TestProviderInput:
    def test_a_message_list_is_shaped(self) -> None:
        shaped = provider_input([_calling("a")])

        assert isinstance(shaped, list)
        assert _shape(shaped) == [("AIMessage", None), ("ToolMessage", "a")]

    def test_role_tuples_become_messages(self) -> None:
        shaped = provider_input([("user", "hi")])

        assert isinstance(shaped, list)
        assert isinstance(shaped[0], HumanMessage)

    def test_a_prompt_string_passes_through(self) -> None:
        assert provider_input("summarise this") == "summarise this"

    def test_a_prompt_value_passes_through(self) -> None:
        prompt = StringPromptValue(text="summarise this")

        assert provider_input(prompt) is prompt
