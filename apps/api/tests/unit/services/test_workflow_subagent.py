"""What the workflow-authoring subagent hands back, and the lane it runs on.

The runner replaces the prepare/execute pair the oauth-registered subagents use,
so the two things every handoff has to get right are its own here: it must
inherit the executor's configurable (and with it the run's resolved lane), and it
must never hand ``create_workflow`` an empty string as if it were a draft.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import SystemMessage
import pytest

from app.agents.context.assemble import AssembledContext
from app.constants.llm import WORKFLOW_SUBAGENT_RECURSION_LIMIT
from app.services.workflow.workflow_subagent import WorkflowSubagentRunner

_MOD = "app.services.workflow.workflow_subagent"


@dataclass
class _Run:
    """One execute() call: what it returned and the two calls it made."""

    result: str
    build_config: AsyncMock
    stream_turn: AsyncMock


async def _execute(draft: str, base_configurable: dict | None = None) -> _Run:
    """Drive execute() with everything outside it stubbed at its seams."""
    build_config = AsyncMock(return_value={"configurable": {"thread_id": "workflow_t1"}})
    stream_turn = AsyncMock(return_value=(draft, False))
    with (
        patch(f"{_MOD}.get_workflow_subagent", new_callable=AsyncMock, return_value=MagicMock()),
        patch(f"{_MOD}.build_agent_config", build_config),
        patch(
            f"{_MOD}.assemble_context",
            new_callable=AsyncMock,
            return_value=AssembledContext(
                stable=SystemMessage(content="ctx", additional_kwargs={"dynamic_context": True}),
                volatile=None,
            ),
        ),
        patch(
            f"{_MOD}.build_connected_integrations_hint",
            new_callable=AsyncMock,
            return_value="connected: none",
        ),
        patch.object(WorkflowSubagentRunner, "_stream_turn", stream_turn),
        patch.object(
            WorkflowSubagentRunner,
            "_draft_correction_needed",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await WorkflowSubagentRunner.execute(
            task="every monday, summarize my inbox",
            user_id="u1",
            thread_id="t1",
            user_name="Dev",
            user_timezone="UTC",
            base_configurable=base_configurable,
        )
    return _Run(result=result, build_config=build_config, stream_turn=stream_turn)


@pytest.mark.unit
class TestTheDraftItHandsBack:
    async def test_a_valid_draft_is_returned_verbatim(self) -> None:
        run = await _execute('{"title": "Inbox digest"}')

        assert run.result == '{"title": "Inbox digest"}'

    async def test_an_empty_answer_becomes_a_terminal_string_not_an_empty_draft(self) -> None:
        """``create_workflow`` reads this as the agent's answer; "" would look like
        a successful run that produced nothing."""
        run = await _execute("")

        assert run.result == "Task completed"


@pytest.mark.unit
class TestTheLaneItInherits:
    async def test_it_runs_on_its_parents_configurable(self) -> None:
        """The executor's bag carries the run's resolved lane, so without this a
        pro user's workflow authoring silently drops to the default model."""
        parent = {"user_id": "u1", "lane": {"provider": "openrouter", "model": "paid/model"}}

        run = await _execute('{"title": "x"}', base_configurable=parent)

        assert run.build_config.call_args.kwargs == {
            "conversation_id": "t1",
            "user": {"user_id": "u1", "email": None, "name": "Dev", "timezone": "UTC"},
            "thread_id": "workflow_t1",
            "agent_name": "workflow_agent",
            "subagent_id": "workflow_agent",
            "base_configurable": parent,
        }

    async def test_authoring_runs_on_a_capped_step_budget(self) -> None:
        """A wandering model must reach the forced-finalize fallback quickly rather
        than burning a full agent's recursion budget first."""
        run = await _execute('{"title": "x"}')

        config = run.stream_turn.call_args.args[2]
        assert config["recursion_limit"] == WORKFLOW_SUBAGENT_RECURSION_LIMIT
