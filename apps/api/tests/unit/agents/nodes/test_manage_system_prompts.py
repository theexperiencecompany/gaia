"""Tests for manage_system_prompts_node: leading slots lifted, everything else as written.

The node sends the latest copy of each leading slot (static prompt, stable context,
onboarding) first and the rest of the thread in order, the same on every provider.
The cross-turn prefix property itself lives in test_manage_system_prompts_append_only.
"""

from typing import Any, TypedDict, cast
from unittest.mock import MagicMock, patch

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from prometheus_client import REGISTRY
import pytest

from app.agents.context.slots import PRESENCE_NOTE_MARKER, PromptSlot, mark
from app.agents.core.nodes.manage_system_prompts import build_request, manage_system_prompts_node
from app.constants.llm import LLMProviderName
from app.override.langgraph_bigtool.utils import PRUNED_MESSAGE_IDS_KEY, State
from tests._harness.context_chain import bound_for


def _static(content: str) -> SystemMessage:
    return SystemMessage(content=content)


def _dynamic(content: str, marker: str = "dynamic_context") -> SystemMessage:
    return SystemMessage(content=content, additional_kwargs={marker: True})


def _config(provider: str | None = None) -> RunnableConfig:
    cfg: dict[str, Any] = {"user_id": "u1", "thread_id": "t1"}
    if provider is not None:
        cfg.update(bound_for(LLMProviderName(provider)))
    return cast(RunnableConfig, {"configurable": cfg})


def _agent_config(agent_name: str) -> RunnableConfig:
    return cast(
        RunnableConfig,
        {"configurable": {"user_id": "u1", "thread_id": "t1", "agent_name": agent_name}},
    )


def _store() -> MagicMock:
    return MagicMock()


