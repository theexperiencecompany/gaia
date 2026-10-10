"""Tests for manage_system_prompts_node after the prompt-ordering rework.

The node now keeps exactly ONE static main prompt and ONE dynamic-context
prompt. Stacking every turn's timestamped dynamic-context message would
shatter the implicit-cache prefix, so older ones are dropped. The legacy
memory_message=True marker is still recognised as a dynamic-context flag
for back-compat with older persisted state.
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

from app.agents.context.slots import PromptSlot
from app.agents.core.nodes.manage_system_prompts import (
    _keep_latest_per_slot,
    _KeptPrompts,
    manage_system_prompts_node,
)
from app.override.langgraph_bigtool.utils import State


def _static(content: str) -> SystemMessage:
    return SystemMessage(content=content)


def _dynamic(content: str, marker: str = "dynamic_context") -> SystemMessage:
    return SystemMessage(content=content, additional_kwargs={marker: True})


def _config(provider: str | None = None) -> RunnableConfig:
    cfg: dict[str, Any] = {"user_id": "u1", "thread_id": "t1"}
    if provider is not None:
        cfg["provider"] = provider
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

    def test_empty_messages(self) -> None:
        state = cast(State, {"messages": []})
        result = manage_system_prompts_node(state, _config(), _store())
        assert result["messages"] == []

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
        """Kept system messages move before any human/ai message, for providers that only promote a leading system run (Gemini)."""
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

    def test_volatile_slots_move_to_tail_for_openai_wire(self) -> None:
        """OpenAI-wire providers move per-turn slots after the conversation so it joins the implicit-cache prefix."""
        msgs = [
            _static("prompt"),
            _dynamic("ctx"),
            SystemMessage(content="todo", additional_kwargs={"todo_context": True}),
            SystemMessage(content="mem", additional_kwargs={"memory_recall": True}),
            HumanMessage(content="hello"),
            AIMessage(content="reply"),
            HumanMessage(content="time", additional_kwargs={"time_context": True}),
        ]
        result = manage_system_prompts_node(
            cast(State, {"messages": msgs}), _config("openrouter"), _store()
        )
        actual = [(m.type, m.content) for m in result["messages"]]
        assert actual == [
            ("system", "prompt"),
            ("system", "ctx"),
            ("human", "hello"),
            ("ai", "reply"),
            ("system", "todo"),
            ("system", "mem"),
            ("human", "time"),
        ]

    def test_leading_layout_preserved_for_gemini(self) -> None:
        """Gemini only promotes a leading contiguous run of SystemMessages, so volatile slots must stay in that leading block."""
        msgs = [
            _static("prompt"),
            _dynamic("ctx"),
            SystemMessage(content="todo", additional_kwargs={"todo_context": True}),
            SystemMessage(content="mem", additional_kwargs={"memory_recall": True}),
            HumanMessage(content="hello"),
            HumanMessage(content="time", additional_kwargs={"time_context": True}),
        ]
        result = manage_system_prompts_node(
            cast(State, {"messages": msgs}), _config("gemini"), _store()
        )
        actual = [(m.type, m.content) for m in result["messages"]]
        assert actual == [
            ("system", "prompt"),
            ("system", "ctx"),
            ("system", "todo"),
            ("system", "mem"),
            ("human", "hello"),
            ("human", "time"),
        ]

    def test_missing_provider_defaults_to_leading_layout(self) -> None:
        """No provider in the config defaults to the safe leading layout."""
        msgs = [
            _static("prompt"),
            _dynamic("ctx"),
            SystemMessage(content="mem", additional_kwargs={"memory_recall": True}),
            HumanMessage(content="hello"),
        ]
        result = manage_system_prompts_node(cast(State, {"messages": msgs}), _config(), _store())
        types = [m.type for m in result["messages"]]
        assert types == ["system", "system", "system", "human"]

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
    dropped_time_context: int
    tail_layout: bool


class TestPromptPruningWideEvent:
    """tail_layout's name and polarity are part of the node's contract: a cache-hit-rate drop is diagnosed with it."""

    def _pruning_for(
        self, msgs: list[AnyMessage], provider: str | None = "openrouter"
    ) -> _PromptPruning:
        with patch("app.agents.core.nodes.manage_system_prompts.log") as mock_log:
            manage_system_prompts_node(cast(State, {"messages": msgs}), _config(provider), _store())
        return cast(_PromptPruning, mock_log.set.call_args.kwargs["prompt_pruning"])

    def _prompt_pruning(self, provider: str | None) -> _PromptPruning:
        return self._pruning_for(
            [_static("prompt"), _dynamic("ctx"), HumanMessage(content="hello")], provider
        )

    def test_openai_wire_request_is_reported_as_the_tail_layout(self) -> None:
        assert self._prompt_pruning("openrouter")["tail_layout"] is True

    def test_gemini_request_is_reported_as_the_leading_layout(self) -> None:
        assert self._prompt_pruning("gemini")["tail_layout"] is False

    def test_slot_sizes_report_each_slot_s_real_length(self) -> None:
        """slot_chars ranks slots by how many bytes they cost on every call, so it must be the slot's real length."""
        pruning = self._pruning_for(
            [_static("x" * 300), _dynamic("y" * 40), HumanMessage(content="hello")]
        )

        assert pruning["slot_chars"]["static"] == 300
        assert pruning["slot_chars"]["dynamic_stable"] == 40

    def test_a_slot_that_did_not_change_keeps_its_digest(self) -> None:
        """Identical bytes must fingerprint identically, or the field cannot tell a stable slot from a churning one."""
        first = self._pruning_for([_static("prompt"), _dynamic("ctx")])
        again = self._pruning_for([_static("prompt"), _dynamic("ctx")])

        assert first["slot_digests"] == again["slot_digests"]

    def test_a_slot_whose_content_moved_gets_a_new_digest(self) -> None:
        """Content that moves must get a new digest, or the cache loss it causes stays invisible."""
        before = self._pruning_for([_static("prompt"), _dynamic("ctx")])
        after = self._pruning_for([_static("prompt"), _dynamic("ctx CHANGED")])

        assert before["slot_digests"]["static"] == after["slot_digests"]["static"]
        assert before["slot_digests"]["dynamic_stable"] != after["slot_digests"]["dynamic_stable"]

    def test_a_slot_holding_several_messages_reports_their_combined_size(self) -> None:
        """The conversation slot's size must account for every message plus the separator between them, not just the first."""
        pruning = self._pruning_for(
            [_static("p"), HumanMessage(content="hello"), AIMessage(content="reply")]
        )

        # "hello" + one separator + "reply"
        assert pruning["slot_chars"]["conversation"] == len("hello") + 1 + len("reply")

    def test_every_digest_is_a_fixed_width_fingerprint(self) -> None:
        """Digests are compared across two requests, so a variable width would make two runs of the same slot incomparable."""
        pruning = self._pruning_for([_static("prompt"), _dynamic("ctx")])

        assert pruning["slot_digests"]
        assert all(len(d) == 8 for d in pruning["slot_digests"].values()), (
            f"expected 8-hex-char digests, got {pruning['slot_digests']}"
        )

    def test_a_pruned_stale_message_does_not_move_the_digest(self) -> None:
        """The digest fingerprints what is sent (the slot's last message), not stale copies pruned before reaching the model."""
        fresh = _dynamic("the context that is actually sent")
        first = self._pruning_for([_static("p"), _dynamic("stale one"), fresh])
        again = self._pruning_for([_static("p"), _dynamic("stale TWO, different"), fresh])

        assert first["slot_digests"]["dynamic_stable"] == again["slot_digests"]["dynamic_stable"]
        assert first["slot_chars"]["dynamic_stable"] == len("the context that is actually sent")

    def test_the_digests_never_carry_the_content_itself(self) -> None:
        """Digests ship to the log pipeline on every model call, and slot text is user data."""
        pruning = self._pruning_for([_static("prompt"), _dynamic("hunter2 is the secret")])

        assert "hunter2" not in str(pruning["slot_digests"])

    def test_reports_the_exact_message_and_prune_counts(self) -> None:
        """messages_in, messages_out and the two drop counters are contract in both name and value."""
        msgs = [
            _static("p"),
            _dynamic("stale"),
            _dynamic("fresh"),
            HumanMessage(content="hello"),
            HumanMessage(content="t1", additional_kwargs={"time_context": True}),
            HumanMessage(content="t2", additional_kwargs={"time_context": True}),
        ]

        pruning = self._pruning_for(msgs)

        assert pruning["messages_in"] == 6
        assert pruning["messages_out"] == 4
        assert pruning["dropped_system_prompts"] == 1
        assert pruning["dropped_time_context"] == 1


