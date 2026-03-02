"""Trello tools using Composio custom tool infrastructure."""

from typing import Any, Dict, List

from composio import Composio

from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool


def register_trello_custom_tools(composio: Composio) -> List[str]:
    """Register Trello tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="TRELLO")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Trello context snapshot: cards assigned to the current user.

        Zero required parameters. Returns current board state for situational awareness.
        """
        user_id = auth_credentials.get("user_id", "")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        data = execute_tool(
            "TRELLO_GET_MEMBERS_CARDS_BY_ID_MEMBER",
            {"idMember": "me"},
            user_id,
        )
        cards = data if isinstance(data, list) else data.get("cards", [])
        return {"cards": cards}

    return ["TRELLO_CUSTOM_GATHER_CONTEXT"]
