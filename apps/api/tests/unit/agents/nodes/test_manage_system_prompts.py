"""Tests for the manage_system_prompts node (prompt-cache prefix stabiliser).

The node keeps exactly ONE of each prompt slot per LLM call so the implicit
prompt-cache prefix stays byte-stable across turns:

  - one static (non-dynamic, non-todo) system prompt — the latest
  - one dynamic-context system prompt — the latest (new ``dynamic_context`` or
    legacy ``memory_message`` marker)
  - one todo-context system prompt — the latest, kept in its own slot
  - one time-context HumanMessage — the latest

and rewrites the list as ``[static, dynamic, todo, time, ...non_system]`` so the
kept system block sits contiguously at the front (langchain-google-genai only
promotes a leading, contiguous SystemMessage run to ``system_instruction``).

Tests import the real node + predicate helpers, mock nothing internal, and
assert real behaviour: returned message order/identity, drop counts, the
emitted observability payload, and the two early-return paths.
"""

from typing import cast

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
import pytest

from app.agents.core.nodes.manage_system_prompts import (
    _has_marker,
    _is_dynamic_context,
    _is_time_context,
    _is_todo_context,
    manage_system_prompts_node,
)
from app.override.langgraph_bigtool.utils import State
from shared.py.wide_events import log


def _static(content: str) -> SystemMessage:
    return SystemMessage(content=content)


def _marked(content: str, marker: str) -> SystemMessage:
    return SystemMessage(content=content, additional_kwargs={marker: True})


def _dynamic(content: str, marker: str = "dynamic_context") -> SystemMessage:
    return _marked(content, marker)


def _todo(content: str) -> SystemMessage:
    return _marked(content, "todo_context")


def _time(content: str) -> HumanMessage:
    return HumanMessage(content=content, additional_kwargs={"time_context": True})


def _config() -> RunnableConfig:
    return cast(RunnableConfig, {"configurable": {"user_id": "u1", "thread_id": "t1"}})


def _store() -> object:
    # The node never touches the store; any object satisfies the signature.
    return object()


def _run(messages: list[AnyMessage]) -> State:
    return manage_system_prompts_node(cast(State, {"messages": messages}), _config(), _store())


def _contents(messages: list[AnyMessage]) -> list[object]:
    return [m.content for m in messages]


@pytest.mark.unit
class TestMarkerPredicates:
    """``_has_marker`` and the three slot predicates that build on it."""

    def test_has_marker_via_additional_kwargs(self) -> None:
        msg = SystemMessage(content="x", additional_kwargs={"flag": True})
        assert _has_marker(msg, "flag") is True

    def test_has_marker_via_model_extra_fallback(self) -> None:
        class FakeMsg:
            additional_kwargs: dict = {}
            model_extra = {"flag": True}

        assert _has_marker(cast(AnyMessage, FakeMsg()), "flag") is True

    def test_has_marker_absent_returns_false(self) -> None:
        assert _has_marker(SystemMessage(content="plain"), "flag") is False

    def test_has_marker_is_name_specific(self) -> None:
        msg = SystemMessage(content="x", additional_kwargs={"dynamic_context": True})
        assert _has_marker(msg, "todo_context") is False

    def test_dynamic_context_new_marker(self) -> None:
        assert _is_dynamic_context(_dynamic("ctx")) is True

    def test_dynamic_context_legacy_memory_marker(self) -> None:
        assert _is_dynamic_context(_dynamic("ctx", marker="memory_message")) is True

    def test_dynamic_context_plain_is_false(self) -> None:
        assert _is_dynamic_context(_static("plain")) is False

    def test_todo_context_true_and_false(self) -> None:
        assert _is_todo_context(_todo("t")) is True
        assert _is_todo_context(_static("plain")) is False

    def test_time_context_true_and_false(self) -> None:
        assert _is_time_context(_time("clock")) is True
        assert _is_time_context(HumanMessage(content="plain")) is False


