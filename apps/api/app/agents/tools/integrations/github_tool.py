"""GitHub tools using Composio custom tool infrastructure."""

from typing import Any, Dict, List

from composio import Composio

from shared.py.wide_events import log
from app.models.common_models import GatherContextInput
from app.utils.context_utils import execute_tool


def register_github_custom_tools(composio: Composio) -> List[str]:
    """Register GitHub tools as Composio custom tools."""

    @composio.tools.custom_tool(toolkit="GITHUB")
    def CUSTOM_GATHER_CONTEXT(
        request: GatherContextInput,
        execute_request: Any,
        auth_credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Get GitHub context snapshot: assigned issues, PRs, review requests, notifications.

        Zero required parameters. Returns current GitHub state for situational awareness.
        """
        log.set(tool={"integration": "github", "action": "gather_context"})
        user_id = auth_credentials.get("user_id", "")
        if not user_id:
            raise ValueError("Missing user_id in auth_credentials")

        data = execute_tool(
            "GITHUB_LIST_ISSUES_ASSIGNED_TO_THE_AUTHENTICATED_USER",
            {"per_page": 20, "state": "open"},
            user_id,
        )
        issues = data.get("issues", data.get("items", []))
        prs = [i for i in issues if i.get("pull_request")]
        actual_issues = [i for i in issues if not i.get("pull_request")]

        review_requests: List[Dict[str, Any]] = []
        try:
            reviews_data = execute_tool(
                "GITHUB_SEARCH_GITHUB_ISSUES_AND_PULL_REQUESTS",
                {"q": "is:pr is:open review-requested:@me", "per_page": 10},
                user_id,
            )
            review_requests = reviews_data.get("items", [])
        except Exception as e:
            log.debug(f"GitHub review requests fetch skipped: {e}")

        notifications: List[Dict[str, Any]] = []
        try:
            notif_data = execute_tool(
                "GITHUB_LIST_NOTIFICATIONS",
                {"per_page": 10, "all": False},
                user_id,
            )
            raw = notif_data.get("notifications", notif_data)
            notifications = raw if isinstance(raw, list) else []
        except Exception as e:
            log.debug(f"GitHub notifications fetch skipped: {e}")

        return {
            "assigned_issues": actual_issues,
            "assigned_prs": prs,
            "review_requests": review_requests,
            "notifications": notifications,
        }

    return ["GITHUB_CUSTOM_GATHER_CONTEXT"]
