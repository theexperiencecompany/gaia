"""Attacks on SubagentJoinMiddleware — landed work must be collected, running work must not block.

Two failure modes, pulling opposite directions:
* the model ends the turn with LANDED-but-uncollected subagent work (results in
  the bucket, or a parked approval) — without the forced join it is stranded;
* the model rests while subagents are STILL RUNNING ("dispatched — I'll report
  when it's done") — forcing the join here would trap the executor in a
  blocking-poll loop; their landing queues a collection turn instead.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage
import pytest

from app.agents.middleware.subagent_join import SubagentJoinMiddleware

MODULE = "app.agents.middleware.subagent_join"

CONFIGURABLE = {
    "stream_id": "stream-1",
    "conversation_id": "conv-1",
    "user_id": "507f1f77bcf86cd799439011",
}


def _state(response: AIMessage) -> dict[str, Any]:
    return {"messages": [response]}


def _with_config(configurable: dict[str, Any]) -> Any:
    return patch(f"{MODULE}.get_config", return_value={"configurable": configurable})


@pytest.mark.unit
class TestForcedJoin:
    async def test_landed_results_force_the_join_on_a_bare_final_answer(self) -> None:
        response = AIMessage(content="All done!")
        with (
            _with_config(CONFIGURABLE),
            patch(f"{MODULE}.get_pending_subagents", return_value=0),
            patch(f"{MODULE}.has_bg_subagent_results", AsyncMock(return_value=True)),
        ):
            await SubagentJoinMiddleware().aafter_model(_state(response), MagicMock())

        assert [call["name"] for call in response.tool_calls] == ["wait_for_subagents"]

    async def test_finish_task_is_dropped_while_parked_approvals_exist(self) -> None:
        # finish_task short-circuits routing before the join could ever run, so
        # it must be replaced, not appended to.
        response = AIMessage(
            content="",
            tool_calls=[{"name": "finish_task", "args": {}, "id": "ft-1"}],
        )
        with (
            _with_config(CONFIGURABLE),
            patch(f"{MODULE}.get_pending_subagents", return_value=0),
            patch(f"{MODULE}.has_bg_subagent_results", AsyncMock(return_value=False)),
            patch(
                f"{MODULE}.list_parked_subagents_for_conversation",
                AsyncMock(return_value=[MagicMock()]),
            ),
        ):
            await SubagentJoinMiddleware().aafter_model(_state(response), MagicMock())

        assert [call["name"] for call in response.tool_calls] == ["wait_for_subagents"]

    async def test_still_running_subagents_allow_the_model_to_rest(self) -> None:
        # The Claude Code contract: dispatch, answer now, get woken on landing.
        # Forcing the join here would block the turn on long-running work.
        response = AIMessage(content="Dispatched — I'll report when they finish.")
        listing = AsyncMock(return_value=[MagicMock()])
        with (
            _with_config(CONFIGURABLE),
            patch(f"{MODULE}.get_pending_subagents", return_value=2),
            patch(f"{MODULE}.list_parked_subagents_for_conversation", listing),
        ):
            await SubagentJoinMiddleware().aafter_model(_state(response), MagicMock())

        assert response.tool_calls == []
        assert listing.await_count == 0  # not even consulted — running wins

    async def test_a_final_answer_with_no_background_work_is_untouched(self) -> None:
        response = AIMessage(content="All done!")
        with (
            _with_config(CONFIGURABLE),
            patch(f"{MODULE}.get_pending_subagents", return_value=0),
            patch(f"{MODULE}.has_bg_subagent_results", AsyncMock(return_value=False)),
            patch(
                f"{MODULE}.list_parked_subagents_for_conversation",
                AsyncMock(return_value=[]),
            ),
        ):
            await SubagentJoinMiddleware().aafter_model(_state(response), MagicMock())

        assert response.tool_calls == []

    async def test_real_tool_calls_are_never_rewritten(self) -> None:
        # The turn is not ending — the model is still working. Forcing the join
        # here would drop its actual next action.
        response = AIMessage(
            content="",
            tool_calls=[{"name": "GMAIL_SEND_EMAIL", "args": {}, "id": "tc-1"}],
        )
        with (
            _with_config(CONFIGURABLE),
            patch(f"{MODULE}.get_pending_subagents", return_value=0),
            patch(f"{MODULE}.has_bg_subagent_results", AsyncMock(return_value=True)),
        ):
            await SubagentJoinMiddleware().aafter_model(_state(response), MagicMock())

        assert [call["name"] for call in response.tool_calls] == ["GMAIL_SEND_EMAIL"]

    async def test_headless_runs_collect_results_but_ignore_parked_records(self) -> None:
        # A background (workflow/cron) run can't have parked its own subagents —
        # the gate denies instead of parking there. Conversation-scoped parked
        # records would belong to some other context; do not collect them here.
        response = AIMessage(content="Done.")
        listing = AsyncMock(return_value=[MagicMock()])
        with (
            _with_config({**CONFIGURABLE, "execution_mode": "background"}),
            patch(f"{MODULE}.get_pending_subagents", return_value=0),
            patch(f"{MODULE}.has_bg_subagent_results", AsyncMock(return_value=False)),
            patch(f"{MODULE}.list_parked_subagents_for_conversation", listing),
        ):
            await SubagentJoinMiddleware().aafter_model(_state(response), MagicMock())

        assert response.tool_calls == []
        assert listing.await_count == 0