def _with_id(message: AnyMessage, mid: str) -> AnyMessage:
    message.id = mid
    return message


def _time_message(content: str, mid: str) -> AnyMessage:
    return _with_id(HumanMessage(content=content, additional_kwargs={"time_context": True}), mid)


class TestKeepLatestPerSlot:
    """The prune step, driven directly.

    manage_system_prompts_node only ever hands the helper one message per slot,
    so the drop accounting and the returned pruned_ids are unobservable through
    it. These feed it stacked slots and assert every _KeptPrompts field exactly.
    """

    def test_singleton_slots_keep_the_last_message_and_count_their_drops(self) -> None:
        statics = [_with_id(_static(f"static {i}"), f"s{i}") for i in range(3)]
        times = [_time_message(f"time {i}", f"t{i}") for i in range(4)]
        conversation = [
            _with_id(HumanMessage(content="hello"), "c0"),
            _with_id(AIMessage(content="reply"), "c1"),
        ]
        by_slot: dict[PromptSlot, list[AnyMessage]] = {
            PromptSlot.STATIC: statics,
            PromptSlot.CONVERSATION: conversation,
            PromptSlot.TIME: times,
        }

        kept: _KeptPrompts = _keep_latest_per_slot(
            by_slot, (PromptSlot.STATIC, PromptSlot.CONVERSATION, PromptSlot.TIME)
        )

        assert kept.messages == [statics[-1], *conversation, times[-1]]
        assert kept.by_slot == {
            PromptSlot.STATIC: [statics[-1]],
            PromptSlot.CONVERSATION: conversation,
            PromptSlot.TIME: [times[-1]],
        }
        assert kept.pruned_ids == ["s0", "s1", "t0", "t1", "t2"]
        assert kept.dropped_system == 2
        assert kept.dropped_time == 3

    def test_slots_absent_from_the_input_produce_an_empty_result(self) -> None:
        kept = _keep_latest_per_slot({}, (PromptSlot.STATIC, PromptSlot.TIME))

        assert kept == _KeptPrompts([], {}, [], 0, 0)
