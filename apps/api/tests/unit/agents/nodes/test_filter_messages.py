"""Behavior spec for the filter-messages pre-model hook.

UNIT: app/agents/core/nodes/filter_messages.py :: filter_messages_node

EXPECTED:
    Given a graph state with a message history, return a NEW state in which every
    AIMessage's `tool_calls` list is pruned down to only those tool calls that have
    a matching ToolMessage response somewhere in the history. All non-AI messages,
    and the AIMessage's own content/identity, are preserved in original order. The
    returned state is the same mapping with `messages` replaced. On any internal
    error, the node must return the ORIGINAL state unchanged (so the graph keeps
    running) and emit an error log.

MECHANISM:
    Pass 1: collect `tool_call_id` of every ToolMessage into a set.
    Pass 2: for each AIMessage that has tool_calls, model_copy() it and keep only
            the tool_calls whose `tc.get("id")` is in the answered set; every other
            message is appended unchanged.
    Returns `{**state, "messages": filtered_messages}`.
    The whole body is wrapped in try/except: on exception it logs
    `f"Error in filter messages node: {e}"` and returns the unmodified `state`.

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - An unanswered tool call is REMOVED from its AIMessage  [membership `in` flip]
  - An answered tool call is KEPT                          [membership `in` flip]
  - Matching is by the literal key "id" on each tool_call  [const_str "id" -> ""]
  - Matching is set-based across the WHOLE history, not positional: a ToolMessage
    answers its AIMessage regardless of order in the list
  - Non-AI messages (System/Human/Tool) survive identical and in order
  - AIMessage content + identity are preserved even when all its tool_calls are stripped
  - The returned object is a NEW filtered state with the `messages` key replaced
    (happy-path `return {**state, ...}` -> `return None` mutant)
  - On internal error, the ORIGINAL state is returned, NOT None
    (except-path `return state` -> `return None` mutant)
  - On internal error, the error log carries the "Error in filter messages node"
    contract message (except-path log const_str mutant)

EQUIVALENT MUTANTS (allowed survivors, justified):
  - L21 const_str "Filters out unanswered tool calls from AI messages." -> "":
    this is the function DOCSTRING. It has zero runtime effect on the returned
    state or logs, so no behavioral test can distinguish it. Proven equivalent.
"""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from app.agents.core.nodes import filter_messages as filter_messages_module
from app.agents.core.nodes.filter_messages import filter_messages_node


def _config() -> dict:
    return {"configurable": {"user_id": "u1", "thread_id": "t1"}}


def _store() -> MagicMock:
    return MagicMock()


def _ai(content: str, *ids: str) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=[{"id": tc_id, "name": f"tool_{tc_id}", "args": {}} for tc_id in ids],
    )


