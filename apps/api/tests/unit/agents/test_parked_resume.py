"""Resuming a parked background subagent from the decided approval that answers it.

The thread registry is real (fakeredis); the builders and resume_background are the
doubled seams, since what is under test is which run gets rebuilt and resumed.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background.running_registry import RunningSubagents
from app.agents.core.subagents.parked_resume import SubagentResumeError, resume_parked_subagent
from app.models.agent_models import (
    AgentConfigurable,
    RunningSubagent,
    SubagentKind,
    SubagentResumeItem,
)
from app.models.hil_models import HILApprovalRecord
from tests.unit.services.hil.conftest import CONVERSATION_ID, USER_ID, make_record

pytestmark = pytest.mark.unit

MODULE = "app.agents.core.subagents.parked_resume"
THREAD = f"spawn_{CONVERSATION_ID}_call-spawn"
PARENT: AgentConfigurable = {
    "user_id": USER_ID,
    "conversation_id": CONVERSATION_ID,
    "bot_message_id": "bot-1",
}


def _recipe(kind: SubagentKind, integration_id: str = "") -> SubagentResumeItem:
    return {
        "kind": kind,
        "tool_call_id": "call-spawn",
        "task": "draw the flowchart",
        "context": "the user's notes",
        "integration_id": integration_id,
        "inherited_tool_names": ["create_flowchart"],
        "parent_configurable": PARENT,
    }


def _decided(recipe: SubagentResumeItem, thread: str | None = THREAD) -> HILApprovalRecord:
    return make_record(
        status="approved",
        resume_item=None,
        subagent_thread_id=thread,
        subagent_resume=recipe,
    )


@pytest.fixture
def resume() -> Iterator[AsyncMock]:
    with patch(f"{MODULE}.resume_background", new=AsyncMock(return_value=True)) as resumed:
        yield resumed


class TestResumeParkedSubagent:
    async def test_a_spawn_is_rebuilt_by_the_executors_spawner_and_resumed_with_the_decision(
        self, fake_redis: Any, resume: AsyncMock
    ) -> None:
        executor_graph, spawner = MagicMock(), MagicMock()
        rebuilt = MagicMock(name="rebuilt-delegation")
        spawner.build_delegation = AsyncMock(return_value=rebuilt)
        get_graph = AsyncMock(return_value=executor_graph)
        with (
            patch(f"{MODULE}.GraphManager.get_graph", new=get_graph),
            patch(f"{MODULE}.spawner_of", side_effect={executor_graph: spawner}.__getitem__),
        ):
            resumed = await resume_parked_subagent(_decided(_recipe(SubagentKind.SPAWN)))

        assert resumed is True
        get_graph.assert_awaited_once_with("executor_agent")
        spawner.build_delegation.assert_awaited_once_with(
            task="draw the flowchart",
            context="the user's notes",
            parent_configurable=PARENT,
            tool_call_id="call-spawn",
            inherited_tool_names=["create_flowchart"],
        )
        resume.assert_awaited_once_with(
            rebuilt,
            {"status": "approved", "feedback": None, "scope": "once", "approval_id": "appr-1"},
        )

    async def test_an_mcp_handoff_is_rebuilt_by_the_handoff_builder(
        self, fake_redis: Any, resume: AsyncMock
    ) -> None:
        built = MagicMock(name="mcp-delegation")
        with patch(
            f"{MODULE}.build_handoff_delegation", new=AsyncMock(return_value=built)
        ) as build:
            await resume_parked_subagent(
                _decided(_recipe(SubagentKind.MCP, integration_id="linear-mcp"))
            )

        build.assert_awaited_once_with("linear-mcp", "draw the flowchart", PARENT, "call-spawn")
        assert resume.await_args.args[0] is built

    async def test_a_handoff_that_can_no_longer_be_built_raises_its_reason(
        self, fake_redis: Any, resume: AsyncMock
    ) -> None:
        with (
            patch(
                f"{MODULE}.build_handoff_delegation",
                new=AsyncMock(return_value="linear-mcp is no longer connected"),
            ),
            pytest.raises(SubagentResumeError, match="linear-mcp is no longer connected"),
        ):
            await resume_parked_subagent(
                _decided(_recipe(SubagentKind.MCP, integration_id="linear-mcp"))
            )

        resume.assert_not_awaited()

    async def test_a_thread_still_held_by_a_live_run_is_left_to_that_run(
        self, fake_redis: Any, resume: AsyncMock
    ) -> None:
        await RunningSubagents(CONVERSATION_ID).claim(
            RunningSubagent(
                subagent_id="row-1",
                subagent_thread_id=THREAD,
                integration_id="spawn",
                agent_name="spawned_subagent",
                task_summary="",
                started_at="",
            )
        )
        with patch(f"{MODULE}.build_handoff_delegation", new=AsyncMock()) as build:
            resumed = await resume_parked_subagent(_decided(_recipe(SubagentKind.MCP)))

        assert resumed is False
        build.assert_not_awaited()
        resume.assert_not_awaited()

    async def test_the_answer_is_whether_resume_background_could_claim_the_thread(
        self, fake_redis: Any, resume: AsyncMock
    ) -> None:
        resume.return_value = False
        with patch(f"{MODULE}.build_handoff_delegation", new=AsyncMock(return_value=MagicMock())):
            resumed = await resume_parked_subagent(_decided(_recipe(SubagentKind.MCP), thread=None))

        assert resumed is False
        resume.assert_awaited_once()