@pytest.mark.unit
class TestManageSystemPromptsCollapse:
    """One slot per kind, latest wins, and the front-loaded output order."""

    def test_keeps_latest_static_drops_older(self) -> None:
        result = _run([_static("old"), HumanMessage(content="hi"), _static("latest")])
        systems = [m for m in result["messages"] if m.type == "system"]
        assert len(systems) == 1
        assert systems[0].content == "latest"

    def test_keeps_latest_dynamic_drops_older(self) -> None:
        result = _run([_dynamic("ctx1"), _dynamic("ctx2"), _dynamic("ctx3")])
        systems = [m for m in result["messages"] if m.type == "system"]
        assert len(systems) == 1
        assert systems[0].content == "ctx3"

    def test_todo_kept_in_own_slot_not_collapsed_into_static(self) -> None:
        # A real static + a todo-context system message: both survive because
        # todo has its own slot. A naive "one system message" rule would drop one.
        result = _run([_static("main"), _todo("todo snapshot")])
        contents = _contents(result["messages"])
        assert contents == ["main", "todo snapshot"]

    def test_keeps_latest_of_every_kind(self) -> None:
        result = _run(
            [
                _static("old main"),
                _dynamic("old ctx"),
                _todo("old todo"),
                HumanMessage(content="q"),
                _dynamic("new ctx"),
                _todo("new todo"),
                _static("new main"),
            ]
        )
        contents = _contents(result["messages"])
        assert contents == ["new main", "new ctx", "new todo", "q"]

    def test_keeps_latest_time_context_drops_older(self) -> None:
        result = _run([_time("09:00"), HumanMessage(content="q"), _time("10:00")])
        time_msgs = [m for m in result["messages"] if _is_time_context(m)]
        assert len(time_msgs) == 1
        assert time_msgs[0].content == "10:00"

    def test_output_order_is_static_dynamic_todo_time_then_rest(self) -> None:
        # Interleave every kind out of order; the node must reorder the kept
        # system/time block to the front and keep the remaining dialogue in
        # original relative order.
        result = _run(
            [
                HumanMessage(content="hello"),
                _time("clock-old"),
                _dynamic("ctx"),
                AIMessage(content="reply"),
                _todo("todo"),
                _time("clock-new"),
                _static("main"),
            ]
        )
        contents = _contents(result["messages"])
        assert contents == ["main", "ctx", "todo", "clock-new", "hello", "reply"]

    def test_non_system_messages_preserved_in_order(self) -> None:
        result = _run(
            [
                _static("prompt"),
                HumanMessage(content="hello"),
                AIMessage(content="hi there"),
                ToolMessage(content="result", tool_call_id="tc1"),
            ]
        )
        types = [m.type for m in result["messages"]]
        assert types == ["system", "human", "ai", "tool"]

    def test_reverse_scan_picks_last_static_even_when_earlier_slots_fill_first(
        self,
    ) -> None:
        # dynamic + todo + time appear AFTER the two static prompts. The reverse
        # scan must not stop early before reaching the later static; the latest
        # static is the second one. Guards the loop range and the all-four-slots
        # break condition.
        result = _run(
            [
                _static("static-1"),
                _static("static-2"),
                _dynamic("ctx"),
                _todo("todo"),
                _time("clock"),
            ]
        )
        contents = _contents(result["messages"])
        assert contents == ["static-2", "ctx", "todo", "clock"]

    def test_single_message_at_final_index_is_scanned(self) -> None:
        # A lone static prompt sits at the only (final) index. The reverse scan
        # must include that final index — guards the loop's start bound
        # ``range(len(messages) - 1, ...)``: an off-by-one that starts one short
        # would never visit it and silently drop the only system prompt.
        result = _run([_static("only")])
        contents = _contents(result["messages"])
        assert contents == ["only"]

    def test_todo_at_lowest_index_found_when_other_slots_fill_first(self) -> None:
        # static/dynamic/time occupy the higher indices and are found first in
        # the reverse scan; the todo message sits at the lowest index, reached
        # last. The all-four-slots break must NOT fire until the todo slot is
        # also filled — otherwise the loop stops early and drops the todo.
        result = _run([_todo("t"), _static("s"), _dynamic("d"), _time("clock")])
        contents = _contents(result["messages"])
        assert contents == ["s", "d", "t", "clock"]

    def test_time_at_lowest_index_found_when_other_slots_fill_first(self) -> None:
        # Symmetric to the todo case for the time slot: time sits at the lowest
        # index, the other three fill first. The break condition must require
        # the time slot too, or the latest time-context message is dropped.
        result = _run([_time("clock"), _static("s"), _dynamic("d"), _todo("t")])
        contents = _contents(result["messages"])
        assert contents == ["s", "d", "t", "clock"]

    def test_returns_new_state_dict_not_mutated_original(self) -> None:
        original_msgs = [_static("old"), _static("new")]
        state = cast(State, {"messages": original_msgs})
        result = manage_system_prompts_node(state, _config(), _store())
        # Original list object is untouched; result carries a fresh filtered list.
        assert state["messages"] is original_msgs
        assert len(original_msgs) == 2
        assert result["messages"] is not original_msgs
        assert _contents(result["messages"]) == ["new"]


