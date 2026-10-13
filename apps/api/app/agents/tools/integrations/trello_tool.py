"""Trello tools using Composio custom tool infrastructure."""

from composio import Composio
from composio.types import ExecuteRequestFn

from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.trello import TrelloCardList
from app.utils.context_utils import execute_tool


def register_trello_custom_tools(composio: Composio) -> list[str]:
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        # execute_tool declares -> dict[str, Any], but this endpoint's real payload
        # can come back as a bare list — the model's before-validator wraps it.
        cards = TrelloCardList.model_validate(
            execute_tool(
                "TRELLO_GET_MEMBERS_CARDS_BY_ID_MEMBER",
                {"idMember": "me"},
                user_id,
            )
        ).cards
        return {
            "cards": [
                c.model_dump(  # pragma: no mutate -- dropping mode= is unobservable here and banned by tool-dump-boundary
                    mode="json",  # pragma: no mutate -- JSON-native fields only, so any mode value dumps identically
                )
                for c in cards
            ]
        }

    return ["TRELLO_CUSTOM_GATHER_CONTEXT"]
