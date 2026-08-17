"""The hook chains each tier runs before every LLM call.

The ORDER is the whole subject. Every hook here appends or rewrites messages,
and ``manage_system_prompts_node`` is what places the result into the canonical
slot order — so it has to run last, or whatever an earlier hook appended trails
the system block instead of sitting inside it. That was previously spelled out
at three separate graph builders and enforced by nothing.
"""

import pytest

from app.agents.core.nodes.adapt_media import adapt_media_node
from app.agents.core.nodes.executor_status import executor_status_hook
from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.agents.core.nodes.pre_model_hooks import comms_pre_model_hooks, worker_pre_model_hooks
from app.override.langgraph_bigtool.hooks import HookType


def _todo_hook(state: dict[str, object]) -> dict[str, object]:
    return state


@pytest.mark.unit
class TestTheChainsAreExactlyThese:
    """Spelled out end to end. Every weaker assertion — "contains", "ends with",
    a length check — leaves room for an extra hook, a missing one, or a ``None``
    slipped into the list, and a ``None`` in a hook chain is a crash on the next
    LLM call rather than anything the type checker would catch."""

    def test_comms(self) -> None:
        assert comms_pre_model_hooks() == [
            filter_messages_node,
            executor_status_hook,
            manage_system_prompts_node,
        ]

    def test_a_worker_with_no_todo_channel(self) -> None:
        assert worker_pre_model_hooks() == [
            filter_messages_node,
            adapt_media_node,
            manage_system_prompts_node,
        ]

    def test_a_worker_with_a_todo_channel(self) -> None:
        assert worker_pre_model_hooks(_todo_hook) == [
            filter_messages_node,
            adapt_media_node,
            _todo_hook,
            manage_system_prompts_node,
        ]


@pytest.mark.unit
class TestTheSlotterRunsLast:
    """``manage_system_prompts_node`` places messages by ``PromptSlot``. Anything
    appended after it keeps whatever position it was inserted at, which is the
    defect that made ``todo_context`` land in a different place depending on
    which other slots the turn happened to fill."""

    def test_comms_ends_with_the_slotter(self) -> None:
        assert comms_pre_model_hooks()[-1] is manage_system_prompts_node

    def test_workers_end_with_the_slotter(self) -> None:
        assert worker_pre_model_hooks()[-1] is manage_system_prompts_node

    def test_a_todo_hook_runs_before_the_slotter_not_after(self) -> None:
        chain = worker_pre_model_hooks(_todo_hook)

        assert chain.index(_todo_hook) < chain.index(manage_system_prompts_node)

    def test_the_executor_status_frame_runs_before_the_slotter(self) -> None:
        """Appended after, the frame would trail the system block — where Gemini
        silently discards it along with everything else that follows."""
        chain = comms_pre_model_hooks()

        assert chain.index(executor_status_hook) < chain.index(manage_system_prompts_node)


@pytest.mark.unit
class TestEachTierGetsOnlyItsOwnHooks:
    def test_comms_is_given_the_live_executor_status_frame(self) -> None:
        assert executor_status_hook in comms_pre_model_hooks()

    def test_comms_does_no_media_adaptation(self) -> None:
        """It holds no media-producing tools, so the pass would be dead work on
        every single user-facing turn."""
        assert adapt_media_node not in comms_pre_model_hooks()

    def test_workers_adapt_media(self) -> None:
        assert adapt_media_node in worker_pre_model_hooks()

    def test_workers_are_not_given_the_comms_status_frame(self) -> None:
        assert executor_status_hook not in worker_pre_model_hooks()

    @pytest.mark.parametrize("chain", [comms_pre_model_hooks(), worker_pre_model_hooks()])
    def test_unanswered_tool_calls_are_stripped_first(self, chain: list[HookType]) -> None:
        """Filtering first means every later hook sees a valid array."""
        assert chain[0] is filter_messages_node


@pytest.mark.unit
class TestTheTodoHookIsOptional:
    def test_a_tier_with_no_todo_channel_gets_no_todo_hook(self) -> None:
        """Spawned workers own no todo list, and an authoring-only subagent must
        not plan or execute tasks at all."""
        assert worker_pre_model_hooks() == worker_pre_model_hooks(None)

    def test_supplying_one_adds_exactly_one_hook(self) -> None:
        without = worker_pre_model_hooks()
        with_todo = worker_pre_model_hooks(_todo_hook)

        assert len(with_todo) == len(without) + 1
        assert _todo_hook in with_todo
        assert _todo_hook not in without
