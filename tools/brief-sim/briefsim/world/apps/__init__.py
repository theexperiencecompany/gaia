"""The fake apps behind the fake Composio: each turns world state into the provider's own response."""

from typing import Final

#: Composio tool slugs each fake toolkit implements; the vendored schemas list exactly these.
SIMULATED_SLUGS: Final[dict[str, list[str]]] = {
    "GITHUB": [
        "GITHUB_FIND_PULL_REQUESTS",
        "GITHUB_GET_THE_AUTHENTICATED_USER",
        "GITHUB_LIST_ISSUES_ASSIGNED_TO_THE_AUTHENTICATED_USER",
        "GITHUB_LIST_NOTIFICATIONS_FOR_THE_AUTHENTICATED_USER",
        "GITHUB_SEARCH_ISSUES_AND_PULL_REQUESTS",
    ],
    "TODOIST": [
        "TODOIST_FILTER_TASKS",
        "TODOIST_GET_ALL_PROJECTS",
        "TODOIST_GET_ALL_TASKS",
        "TODOIST_GET_USER",
    ],
}
