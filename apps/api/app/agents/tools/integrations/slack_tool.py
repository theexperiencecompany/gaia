"""Slack tools using Composio custom tool infrastructure."""

from datetime import UTC, datetime

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.slack import SlackSearchMatch, SlackSearchResult
from app.utils.context_utils import execute_tool
from shared.py.wide_events import log


def register_slack_custom_tools(composio: Composio) -> list[str]:
    """Register Slack tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="SLACK")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get Slack workspace context: messages, @mentions, and unread count.

        Zero required parameters. Returns current workspace state for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "slack", "action": "gather_context"})
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        slack_query = f"on:{today}"

        messages = SlackSearchResult.model_validate(
            execute_tool(
                "SLACK_SEARCH_MESSAGES",
                {"query": slack_query, "count": 20},
                user_id,
            )
        ).messages.matches

        mentions: list[SlackSearchMatch] = []
        try:
            mentions = SlackSearchResult.model_validate(
                execute_tool(
                    "SLACK_SEARCH_MESSAGES",
                    {"query": f"on:{today} @me", "count": 10},
                    user_id,
                )
            ).messages.matches
        except Exception as e:
            log.debug(f"{LogTag.TOOL} Slack mentions fetch skipped", error_type=type(e).__name__)

        mention_ts = {m.ts for m in mentions}
        other_messages = [m for m in messages if m.ts not in mention_ts]

        # A match is all strings, so the json mode the tool-dump-boundary lint pins here
        # dumps exactly what python mode would -- hence the pragmas.
        return {
            "messages": [
                m.model_dump(mode="json", exclude_unset=True)  # pragma: no mutate
                for m in other_messages
            ],
            "mentions": [
                m.model_dump(mode="json", exclude_unset=True)  # pragma: no mutate
                for m in mentions
            ],
            # Sum both lists: they're disjoint, and the two searches page
            # independently (20 vs 10), so a mention can arrive that the
            # message page never returned.
            "unread_count": len(other_messages) + len(mentions),
        }

    return ["SLACK_CUSTOM_GATHER_CONTEXT"]