@pytest.mark.unit
class TestObservabilityPayload:
    """The ``prompt_pruning`` wide-event payload is the observability contract."""

    def test_payload_reflects_drops_and_kept_slots(self) -> None:
        log.reset()
        _run(
            [
                _static("old main"),
                _static("new main"),
                _dynamic("ctx"),
                _todo("todo"),
                _time("09:00"),
                _time("10:00"),
                HumanMessage(content="q"),
            ]
        )
        payload = log.get()["prompt_pruning"]
        assert payload["messages_in"] == 7
        # static(1) + dynamic(1) + todo(1) + time(1) + human(1) = 5
        assert payload["messages_out"] == 5
        assert payload["dropped_system_prompts"] == 1
        assert payload["dropped_time_context"] == 1
        assert payload["kept_static"] is True
        assert payload["kept_dynamic"] is True
        assert payload["kept_todo"] is True
        assert payload["kept_time"] is True

    def test_payload_reflects_absent_slots(self) -> None:
        log.reset()
        _run([HumanMessage(content="only a question")])
        payload = log.get()["prompt_pruning"]
        assert payload["messages_in"] == 1
        assert payload["messages_out"] == 1
        assert payload["dropped_system_prompts"] == 0
        assert payload["dropped_time_context"] == 0
        assert payload["kept_static"] is False
        assert payload["kept_dynamic"] is False
        assert payload["kept_todo"] is False
        assert payload["kept_time"] is False


@pytest.mark.unit
class TestEarlyReturnPaths:
    def test_empty_messages_returns_same_state_object(self) -> None:
        state = cast(State, {"messages": []})
        result = manage_system_prompts_node(state, _config(), _store())
        assert result is state
        assert result["messages"] == []

    def test_missing_messages_key_returns_same_state_object(self) -> None:
        state = cast(State, {})
        result = manage_system_prompts_node(state, _config(), _store())
        assert result is state

    def test_exception_is_swallowed_and_original_state_returned(self) -> None:
        # A message whose ``.type`` access raises drives the loop into the
        # except branch; the node must return the ORIGINAL state object intact.
        class ExplodingMessage:
            additional_kwargs: dict = {}

            @property
            def type(self) -> str:
                raise RuntimeError("boom")

        msgs = [cast(AnyMessage, ExplodingMessage()), _static("prompt")]
        state = cast(State, {"messages": msgs})
        result = manage_system_prompts_node(state, _config(), _store())
        assert result is state
        assert result["messages"] is msgs
