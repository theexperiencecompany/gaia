"""GitHub tools using Composio custom tool infrastructure."""

from typing import Any

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool
from app.utils.json_helpers import list_bag, text_bag
from shared.py.wide_events import log


def register_github_custom_tools(composio: Composio[Any, Any]) -> list[str]:
    """Register GitHub tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GITHUB")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: ExecuteRequestFn,
        auth_credentials: dict[str, object],
    ) -> dict[str, object]:
        """Get GitHub context snapshot: assigned issues, PRs, review requests, notifications.

        Zero required parameters. Returns current GitHub state for situational awareness.
        """
        del request, execute_request  # unused: framework-mandated custom-tool signature
        log.set(tool={"integration": "github", "action": "gather_context"})
        user_id = text_bag(auth_credentials, "user_id")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        data = execute_tool(
            "GITHUB_LIST_ISSUES_ASSIGNED_TO_THE_AUTHENTICATED_USER",
            {"per_page": 20, "state": "open"},
            user_id,
        )
        issues = list_bag(data, "issues") or list_bag(data, "items")
        prs = [i for i in issues if isinstance(i, dict) and i.get("pull_request")]
        actual_issues = [i for i in issues if isinstance(i, dict) and not i.get("pull_request")]

        review_requests: list[dict[str, object]] = []
        try:
            reviews_data = execute_tool(
                "GITHUB_SEARCH_GITHUB_ISSUES_AND_PULL_REQUESTS",
                {"q": "is:pr is:open review-requested:@me", "per_page": 10},
                user_id,
            )
            review_requests = [r for r in list_bag(reviews_data, "items") if isinstance(r, dict)]
        except Exception as e:
            log.debug(
                f"{LogTag.TOOL} GitHub review requests fetch skipped", error_type=type(e).__name__
            )

        notifications: list[dict[str, object]] = []
        try:
            notif_data = execute_tool(
                "GITHUB_LIST_NOTIFICATIONS",
                {"per_page": 10, "all": False},
                user_id,
            )
            raw = notif_data.get("notifications", notif_data)
            notifications = raw if isinstance(raw, list) else []
        except Exception as e:
            log.debug(
                f"{LogTag.TOOL} GitHub notifications fetch skipped", error_type=type(e).__name__
            )

        return {
            "assigned_issues": actual_issues,
            "assigned_prs": prs,
            "review_requests": review_requests,
            "notifications": notifications,
        }

    return ["GITHUB_CUSTOM_GATHER_CONTEXT"]
