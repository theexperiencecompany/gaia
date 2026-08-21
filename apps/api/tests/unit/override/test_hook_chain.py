"""The pre-model hook chain: that it threads state, and that order is kept.

Each hook rewrites the message list on its way to the model, and each one's
contract assumes the previous ones already ran:

* ``filter_messages_node`` strips unanswered tool calls — if it ran *after*
  ``manage_system_prompts_node`` the provider would receive a dangling tool call
  and reject the whole request, so the user's message appears to vanish;
* ``adapt_media_node`` rewrites media blocks for the model lane;
* the todo hook re-renders the plan and appends it, marked;
* ``manage_system_prompts_node`` runs LAST and collapses each system slot to its
  latest copy, which only works once every earlier hook has added theirs.

Nothing asserted that they run in order. ``test_graph_builder`` checks only
``len(pre_model_hooks) == 4``, which any four callables in any order satisfy;
the one real order assertion in the repo is comms-only and integration-tier.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.override.langgraph_bigtool.hooks import execute_hooks


def _recorder(name: str, calls: list[str]):
    """A sync hook that records itself and appends to the threaded state."""

    def hook(state: dict[str, Any], config: Any, store: Any) -> dict[str, Any]:
        calls.append(name)
        return {**state, "messages": [*state.get("messages", []), name]}

    return hook


def _async_recorder(name: str, calls: list[str]):
    async def hook(state: dict[str, Any], config: Any, store: Any) -> dict[str, Any]:
        calls.append(name)
        return {**state, "messages": [*state.get("messages", []), name]}

    return hook


class TestExecuteHooks:
    async def test_hooks_run_in_declaration_order(self):
        calls: list[str] = []
        hooks = [_recorder("first", calls), _recorder("second", calls), _recorder("third", calls)]

        await execute_hooks(hooks, {"messages": []}, {}, MagicMock())

        assert calls == ["first", "second", "third"]

    async def test_each_hook_sees_the_previous_hooks_output(self):
        """The chain is a pipeline, not a fan-out. If state were not threaded,
        every hook would operate on the original messages and only the last
        one's rewrite would survive."""
        calls: list[str] = []
        hooks = [_recorder("a", calls), _recorder("b", calls)]

        state = await execute_hooks(hooks, {"messages": ["start"]}, {}, MagicMock())

        assert state["messages"] == ["start", "a", "b"]

    async def test_sync_and_async_hooks_chain_together(self):
        """The chain mixes both — a sync hook after an async one must receive
        the awaited result, not a coroutine object."""
        calls: list[str] = []
        hooks = [_async_recorder("async", calls), _recorder("sync", calls)]

        state = await execute_hooks(hooks, {"messages": []}, {}, MagicMock())

        assert calls == ["async", "sync"]
        assert state["messages"] == ["async", "sync"]

    async def test_no_hooks_returns_the_state_untouched(self):
        original = {"messages": ["only"]}

        assert await execute_hooks(None, original, {}, MagicMock()) is original
        assert await execute_hooks([], original, {}, MagicMock()) is original


class TestDeclaredChains:
    """The order each graph declares. Asserted by identity against the real node
    objects, so renaming or reordering a hook fails here rather than in a
    provider rejection three layers away.
    """

    @staticmethod
    async def _captured(builder: str) -> dict[str, Any]:
        from app.agents.core.graph_builder import build_graph as bg
        from tests.e2e._harness.graph_run import scripted_model

        captured: dict[str, Any] = {}

        def _capture(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock(compile=MagicMock(return_value=MagicMock()))

        from app.agents.tools.core.registry import init_tool_registry
        from app.core.lazy_loader import providers

        if not providers.is_initialized("tool_registry"):
            init_tool_registry()

        from langgraph.store.memory import InMemoryStore

        with (
            patch.object(bg, "get_tools_store", AsyncMock(return_value=InMemoryStore())),
            patch.object(bg, "get_checkpointer_manager", AsyncMock(return_value=None)),
            patch.object(bg, "create_agent", side_effect=_capture),
        ):
            async with getattr(bg, builder)(
                chat_llm=scripted_model(["hi"]), in_memory_checkpointer=True
            ):
                pass
        return captured

    @classmethod
    async def _hooks_for(cls, builder: str) -> list[Any]:
        return list((await cls._captured(builder))["pre_model_hooks"])

    async def test_the_executor_filters_before_it_manages_prompts(self):
        """``filter_messages_node`` must run first. After the prompt manager, a
        dangling tool call reaches the provider and the request is rejected —
        the user's turn fails with no visible cause."""
        from app.agents.core.nodes.adapt_media import adapt_media_node
        from app.agents.core.nodes.filter_messages import filter_messages_node
        from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node

        hooks = await self._hooks_for("build_executor_graph")

        assert hooks[0] is filter_messages_node
        assert hooks[1] is adapt_media_node
        assert hooks.index(filter_messages_node) < hooks.index(manage_system_prompts_node)

    async def test_the_prompt_manager_runs_last_so_it_can_slot_what_others_added(self):
        """Every hook that emits a system message — the todo plan, the comms
        status frame — appends it marked and lets the prompt manager place it.
        A hook that ran afterwards would have to place its own message, and its
        position would then depend on which other slots that turn happened to
        fill, which is how ``todo_context`` used to land in a different position
        depending on whether a background-executor frame was present."""
        from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node

        hooks = await self._hooks_for("build_executor_graph")

        assert len(hooks) == 4
        assert hooks[-1] is manage_system_prompts_node

    async def test_comms_slots_the_executor_status_before_the_prompt_manager(self):
        """The status frame is a system message that must be slotted, not
        appended — Gemini drops any SystemMessage after a non-system message, so
        a status frame added afterwards is silently never seen."""
        from app.agents.core.nodes.executor_status import executor_status_hook
        from app.agents.core.nodes.filter_messages import filter_messages_node
        from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node

        hooks = await self._hooks_for("build_comms_graph")

        assert hooks == [filter_messages_node, executor_status_hook, manage_system_prompts_node]

    async def test_comms_does_not_carry_the_executor_only_hooks(self):
        """Comms has no todos and no media lane. Carrying those hooks would cost
        every chat turn work it cannot use."""
        from app.agents.core.nodes.adapt_media import adapt_media_node

        hooks = await self._hooks_for("build_comms_graph")

        assert adapt_media_node not in hooks
        assert len(hooks) == 3


class TestEndGraphHooks:
    """What runs after the model, and in what order.

    Both comms end hooks are invisible to a route assertion: the node name
    appears as long as *either* is wired, so dropping one silently keeps the
    graph looking correct. Asserted by identity for that reason.
    """

    async def test_comms_generates_follow_ups_and_learns_from_the_turn(self):
        """Passive ingestion is how a fact mentioned in passing is retained.
        Without it, only what the agent explicitly saves via add_memory
        persists, and conversational disclosures are lost."""
        from app.agents.core.nodes import memory_node
        from app.agents.core.nodes.follow_up_actions_node import follow_up_actions_node

        captured = await TestDeclaredChains._captured("build_comms_graph")

        assert list(captured["end_graph_hooks"]) == [follow_up_actions_node, memory_node]

    async def test_the_executor_has_no_end_graph_hooks(self):
        """The executor's output is not user-facing, so follow-up chips and
        conversational ingestion would both be wrong there — and its runs are
        long, so the cost would be paid on every delegation."""
        captured = await TestDeclaredChains._captured("build_executor_graph")

        assert not captured.get("end_graph_hooks")