class TestManageSystemPrompts:
    def test_keeps_latest_static_prompt(self) -> None:
        msgs = [
            _static("old prompt"),
            HumanMessage(content="hi"),
            _static("latest prompt"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        assert [m.content for m in result["messages"]] == ["latest prompt", "hi"]

    def test_keeps_only_latest_dynamic_context(self) -> None:
        msgs = [_dynamic("ctx1"), _dynamic("ctx2"), _dynamic("ctx3")]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        assert [m.content for m in result["messages"]] == ["ctx3"]

    def test_the_legacy_combined_marker_still_reads_as_stable_context(self) -> None:
        msgs = [_dynamic("old", marker="memory_message"), _dynamic("new")]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        assert [m.content for m in result["messages"]] == ["new"]

    def test_leading_slots_lead_in_declaration_order(self) -> None:
        msgs = [
            _dynamic("old ctx"),
            HumanMessage(content="q"),
            SystemMessage(content="onboarding", additional_kwargs={"onboarding_context": True}),
            _dynamic("new ctx"),
            _static("new main"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        assert [m.content for m in result["messages"]] == ["new main", "new ctx", "onboarding", "q"]

    def test_empty_messages(self) -> None:
        state = cast(State, {"messages": []})
        result = manage_system_prompts_node(state, _config(), _store())
        assert result["messages"] == []

    def test_everything_but_the_leading_slots_is_sent_as_written_and_never_pruned(self) -> None:
        """Recall, clock, notes, tool turns: each stays where its turn put it, every copy of it."""
        note = mark(HumanMessage(content="[Surface change]", id="note"), PRESENCE_NOTE_MARKER)
        thread = [
            _with_id(_static("prompt"), "s1"),
            _with_id(_recall("recall 1"), "r1"),
            _with_id(HumanMessage(content="q1"), "h1"),
            _time_message("clock 1", "t1"),
            _with_id(
                AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c"}]), "a1"
            ),
            _with_id(ToolMessage(content="result", tool_call_id="c"), "tool1"),
            _with_id(_static("prompt"), "s2"),
            _with_id(_recall("recall 2"), "r2"),
            note,
            _with_id(HumanMessage(content="q2"), "h2"),
            _time_message("clock 2", "t2"),
        ]

        result = manage_system_prompts_node(cast(State, {"messages": thread}), _config(), _store())

        assert [m.id for m in result["messages"]] == [
            "s2", "r1", "h1", "t1", "a1", "tool1", "r2", "note", "h2", "t2",
        ]  # fmt: skip
        assert result[PRUNED_MESSAGE_IDS_KEY] == ["s1"]

    @pytest.mark.parametrize("provider", ["openai", "openrouter", "gemini", "custom"])
    def test_the_request_is_the_same_on_every_provider(self, provider: str) -> None:
        msgs = [
            _static("prompt"),
            _dynamic("ctx"),
            _recall("mem"),
            HumanMessage(content="hello"),
            AIMessage(content="reply"),
            HumanMessage(content="time", additional_kwargs={"time_context": True}),
        ]
        unbound = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        bound = manage_system_prompts_node(
            cast(State, {"messages": msgs}), _config(provider), _store()
        )
        assert [m.content for m in bound["messages"]] == [m.content for m in unbound["messages"]]
        assert [m.content for m in bound["messages"]] == [
            "prompt", "ctx", "mem", "hello", "reply", "time",
        ]  # fmt: skip

    def test_exception_is_logged_and_state_returned_unmodified(self) -> None:
        """An unexpected failure degrades to the untouched input state instead of crashing the graph, and the cause is logged."""
        msgs = [HumanMessage(content="hello"), _static("latest prompt")]
        state = cast(State, {"messages": msgs})
        with (
            patch(
                "app.agents.core.nodes.manage_system_prompts.slot_of",
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
        assert "unexpected failure" in kwargs.get("error", ""), (
            f"The swallowed exception must be named in the log, got: {kwargs}"
        )

    def test_node_records_the_exact_elapsed_seconds(self) -> None:
        """Two pinned clock reads land exactly 0.5, pinning the direction of the subtraction."""
        labels = {"node": "manage_system_prompts", "agent": "span-test-agent"}
        before = REGISTRY.get_sample_value("graph_node_seconds_sum", labels) or 0.0

        with patch(
            "app.agents.core.nodes.manage_system_prompts.time.perf_counter",
            side_effect=[5.0, 5.5],
        ):
            manage_system_prompts_node(
                cast(State, {"messages": [HumanMessage(content="hello")]}),
                _agent_config("span-test-agent"),
                _store(),
            )

        assert REGISTRY.get_sample_value("graph_node_seconds_sum", labels) == before + 0.5


class _PromptPruning(TypedDict):
    """The prompt_pruning wide-event payload these tests assert on.

    Named rather than dict[str, Any] so a renamed or dropped field breaks
    type-check here instead of silently making every assertion below vacuous —
    the failure mode of a diagnostic nobody notices has stopped working.
    """

    slot_digests: dict[str, str]
    slot_chars: dict[str, int]
    messages_in: int
    messages_out: int
    dropped_system_prompts: int
    kept_static: bool
    kept_dynamic: bool
    kept_onboarding: bool


class TestPromptPruningWideEvent:
    """A changed leading slot is the one thing that still moves the cache boundary, so each is fingerprinted."""

    def _pruning_for(self, msgs: list[AnyMessage]) -> _PromptPruning:
        with patch("app.agents.core.nodes.manage_system_prompts.log") as mock_log:
            manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        return cast(_PromptPruning, mock_log.set.call_args.kwargs["prompt_pruning"])

    def test_slot_sizes_report_each_leading_slot_s_real_length(self) -> None:
        pruning = self._pruning_for(
            [_static("x" * 300), _dynamic("y" * 40), HumanMessage(content="hello")]
        )

        assert pruning["slot_chars"] == {"static": 300, "dynamic_stable": 40}

    def test_a_slot_that_did_not_change_keeps_its_digest(self) -> None:
        first = self._pruning_for([_static("prompt"), _dynamic("ctx")])
        again = self._pruning_for([_static("prompt"), _dynamic("ctx")])

        assert first["slot_digests"] == again["slot_digests"]

    def test_a_slot_whose_content_moved_gets_a_new_digest(self) -> None:
        before = self._pruning_for([_static("prompt"), _dynamic("ctx")])
        after = self._pruning_for([_static("prompt"), _dynamic("ctx CHANGED")])

        assert before["slot_digests"]["static"] == after["slot_digests"]["static"]
        assert before["slot_digests"]["dynamic_stable"] != after["slot_digests"]["dynamic_stable"]

    def test_per_turn_messages_are_not_fingerprinted(self) -> None:
        """They never move the boundary, so a digest of them would only add noise per call."""
        pruning = self._pruning_for([_static("prompt"), _recall("mem"), HumanMessage(content="q")])

        assert set(pruning["slot_digests"]) == {"static"}

    def test_a_kept_slot_is_reported_kept_and_an_absent_one_not(self) -> None:
        pruning = self._pruning_for([_static("prompt"), _dynamic("ctx")])

        assert pruning["kept_static"] is True
        assert pruning["kept_dynamic"] is True
        assert pruning["kept_onboarding"] is False

    def test_every_digest_is_a_fixed_width_fingerprint(self) -> None:
        pruning = self._pruning_for([_static("prompt"), _dynamic("ctx")])

        assert pruning["slot_digests"]
        assert all(len(d) == 8 for d in pruning["slot_digests"].values())

    def test_a_pruned_stale_message_does_not_move_the_digest(self) -> None:
        fresh = _dynamic("the context that is actually sent")
        first = self._pruning_for([_static("p"), _dynamic("stale one"), fresh])
        again = self._pruning_for([_static("p"), _dynamic("stale TWO, different"), fresh])

        assert first["slot_digests"]["dynamic_stable"] == again["slot_digests"]["dynamic_stable"]
        assert first["slot_chars"]["dynamic_stable"] == len("the context that is actually sent")

    def test_the_digests_never_carry_the_content_itself(self) -> None:
        pruning = self._pruning_for([_static("prompt"), _dynamic("hunter2 is the secret")])

        assert "hunter2" not in str(pruning["slot_digests"])

    def test_reports_the_exact_message_and_drop_counts(self) -> None:
        msgs: list[AnyMessage] = [
            _static("p"),
            _dynamic("stale"),
            _dynamic("fresh"),
            HumanMessage(content="hello"),
            HumanMessage(content="t1", additional_kwargs={"time_context": True}),
            HumanMessage(content="t2", additional_kwargs={"time_context": True}),
        ]

        pruning = self._pruning_for(msgs)

        assert pruning["messages_in"] == 6
        assert pruning["messages_out"] == 5
        assert pruning["dropped_system_prompts"] == 1


def _with_id(message: AnyMessage, mid: str) -> AnyMessage:
    message.id = mid
    return message


def _recall(content: str) -> SystemMessage:
    return SystemMessage(content=content, additional_kwargs={"memory_recall": True})


def _time_message(content: str, mid: str) -> AnyMessage:
    return _with_id(HumanMessage(content=content, additional_kwargs={"time_context": True}), mid)


class TestBuildRequest:
    """The pure step, driven directly: what is sent, and which stale copies the checkpoint drops."""

    def test_only_stale_copies_the_checkpoint_holds_are_pruned_but_every_one_is_counted(
        self,
    ) -> None:
        unsaved = _static("static 0")
        saved = [_with_id(_static(f"static {i}"), f"s{i}") for i in (1, 2)]

        request = build_request([unsaved, *saved, _with_id(HumanMessage(content="q"), "h")])

        assert [m.content for m in request.messages] == ["static 2", "q"]
        assert request.pruned_ids == ["s1"]
        assert request.dropped == 2
        assert request.leading == {PromptSlot.STATIC: saved[-1]}

    def test_a_thread_without_leading_slots_is_sent_unchanged(self) -> None:
        thread: list[AnyMessage] = [HumanMessage(content="q"), AIMessage(content="a")]

        request = build_request(thread)

        assert request.messages == thread
        assert request.leading == {}
        assert request.pruned_ids == []
        assert request.dropped == 0
