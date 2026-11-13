"""GitHub tools using Composio custom tool infrastructure."""

from composio import Composio
from composio.types import ExecuteRequestFn

from app.constants.log_tags import LogTag
from app.models.common_models import GatherContextInput
from app.models.integrations.composio import CustomToolAuthCredentials
from app.models.integrations.github import (
    GitHubIssue,
    GitHubIssueList,
    GitHubNotification,
    GitHubNotificationList,
)
from app.utils.context_utils import execute_tool
from shared.py.wide_events import log


def _passthrough(items: list[GitHubIssue] | list[GitHubNotification]) -> list[dict[str, object]]:
    # JSON-native fields: python and json dumps are identical
    return [item.model_dump(mode="json", exclude_unset=True) for item in items]  # pragma: no mutate


def register_github_custom_tools(composio: Composio) -> list[str]:
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
        user_id = CustomToolAuthCredentials.parse(auth_credentials).user_id

        issues = GitHubIssueList.model_validate(
            execute_tool(
                "GITHUB_LIST_ISSUES_ASSIGNED_TO_THE_AUTHENTICATED_USER",
                {"per_page": 20, "state": "open"},
                user_id,
            )
        ).all
        prs = [i for i in issues if i.pull_request is not None]
        actual_issues = [i for i in issues if i.pull_request is None]

        review_requests: list[GitHubIssue] = []
        try:
            review_requests = GitHubIssueList.model_validate(
                execute_tool(
                    "GITHUB_SEARCH_GITHUB_ISSUES_AND_PULL_REQUESTS",
                    {"q": "is:pr is:open review-requested:@me", "per_page": 10},
                    user_id,
                )
            ).all
        except Exception as e:
            log.debug(
                f"{LogTag.TOOL} GitHub review requests fetch skipped", error_type=type(e).__name__
            )

        notifications: list[GitHubNotification] = []
        try:
            notifications = GitHubNotificationList.model_validate(
                execute_tool(
                    "GITHUB_LIST_NOTIFICATIONS",
                    {"per_page": 10, "all": False},
                    user_id,
                )
            ).notifications
        except Exception as e:
            log.debug(
                f"{LogTag.TOOL} GitHub notifications fetch skipped", error_type=type(e).__name__
            )

        return {
            "assigned_issues": _passthrough(actual_issues),
            "assigned_prs": _passthrough(prs),
            "review_requests": _passthrough(review_requests),
            "notifications": _passthrough(notifications),
        }

    return ["GITHUB_CUSTOM_GATHER_CONTEXT"]
