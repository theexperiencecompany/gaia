"""Tests for manage_system_prompts_node after the prompt-ordering rework.

The node keeps exactly ONE message per slot (static, dynamic-context,
todo-context, background-executor, executor-status, memory-recall, and
time-context) and rebuilds the message list in a cache-stable order:
``[static, dynamic, todo, bg_exec, exec_status, memory_recall,
...non_system..., time]``. These tests pin the exact per-slot behavior —
which messages are dropped, the precise output ordering, and the
``prompt_pruning`` log payload — so a single mutated operator in the node
cannot slip through unnoticed.
"""

from typing import Any, ClassVar, cast
from unittest.mock import MagicMock, patch

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig

from app.agents.core.nodes.manage_system_prompts import (
    _has_marker,
    _is_background_executor,
    _is_dynamic_context,
    _is_executor_status,
    _is_memory_recall,
    _is_time_context,
    _is_todo_context,
    manage_system_prompts_node,
)
from app.override.langgraph_bigtool.utils import State


def _static(content: str) -> SystemMessage:
    return SystemMessage(content=content)


def _dynamic(content: str, marker: str = "dynamic_context") -> SystemMessage:
    return SystemMessage(content=content, additional_kwargs={marker: True})


def _marked(content: str, marker: str) -> SystemMessage:
    return SystemMessage(content=content, additional_kwargs={marker: True})


def _bg_exec(content: str) -> SystemMessage:
    return SystemMessage(content=content, name="background_executor")


def _time(content: str) -> HumanMessage:
    return HumanMessage(content=content, additional_kwargs={"time_context": True})


def _config() -> RunnableConfig:
    return cast(RunnableConfig, {"configurable": {"user_id": "u1", "thread_id": "t1"}})


def _store() -> MagicMock:
    return MagicMock()


class TestHasMarker:
    def test_marker_in_additional_kwargs(self) -> None:
        msg = SystemMessage(content="x", additional_kwargs={"flag": True})
        assert _has_marker(msg, "flag") is True

    def test_falsy_marker_value_is_not_a_marker(self) -> None:
        msg = SystemMessage(content="x", additional_kwargs={"flag": False})
        assert _has_marker(msg, "flag") is False

    def test_marker_in_model_extra(self) -> None:
        class FakeMsg:
            additional_kwargs: ClassVar[dict[str, Any]] = {}
            model_extra: ClassVar[dict[str, Any]] = {"flag": True}

        assert _has_marker(cast(AnyMessage, FakeMsg()), "flag") is True

    def test_marker_absent_from_both_places(self) -> None:
        msg = SystemMessage(content="x", additional_kwargs={})
        assert _has_marker(msg, "flag") is False

    def test_marker_in_additional_kwargs_with_non_dict_model_extra(self) -> None:
        class FakeMsg:
            additional_kwargs: ClassVar[dict[str, Any]] = {"flag": True}
            model_extra: ClassVar[Any] = "not-a-dict"

        assert _has_marker(cast(AnyMessage, FakeMsg()), "flag") is True

    def test_missing_model_extra_attribute_falls_back(self) -> None:
        class FakeMsg:
            additional_kwargs: ClassVar[dict[str, Any]] = {}

        assert _has_marker(cast(AnyMessage, FakeMsg()), "flag") is False

    def test_empty_model_extra_dict_is_not_a_marker(self) -> None:
        class FakeMsg:
            additional_kwargs: ClassVar[dict[str, Any]] = {}
            model_extra: ClassVar[dict[str, Any]] = {}

        assert _has_marker(cast(AnyMessage, FakeMsg()), "flag") is False


class TestIsBackgroundExecutor:
    def test_exact_name_is_background_executor(self) -> None:
        msg = SystemMessage(content="x", name="background_executor")
        assert _is_background_executor(msg) is True

    def test_other_name_is_not(self) -> None:
        msg = SystemMessage(content="x", name="executor")
        assert _is_background_executor(msg) is False

    def test_none_name_is_not(self) -> None:
        msg = SystemMessage(content="x", name=None)
        assert _is_background_executor(msg) is False

    def test_missing_name_attribute_is_not(self) -> None:
        class FakeMsg:
            pass

        assert _is_background_executor(cast(AnyMessage, FakeMsg())) is False


class TestMarkerHelpers:
    def test_memory_recall_marker(self) -> None:
        assert _is_memory_recall(_marked("r", "memory_recall")) is True
        assert _is_memory_recall(SystemMessage(content="r")) is False

    def test_todo_context_marker(self) -> None:
        assert _is_todo_context(_marked("t", "todo_context")) is True
        assert _is_todo_context(SystemMessage(content="t")) is False

    def test_executor_status_marker(self) -> None:
        assert _is_executor_status(_marked("s", "executor_status")) is True
        assert _is_executor_status(SystemMessage(content="s")) is False

    def test_time_context_marker(self) -> None:
        assert _is_time_context(_time("now")) is True
        assert _is_time_context(HumanMessage(content="now")) is False


