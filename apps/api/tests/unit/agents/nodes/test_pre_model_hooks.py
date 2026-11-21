"""The hook chains each tier runs before every LLM call.

The ORDER is the whole subject. manage_system_prompts_node builds the request the
model sees, so it has to run last, or whatever an earlier hook rewrote never
reaches the model. That was previously spelled out at three separate graph
builders and enforced by nothing.
"""

import pytest

from app.agents.core.background.executor_channel import drain_inbox_hook
from app.agents.core.background.subagent_channel import drain_subagent_inbox_hook
from app.agents.core.nodes.adapt_media import adapt_media_node
from app.agents.core.nodes.drain_conversation_log import drain_conversation_log_hook
from app.agents.core.nodes.filter_messages import filter_messages_node
from app.agents.core.nodes.manage_system_prompts import manage_system_prompts_node
from app.agents.core.nodes.pre_model_hooks import comms_pre_model_hooks, worker_pre_model_hooks
from app.override.langgraph_bigtool.hooks import HookType


@pytest.mark.unit
class TestTheChainsAreExactlyThese:
    """Spelled out end to end: a weaker assertion leaves room for an extra, missing, or None hook to slip through."""

    def test_comms(self) -> None:
        """Its live-work status rides the turn-start context; only inputs the step absorbed join mid-run."""
        assert comms_pre_model_hooks() == [
            filter_messages_node,
            drain_conversation_log_hook,
            manage_system_prompts_node,
        ]

    def test_a_worker(self) -> None:
        assert worker_pre_model_hooks() == [
            filter_messages_node,
            adapt_media_node,
            manage_system_prompts_node,
        ]

    def test_the_executor_drains_its_inbox(self) -> None:
        assert worker_pre_model_hooks(drains_inbox=True) == [
            filter_messages_node,
            adapt_media_node,
            drain_inbox_hook,
            manage_system_prompts_node,
        ]

    def test_a_subagent_drains_its_own_mailbox(self) -> None:
        assert worker_pre_model_hooks(drains_subagent_inbox=True) == [
            filter_messages_node,
            adapt_media_node,
            drain_subagent_inbox_hook,
            manage_system_prompts_node,
        ]


@pytest.mark.unit
class TestTheRequestBuilderRunsLast:
    """manage_system_prompts_node builds the request; anything after it would never reach the model."""

    @pytest.mark.parametrize(
        "chain",
        [
            comms_pre_model_hooks(),
            worker_pre_model_hooks(),
            worker_pre_model_hooks(drains_inbox=True),
            worker_pre_model_hooks(drains_subagent_inbox=True),
        ],
        ids=["comms", "worker", "executor", "subagent"],
    )
    def test_every_chain_ends_with_it(self, chain: list[HookType]) -> None:
        assert chain[-1] is manage_system_prompts_node


@pytest.mark.unit
class TestEachTierGetsOnlyItsOwnHooks:
    def test_comms_does_no_media_adaptation(self) -> None:
        """It holds no media-producing tools, so the pass would be dead work every turn."""
        assert adapt_media_node not in comms_pre_model_hooks()

    def test_workers_adapt_media(self) -> None:
        assert adapt_media_node in worker_pre_model_hooks()

    def test_a_worker_drains_no_inbox_unless_asked(self) -> None:
        chain = worker_pre_model_hooks()

        assert drain_inbox_hook not in chain
        assert drain_subagent_inbox_hook not in chain

    @pytest.mark.parametrize("chain", [comms_pre_model_hooks(), worker_pre_model_hooks()])
    def test_unanswered_tool_calls_are_stripped_first(self, chain: list[HookType]) -> None:
        """Filtering first means every later hook sees a valid array."""
        assert chain[0] is filter_messages_node