@pytest.mark.unit
class TestFilterMessagesHappyPath:
    def test_unanswered_call_removed_answered_call_kept(self) -> None:
        """The core membership branch: a call WITH a ToolMessage stays, one
        WITHOUT is dropped. Kills the `in` -> `not in` flip and proves matching
        is by the answered-id set."""
        ai = _ai("", "tc1", "tc2")
        answered = ToolMessage(content="result", tool_call_id="tc1")
        state = {"messages": [ai, answered]}

        result = filter_messages_node(state, _config(), _store())

        kept = result["messages"][0]
        assert [tc["id"] for tc in kept.tool_calls] == ["tc1"]

    def test_all_calls_kept_when_all_answered(self) -> None:
        """If every tool call is answered, none are pruned. Kills the const_str
        "id" -> "" mutant: with `tc.get("")` every lookup is None and all calls
        would be wrongly dropped."""
        ai = _ai("", "tc1", "tc2")
        state = {
            "messages": [
                ai,
                ToolMessage(content="r1", tool_call_id="tc1"),
                ToolMessage(content="r2", tool_call_id="tc2"),
            ]
        }

        result = filter_messages_node(state, _config(), _store())

        assert [tc["id"] for tc in result["messages"][0].tool_calls] == ["tc1", "tc2"]

    def test_matching_is_set_based_not_positional(self) -> None:
        """The ToolMessage for "A" appears AFTER ai2, yet must answer ai1 (which
        owns "A") and NOT ai2 (which owns the unanswered "B"). A positional
        implementation would mis-attribute the response."""
        ai1 = _ai("", "A")
        ai2 = _ai("", "B")
        tool_for_a = ToolMessage(content="result_a", tool_call_id="A")
        state = {"messages": [ai1, ai2, tool_for_a]}

        result = filter_messages_node(state, _config(), _store())

        assert [tc["id"] for tc in result["messages"][0].tool_calls] == ["A"]
        assert result["messages"][1].tool_calls == []

    def test_non_ai_messages_preserved_in_order(self) -> None:
        """System/Human/Tool messages pass through untouched and keep their order
        and identity. The trailing AIMessage with an unanswered call also proves
        the filtering branch ran (its call is stripped) without dropping the msg."""
        system = SystemMessage(content="you are helpful")
        human = HumanMessage(content="hello")
        tool = ToolMessage(content="result", tool_call_id="tc1")
        unanswered_ai = _ai("", "tc_unanswered")
        state = {"messages": [system, human, tool, unanswered_ai]}

        result = filter_messages_node(state, _config(), _store())

        msgs = result["messages"]
        assert len(msgs) == 4
        assert msgs[0] is system
        assert msgs[1] is human
        assert msgs[2] is tool
        assert isinstance(msgs[3], AIMessage)
        assert msgs[3].tool_calls == []

    def test_ai_content_preserved_when_all_calls_stripped(self) -> None:
        """An AIMessage whose only tool call is unanswered keeps its content and
        type; only the tool_calls list is emptied (reasoning must not be lost)."""
        ai = _ai("I will use a tool", "tc1")
        state = {"messages": [ai]}

        result = filter_messages_node(state, _config(), _store())

        filtered = result["messages"][0]
        assert isinstance(filtered, AIMessage)
        assert filtered.content == "I will use a tool"
        assert filtered.tool_calls == []

    def test_ai_message_without_tool_calls_untouched(self) -> None:
        """A plain AIMessage (no tool_calls) skips the filtering branch entirely
        and is returned with content intact."""
        ai = AIMessage(content="just text")
        state = {"messages": [ai]}

        result = filter_messages_node(state, _config(), _store())

        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "just text"
        assert not result["messages"][0].tool_calls

    def test_returns_new_state_with_messages_replaced(self) -> None:
        """The happy path returns a state mapping carrying the FILTERED messages
        (not None, not the raw input). Kills the `return {**state, ...}` ->
        `return None` mutant, and proves extra state keys are preserved."""
        ai = _ai("", "tc1")
        state = {"messages": [ai], "extra": "preserved"}

        result = filter_messages_node(state, _config(), _store())

        assert result is not None
        assert result["extra"] == "preserved"
        assert result["messages"][0].tool_calls == []
        # filtered list, not the original input list reference
        assert result["messages"] is not state["messages"]

    def test_empty_history_returns_empty_messages(self) -> None:
        state = {"messages": []}

        result = filter_messages_node(state, _config(), _store())

        assert result["messages"] == []


@pytest.mark.unit
class TestFilterMessagesErrorPath:
    def test_on_internal_error_returns_original_state(self) -> None:
        """A non-iterable `messages` makes pass-1 raise on iteration, exercising
        the except branch. The node must return the ORIGINAL state object so the
        graph continues. Kills the `return state` -> `return None` mutant."""
        bad_state = {"messages": 123, "thread": "keepme"}

        result = filter_messages_node(bad_state, _config(), _store())

        assert result is bad_state
        assert result["thread"] == "keepme"

    def test_on_internal_error_logs_contract_message(self) -> None:
        """The except branch emits the operator-facing error log. Kills the
        log const_str mutant by asserting the exact contract prefix is logged."""
        bad_state = {"messages": 123}

        with patch.object(filter_messages_module.log, "error") as mock_error:
            filter_messages_node(bad_state, _config(), _store())

        mock_error.assert_called_once()
        logged = mock_error.call_args.args[0]
        assert logged.startswith("Error in filter messages node:")
