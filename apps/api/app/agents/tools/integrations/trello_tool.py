"""Trello tools using Composio custom tool infrastructure."""

from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool
from app.utils.json_helpers import text_bag


def register_trello_custom_tools(composio: Composio[Any, Any]) -> list[str]:  # type: ignore[explicit-any]
    """Register Trello tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="TRELLO")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Trello context snapshot: cards assigned to the current user.

        Zero required parameters. Returns current board state for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        user_id = text_bag(auth_credentials, "user_id")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        # execute_tool declares -> dict[str, object], but this endpoint's real payload
        # can come back as a bare list — widen before narrowing.
        data: dict[str, object] | list[object] = execute_tool(
            "TRELLO_GET_MEMBERS_CARDS_BY_ID_MEMBER",
            {"idMember": "me"},
            user_id,
        )
        cards = data if isinstance(data, list) else data.get("cards", [])
        return {"cards": cards}

    return ["TRELLO_CUSTOM_GATHER_CONTEXT"]
