"""Trello tools using Composio custom tool infrastructure.

These tools provide Trello functionality using the access_token from Composio's
auth_credentials. Uses Trello REST API v1 for all operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List

import httpx
from composio import Composio

from app.models.common_models import GatherContextInput

TRELLO_API_BASE = "https://api.trello.com/1"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=30)


def register_trello_custom_tools(composio: Composio) -> List[str]:
    """Register Trello tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="TRELLO")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Trello context snapshot: user info, open boards, and assigned cards.

        Zero required parameters. Returns current board state for situational awareness.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")
        headers = {"Authorization": f"Bearer {token}"}

        # Get authenticated member info
        me_resp = _http_client.get(
            f"{TRELLO_API_BASE}/members/me",
            headers=headers,
            params={"fields": "id,username,fullName,email"},
        )
        me_resp.raise_for_status()
        me_data = me_resp.json()

        # Get open boards
        boards_resp = _http_client.get(
            f"{TRELLO_API_BASE}/members/me/boards",
            headers=headers,
            params={"filter": "open", "fields": "id,name,shortUrl"},
        )
        boards_resp.raise_for_status()
        boards: List[Dict[str, Any]] = boards_resp.json()

        # Get cards assigned to user
        cards_resp = _http_client.get(
            f"{TRELLO_API_BASE}/members/me/cards",
            headers=headers,
            params={
                "filter": "visible",
                "limit": 10,
                "fields": "id,name,idBoard,due,dateLastActivity",
            },
        )
        cards_resp.raise_for_status()
        cards: List[Dict[str, Any]] = cards_resp.json()

        return {
            "user": {
                "id": me_data.get("id"),
                "username": me_data.get("username"),
                "fullName": me_data.get("fullName"),
                "email": me_data.get("email"),
            },
            "boards": [
                {"id": b.get("id"), "name": b.get("name"), "url": b.get("shortUrl")}
                for b in boards
            ],
            "my_cards": [
                {"id": c.get("id"), "name": c.get("name"), "due": c.get("due")}
                for c in cards
            ],
            "board_count": len(boards),
            "card_count": len(cards),
        }

    return ["TRELLO_CUSTOM_GATHER_CONTEXT"]
