"""Slack tools using Composio custom tool infrastructure."""

from datetime import UTC, datetime
from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool
from shared.py.wide_events import log


def register_slack_custom_tools(composio: Composio) -> list[str]:
    """Register Slack tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="SLACK")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, Any],
    ) -> dict[str, Any]:
        """Get Slack workspace context: messages, @mentions, and unread count.

        Zero required parameters. Returns current workspace state for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "slack", "action": "gather_context"})
        user_id = auth_credentials.get("user_id", "")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        slack_query = f"on:{today}"

        data = execute_tool(
            "SLACK_SEARCH_MESSAGES",
            {"query": slack_query, "count": 20},
            user_id,
        )
        messages = data.get("messages", {}).get("matches", [])

        mentions: list[dict[str, Any]] = []
        try:
            mention_data = execute_tool(
                "SLACK_SEARCH_MESSAGES",
                {"query": f"on:{today} @me", "count": 10},
                user_id,
            )
            mentions = mention_data.get("messages", {}).get("matches", [])
        except Exception as e:
            log.debug(f"{LogTag.TOOL} Slack mentions fetch skipped: {e}")

        mention_ts = {m.get("ts") for m in mentions}
        other_messages = [m for m in messages if m.get("ts") not in mention_ts]

        return {
            "messages": other_messages,
            "mentions": mentions,
            # Both lists, because they are disjoint and either one alone
            # under-reports: a day made entirely of @-mentions would otherwise
            # come back as "nothing waiting". Not len(messages) either — the two
            # searches page independently (20 vs 10), so a mention can arrive
            # that the message page never returned.
            "unread_count": len(other_messages) + len(mentions),
        }

    return ["SLACK_CUSTOM_GATHER_CONTEXT"]
