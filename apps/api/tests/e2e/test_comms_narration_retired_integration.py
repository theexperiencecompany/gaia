"""A retired integration's leftovers must not stop the comms graph re-voicing an executor result.

The narration path runs the real comms graph, whose end-of-graph hook reads the
user's connected integrations. A connected row whose integration was removed from
the catalog (browserbase, PR #876) resolves to a tools-only stub, which raised out
of the hook and made the user see "I couldn't write up the result".
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from langchain_core.messages import HumanMessage
import pytest

from app.agents.core.background.comms_narrator import BACKGROUND_EXECUTOR_NAME
from app.agents.core.integration_capabilities import get_user_integration_capabilities
from app.constants.agents import AgentTag, wrap_agent_payload
from tests.e2e._harness.graph_run import comms_graph, run_graph

pytestmark = pytest.mark.e2e

FOLLOW_UP_NODE = "app.agents.core.nodes.follow_up_actions_node"
CAPABILITIES = "app.agents.core.integration_capabilities"
REVOICED = "Your report is ready."


class _StubOnlyIntegrations:
    async def find_one(self, filter_: dict[str, Any], *_a: object, **_k: object) -> dict | None:
        if filter_.get("integration_id") != "browserbase":
            return None
        return {"_id": ObjectId(), "integration_id": "browserbase", "tools": [{"name": "navigate"}]}


@pytest.mark.regression
async def test_the_executor_result_is_revoiced_despite_an_unresolvable_connected_integration() -> (
    None
):
    narration_turn = {
        "messages": [
            HumanMessage(
                content=wrap_agent_payload(AgentTag.EXECUTOR_RESULT, "Report downloaded."),
                name=BACKGROUND_EXECUTOR_NAME,
            )
        ],
        "todos": [],
    }
    async with comms_graph([REVOICED]) as graph:
        with (
            patch(
                f"{FOLLOW_UP_NODE}.get_user_integration_capabilities",
                new=get_user_integration_capabilities,
            ),
            patch(
                f"{CAPABILITIES}.get_connected_integration_ids",
                AsyncMock(return_value=["browserbase"]),
            ),
            patch(
                "app.db.repositories.base.get_async_collection",
                return_value=_StubOnlyIntegrations(),
            ),
        ):
            run = await run_graph(graph, "", state=narration_turn, is_result_narration=True)

    assert REVOICED in run.final_text()
    assert "end_graph_hooks" in run.visited
