"""provider_transcript: every tool call reaches a provider followed by exactly its results."""

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompt_values import StringPromptValue
import pytest

from app.agents.llm.transcript import UNFINISHED_TOOL_RESULT, provider_input, provider_transcript


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


@pytest.mark.unit
class TestProviderTranscript:
    def test_a_valid_thread_comes_back_unchanged(self) -> None:
        thread: list[AnyMessage] = [
            SystemMessage(content="sys"),
            HumanMessage(content="hi"),
            _calling("a", "b"),
            _result("a"),
            _result("b"),
            AIMessage(content="done"),
        ]

        assert provider_transcript(thread) == thread

    def test_a_result_written_after_later_turns_moves_back_beside_its_call(self) -> None:
        late = _result("a", content="the real result")
        thread: list[AnyMessage] = [
            HumanMessage(content="research"),
            _calling("a"),
            HumanMessage(content="add a todo"),
            AIMessage(content="todo added"),
            late,
        ]

        shaped = provider_transcript(thread)

        assert _shape(shaped) == [
            ("HumanMessage", None),
            ("AIMessage", None),
            ("ToolMessage", "a"),
            ("HumanMessage", None),
            ("AIMessage", None),
        ]
        assert shaped[2] is late

    def test_results_follow_the_order_of_their_calls(self) -> None:
        thread: list[AnyMessage] = [_calling("a", "b"), _result("b"), _result("a")]

        assert _shape(provider_transcript(thread))[1:] == [
            ("ToolMessage", "a"),
            ("ToolMessage", "b"),
        ]

    def test_an_unanswered_call_is_answered_as_unfinished(self) -> None:
        thread: list[AnyMessage] = [_calling("a", content="let me look"), HumanMessage(content="?")]

        shaped = provider_transcript(thread)

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

    def test_an_unparsed_call_is_answered_too(self) -> None:
        """OpenAI is sent invalid_tool_calls as tool calls, so they need a result as well."""
        broken = AIMessage(
            content="",
            invalid_tool_calls=[{"id": "x", "name": "web_search", "args": "{", "error": "json"}],
        )

        assert _shape(provider_transcript([broken])) == [("AIMessage", None), ("ToolMessage", "x")]

    def test_a_result_with_no_call_is_dropped(self) -> None:
        thread: list[AnyMessage] = [HumanMessage(content="hi"), _result("gone")]

        assert _shape(provider_transcript(thread)) == [("HumanMessage", None)]

    def test_a_second_result_for_one_call_is_dropped(self) -> None:
        first = _result("a", content="first")
        thread: list[AnyMessage] = [_calling("a"), first, _result("a", content="again")]

        shaped = provider_transcript(thread)

        assert len(shaped) == 2
        assert shaped[1] is first

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
