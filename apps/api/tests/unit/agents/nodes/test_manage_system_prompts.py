"""Tests for manage_system_prompts_node after the prompt-ordering rework.

The node now keeps exactly ONE static main prompt and ONE dynamic-context
prompt. Stacking every turn's timestamped dynamic-context message would
shatter the implicit-cache prefix, so older ones are dropped. The legacy
``memory_message=True`` marker is still recognised as a dynamic-context flag
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

from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
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
        """Kept system messages must appear BEFORE any human/ai message for
        providers that only promote a leading system run (Gemini).

        On 4.2.0 ``langchain-google-genai``'s ``_parse_chat_history`` collects
        every ``SystemMessage`` into ``system_instruction`` whatever its
        position, so this is no longer about content loss (an older comment
        here claimed it was). It is about keeping ONE canonical order: the node
        rewrites the list as ``[static, dynamic, ...non_system...]`` so the
        cached prefix is the same bytes every turn rather than depending on
        where a hook happened to append.
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

    def test_volatile_slots_move_to_tail_for_openai_wire(self) -> None:
        """OpenAI-wire providers (OpenRouter / custom — the production default
        route) accept system messages anywhere, so the per-turn slots move AFTER
        the conversation: ``[static, dynamic, ...conversation, todo,
        memory_recall, time]``. The conversation then joins the provider's
        implicit-cache prefix instead of re-sending uncached every turn.
        """
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
        """Gemini only promotes a leading contiguous run of SystemMessages to
        ``system_instruction`` and silently drops the rest — so on that lane the
        volatile slots must stay in the leading block even though it costs the
        conversation its place in the cached prefix."""
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
        """No provider in the config (defensive) must not change today's
        behavior — the leading layout is the safe default everywhere."""
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
        """The node runs on every agent turn, so an unexpected failure degrades
        to the untouched input state instead of crashing the graph — but it must
        never disappear silently: the cause has to reach the logs."""
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


class _PromptPruning(TypedDict):
    """The ``prompt_pruning`` wide-event payload these tests assert on.

    Named rather than ``dict[str, Any]`` so a renamed or dropped field breaks
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
    """``tail_layout`` is the field a cache-hit-rate drop is diagnosed with, so
    both its name and its polarity are part of the node's contract."""

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
        """``slot_chars`` exists to rank slots by how many bytes they cost on
        every call, so a size that is not the slot's real length ranks them
        wrongly and points the next investigation at the wrong slot."""
        pruning = self._pruning_for(
            [_static("x" * 300), _dynamic("y" * 40), HumanMessage(content="hello")]
        )

        assert pruning["slot_chars"]["static"] == 300
        assert pruning["slot_chars"]["dynamic_stable"] == 40

    def test_a_slot_that_did_not_change_keeps_its_digest(self) -> None:
        """The whole point: identical bytes must fingerprint identically, or the
        field cannot tell a stable slot from a churning one."""
        first = self._pruning_for([_static("prompt"), _dynamic("ctx")])
        again = self._pruning_for([_static("prompt"), _dynamic("ctx")])

        assert first["slot_digests"] == again["slot_digests"]

    def test_a_slot_whose_content_moved_gets_a_new_digest(self) -> None:
        """And the converse — otherwise a churning slot reads as stable and the
        cache loss it causes stays invisible."""
        before = self._pruning_for([_static("prompt"), _dynamic("ctx")])
        after = self._pruning_for([_static("prompt"), _dynamic("ctx CHANGED")])

        assert before["slot_digests"]["static"] == after["slot_digests"]["static"]
        assert before["slot_digests"]["dynamic_stable"] != after["slot_digests"]["dynamic_stable"]

    def test_a_slot_holding_several_messages_reports_their_combined_size(self) -> None:
        """The conversation is the one slot that accumulates, and it is the one
        whose size actually grows, so the size has to account for every message
        in it plus the separator between them — not just the first."""
        pruning = self._pruning_for(
            [_static("p"), HumanMessage(content="hello"), AIMessage(content="reply")]
        )

        # "hello" + one separator + "reply"
        assert pruning["slot_chars"]["conversation"] == len("hello") + 1 + len("reply")

    def test_every_digest_is_a_fixed_width_fingerprint(self) -> None:
        """Digests are compared across two requests by eye and by script. A
        variable width means two runs of the same slot are not comparable."""
        pruning = self._pruning_for([_static("prompt"), _dynamic("ctx")])

        assert pruning["slot_digests"]
        assert all(len(d) == 8 for d in pruning["slot_digests"].values()), (
            f"expected 8-hex-char digests, got {pruning['slot_digests']}"
        )

    def test_a_pruned_stale_message_does_not_move_the_digest(self) -> None:
        """The digest must fingerprint what is SENT, not what arrives.

        A singleton slot keeps only its last message; the rest are pruned and
        never reach the model. Hashing the whole group makes the digest move
        when a stale copy differs even though the sent bytes are identical —
        a false "this slot churned" in exactly the case the field exists to
        diagnose, since a stacked slot IS the pruning case.
        """
        fresh = _dynamic("the context that is actually sent")
        first = self._pruning_for([_static("p"), _dynamic("stale one"), fresh])
        again = self._pruning_for([_static("p"), _dynamic("stale TWO, different"), fresh])

        assert first["slot_digests"]["dynamic_stable"] == again["slot_digests"]["dynamic_stable"]
        assert first["slot_chars"]["dynamic_stable"] == len("the context that is actually sent")

    def test_the_digests_never_carry_the_content_itself(self) -> None:
        """These fields ship to the log pipeline on every model call, and slot
        text is user data."""
        pruning = self._pruning_for([_static("prompt"), _dynamic("hunter2 is the secret")])

        assert "hunter2" not in str(pruning["slot_digests"])
