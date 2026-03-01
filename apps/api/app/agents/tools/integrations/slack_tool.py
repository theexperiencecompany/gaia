"""Slack tools using Composio custom tool infrastructure.

These tools provide Slack functionality using the access_token from Composio's
auth_credentials. Uses Slack Web API for all operations.

Note: Errors are raised as exceptions - Composio wraps responses automatically.
"""

from typing import Any, Dict, List

import httpx
from composio import Composio

from app.models.common_models import GatherContextInput

SLACK_API_BASE = "https://slack.com/api"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=30)


def register_slack_custom_tools(composio: Composio) -> List[str]:
    """Register Slack tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="SLACK")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get Slack workspace context: user info, unread channels, and DMs.

        Zero required parameters. Returns current workspace state for situational awareness.
        """
        token = auth_credentials.get("access_token")
        if not token:
            raise ValueError("Missing access_token in auth_credentials")
        headers = {"Authorization": f"Bearer {token}"}

        # Get authenticated user info
        auth_resp = _http_client.get(
            f"{SLACK_API_BASE}/auth.test",
            headers=headers,
        )
        auth_resp.raise_for_status()
        auth_data = auth_resp.json()

        # Get channels (public + private) with unread info
        channels_resp = _http_client.get(
            f"{SLACK_API_BASE}/conversations.list",
            headers=headers,
            params={
                "types": "public_channel,private_channel",
                "limit": 20,
                "exclude_archived": "true",
            },
        )
        channels_resp.raise_for_status()
        channels_data = channels_resp.json()
        channels = channels_data.get("channels", [])

        # Get direct messages
        ims_resp = _http_client.get(
            f"{SLACK_API_BASE}/conversations.list",
            headers=headers,
            params={"types": "im", "limit": 10},
        )
        ims_resp.raise_for_status()
        ims_data = ims_resp.json()
        ims = ims_data.get("channels", [])

        all_convos = channels + ims
        unread_channels = [
            {
                "id": c.get("id"),
                "name": c.get("name", "DM"),
                "unread_count": c.get("unread_count", 0),
            }
            for c in all_convos
            if c.get("unread_count", 0) > 0
        ][:10]

        return {
            "user": {
                "id": auth_data.get("user_id"),
                "name": auth_data.get("user"),
                "team": auth_data.get("team"),
                "team_id": auth_data.get("team_id"),
            },
            "unread_channels": unread_channels,
            "channel_count": len(channels),
            "dm_count": len(ims),
        }

    return ["SLACK_CUSTOM_GATHER_CONTEXT"]