class TestIsDynamicContext:
    def test_dynamic_context_marker(self) -> None:
        msg = SystemMessage(content="ctx", additional_kwargs={"dynamic_context": True})
        assert _is_dynamic_context(msg) is True

    def test_legacy_memory_message_marker_treated_as_dynamic(self) -> None:
        msg = SystemMessage(content="ctx", additional_kwargs={"memory_message": True})
        assert _is_dynamic_context(msg) is True

    def test_marker_in_model_extra(self) -> None:
        class FakeMsg:
            additional_kwargs: ClassVar[dict[str, Any]] = {}
            model_extra: ClassVar[dict[str, Any]] = {"dynamic_context": True}

        assert _is_dynamic_context(cast(AnyMessage, FakeMsg())) is True

    def test_plain_system_message(self) -> None:
        assert _is_dynamic_context(SystemMessage(content="plain")) is False


class TestManageSystemPrompts:
    def test_keeps_latest_static_prompt(self) -> None:
        msgs = [
            _static("old prompt"),
            HumanMessage(content="hi"),
            _static("latest prompt"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        system_msgs = [m for m in result["messages"] if m.type == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "latest prompt"

    def test_keeps_only_latest_dynamic_context(self) -> None:
        msgs = [
            _dynamic("ctx1"),
            _dynamic("ctx2"),
            _dynamic("ctx3"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        system_msgs = [m for m in result["messages"] if m.type == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "ctx3"

    def test_keeps_latest_of_each_kind(self) -> None:
        """Stacked main + dynamic prompts collapse to one of each, latest."""
        msgs = [
            _static("old main"),
            _dynamic("old ctx"),
            HumanMessage(content="q"),
            _dynamic("new ctx"),
            _static("new main"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        contents = [m.content for m in result["messages"] if m.type == "system"]
        assert set(contents) == {"new main", "new ctx"}

    def test_empty_messages_returns_same_state(self) -> None:
        """An empty history short-circuits and returns the SAME state object —
        a mutated ``if messages:`` guard would fall through and rebuild the
        list, so identity is the pin."""
        state = cast(State, {"messages": []})
        result = manage_system_prompts_node(state, _config(), _store())
        assert result is state
        assert result["messages"] == []

    def test_missing_messages_key_returns_same_state(self) -> None:
        state = cast(State, {"other_key": "value"})
        with patch("app.agents.core.nodes.manage_system_prompts.log") as mock_log:
            result = manage_system_prompts_node(state, _config(), _store())
        assert result is state
        mock_log.set.assert_not_called()

    def test_extra_state_keys_preserved(self) -> None:
        msgs = [_static("main"), HumanMessage(content="hi")]
        state = cast(State, {"messages": msgs, "extra_key": {"nested": 1}})
        result = manage_system_prompts_node(state, _config(), _store())
        assert result["extra_key"] == {"nested": 1}
        assert [m.content for m in result["messages"]] == ["main", "hi"]

    def test_non_system_messages_preserved(self) -> None:
        msgs = [
            _static("prompt"),
            HumanMessage(content="hello"),
            AIMessage(content="hi there"),
            ToolMessage(content="result", tool_call_id="tc1"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        types = [m.type for m in result["messages"]]
        assert types.count("human") == 1
        assert types.count("ai") == 1
        assert types.count("tool") == 1
        assert types.count("system") == 1

    def test_system_messages_moved_to_front(self) -> None:
        """Kept system messages must appear BEFORE any human/ai message.

        ``langchain-google-genai``'s ``_parse_chat_history`` silently drops any
        ``SystemMessage`` that appears after a non-system message in the list
        — so leaving system messages in their original position would wipe
        out the system prompt and destroy implicit caching. The node
        rewrites the list as ``[static, dynamic, ...non_system...]``.
        """
        msgs = [
            _static("old prompt"),
            _dynamic("ctx1"),
            HumanMessage(content="hello"),
            _dynamic("ctx2"),
            AIMessage(content="reply"),
            _static("latest prompt"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        actual = [m.content for m in result["messages"]]
        # Output: static first, dynamic second, then the non-system messages in
        # their original relative order.
        assert actual == ["latest prompt", "ctx2", "hello", "reply"]

    def test_exact_cache_stable_output_order_for_all_slots(self) -> None:
        """Every slot present with multiple stacked copies: the output must be
        exactly ``[static, dynamic, todo, bg_exec, exec_status, memory_recall,
        ...non_system in order..., latest_time]`` — each slot collapsed to its
        latest copy. The only static sits at index 0 (pins the reverse scan
        actually reaching index 0), and non-system messages keep their
        relative order."""
        msgs = [
            _static("main"),
            _time("old clock"),
            _dynamic("ctx1"),
            _marked("todo1", "todo_context"),
            HumanMessage(content="user q"),
            _bg_exec("bg 1"),
            _marked("status1", "executor_status"),
            _marked("recall1", "memory_recall"),
            AIMessage(content="ai reply"),
            _time("current clock"),
            _marked("recall2", "memory_recall"),
            _bg_exec("bg 2"),
            _marked("status2", "executor_status"),
            _marked("todo2", "todo_context"),
            _dynamic("ctx2"),
            ToolMessage(content="tool result", tool_call_id="tc1"),
        ]
        with patch("app.agents.core.nodes.manage_system_prompts.log") as mock_log:
            result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        assert [m.content for m in result["messages"]] == [
            "main",
            "ctx2",
            "todo2",
            "bg 2",
            "status2",
            "recall2",
            "user q",
            "ai reply",
            "tool result",
            "current clock",
        ]
        mock_log.set.assert_called_once_with(
            prompt_pruning={
                "messages_in": 16,
                "messages_out": 10,
                "dropped_system_prompts": 5,
                "dropped_time_context": 1,
                "kept_static": True,
                "kept_dynamic": True,
                "kept_todo": True,
                "kept_bg_exec": True,
                "kept_exec_status": True,
                "kept_memory_recall": True,
                "kept_time": True,
            }
        )

    def test_log_set_payload_with_partial_slots(self) -> None:
        """The pruning stats must be exact: dropped counts, kept flags for
        every slot, and in/out message counts."""
        msgs = [
            _static("old main"),
            _static("new main"),
            _dynamic("ctx"),
            _time("oldest clock"),
            _time("older clock"),
            _time("new clock"),
        ]
        with patch("app.agents.core.nodes.manage_system_prompts.log") as mock_log:
            result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        assert [m.content for m in result["messages"]] == ["new main", "ctx", "new clock"]
        mock_log.set.assert_called_once_with(
            prompt_pruning={
                "messages_in": 6,
                "messages_out": 3,
                "dropped_system_prompts": 1,
                "dropped_time_context": 2,
                "kept_static": True,
                "kept_dynamic": True,
                "kept_todo": False,
                "kept_bg_exec": False,
                "kept_exec_status": False,
                "kept_memory_recall": False,
                "kept_time": True,
            }
        )

    def test_log_set_payload_with_all_slots_kept(self) -> None:
        msgs = [
            _static("main"),
            _dynamic("ctx"),
            _marked("todo", "todo_context"),
            _bg_exec("bg"),
            _marked("status", "executor_status"),
            _marked("recall", "memory_recall"),
            _time("now"),
        ]
        with patch("app.agents.core.nodes.manage_system_prompts.log") as mock_log:
            result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        assert [m.content for m in result["messages"]] == [
            "main",
            "ctx",
            "todo",
            "bg",
            "status",
            "recall",
            "now",
        ]
        mock_log.set.assert_called_once_with(
            prompt_pruning={
                "messages_in": 7,
                "messages_out": 7,
                "dropped_system_prompts": 0,
                "dropped_time_context": 0,
                "kept_static": True,
                "kept_dynamic": True,
                "kept_todo": True,
                "kept_bg_exec": True,
                "kept_exec_status": True,
                "kept_memory_recall": True,
                "kept_time": True,
            }
        )

    def test_background_executor_name_wins_over_markers(self) -> None:
        """Classification order: the name check comes first, so a message
        carrying both the name and an executor_status marker lands in the
        bg_exec slot."""
        msgs = [
            SystemMessage(
                content="bg",
                name="background_executor",
                additional_kwargs={"executor_status": True},
            ),
            _marked("status", "executor_status"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        assert [m.content for m in result["messages"]] == ["bg", "status"]

    def test_unknown_marker_system_message_is_treated_as_static(self) -> None:
        msgs = [_marked("weird", "some_other_flag"), _static("main")]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        # Both count as static; only the latest static survives.
        assert [m.content for m in result["messages"]] == ["main"]

    def test_legacy_memory_message_marker_slots_as_dynamic(self) -> None:
        msgs = [
            _dynamic("ctx1", marker="memory_message"),
            _dynamic("ctx2", marker="memory_message"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        assert [m.content for m in result["messages"]] == ["ctx2"]

    def test_falsy_marker_value_is_not_recognised(self) -> None:
        msgs = [
            SystemMessage(content="not flagged", additional_kwargs={"todo_context": False}),
            _static("main"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        assert [m.content for m in result["messages"]] == ["main"]

    def test_exception_is_logged_and_state_returned_unmodified(self) -> None:
        """The node runs on every agent turn, so an unexpected failure degrades
        to the untouched input state instead of crashing the graph — but it must
        never disappear silently: the cause has to reach the logs."""
        msgs = [HumanMessage(content="hello"), _static("latest prompt")]
        state = cast(State, {"messages": msgs})
        with (
            patch(
                "app.agents.core.nodes.manage_system_prompts._is_dynamic_context",
                side_effect=RuntimeError("unexpected failure"),
            ),
            patch("app.agents.core.nodes.manage_system_prompts.log") as mock_log,
        ):
            result = manage_system_prompts_node(state, _config(), _store())
        assert result is state
        assert result["messages"] is msgs

        mock_log.error.assert_called_once()
        logged = mock_log.error.call_args.args[0]
        kwargs = mock_log.error.call_args.kwargs
        assert "manage system prompts node" in logged
        assert kwargs.get("error_type") == "RuntimeError", (
            f"The exception type must be reported, got: {kwargs}"
        )
        assert "unexpected failure" in kwargs.get("error", ""), (
            f"The swallowed exception must be named in the log, got: {kwargs}"
        )
