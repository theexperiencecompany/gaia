"""Linear utility functions for API operations.

This module provides helper functions for Linear GraphQL API interactions:
- GraphQL request helper (routed through Composio's proxy)
- Fuzzy name matching for entity resolution
"""

from difflib import SequenceMatcher
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.constants.log_tags import LogTag
from app.models.integrations.linear import (
    LinearGraphQLEnvelope,
    LinearIssueSummary,
    LinearVariables,
)
from app.services.composio.proxy_client import ProxyRequest, proxy_request_sync
from shared.py.wide_events import log

LINEAR_GRAPHQL_ENDPOINT = "https://api.linear.app/graphql"
LINEAR_TOOLKIT = "LINEAR"

DataT = TypeVar("DataT", bound=BaseModel)


def graphql_request(
    query: str,
    variables: LinearVariables | None,
    user_id: str,
    data_model: type[DataT],
) -> DataT:
    """Execute a GraphQL operation against Linear via Composio's proxy and parse its data.

    Raises Exception when the response carries GraphQL errors.
    """
    log.set(operation="graphql_request", endpoint=LINEAR_GRAPHQL_ENDPOINT)

    payload: dict[str, object] = {"query": query}
    if variables is not None:
        payload["variables"] = variables.model_dump(by_alias=True, exclude_unset=True)

    response = LinearGraphQLEnvelope.model_validate(
        proxy_request_sync(
            ProxyRequest(
                user_id=user_id,
                toolkit=LINEAR_TOOLKIT,
                endpoint=LINEAR_GRAPHQL_ENDPOINT,
                method="POST",
                body=payload,
            )
        )
    )

    if response.errors:
        error_messages = [error.message for error in response.errors]
        log.error(f"{LogTag.INTEGRATION} GraphQL errors", error_messages=error_messages)
        raise Exception(f"GraphQL errors: {'; '.join(error_messages)}")

    return data_model.model_validate(response.data)


class _Named(Protocol):
    @property
    def name(self) -> str: ...


NamedT = TypeVar("NamedT", bound=_Named)


def fuzzy_match(
    query: str,
    candidates: list[NamedT],
    limit: int = 3,
    threshold: float = 0.4,
) -> list[NamedT]:
    """Return the candidates whose name best matches query, best first.

    Exact > prefix > substring > SequenceMatcher ratio at or above threshold.
    """
    if not query or not candidates:
        return candidates[:limit] if candidates else []

    query_lower = query.lower().strip()

    scored: list[tuple[NamedT, float]] = []
    for candidate in candidates:
        if not candidate.name:
            continue

        value_lower = candidate.name.lower()

        # Exact match gets highest score
        if value_lower == query_lower:
            scored.append((candidate, 1.0))
            continue

        # Starts with gets high score
        if value_lower.startswith(query_lower):
            scored.append((candidate, 0.9))
            continue

        # Contains gets medium score
        if query_lower in value_lower:
            scored.append((candidate, 0.7))
            continue

        # Sequence matcher for fuzzy matching
        ratio = SequenceMatcher(None, query_lower, value_lower).ratio()
        if ratio >= threshold:
            scored.append((candidate, ratio))

    # Sort by score (descending) and return top matches
    scored.sort(key=lambda x: x[1], reverse=True)
    return [item[0] for item in scored[:limit]]


def priority_to_int(priority: str) -> int:
    """Convert priority string to Linear priority int (0=none, 1=urgent, 4=low)."""
    mapping = {
        "urgent": 1,
        "high": 2,
        "medium": 3,
        "low": 4,
        "none": 0,
    }
    return mapping.get(priority.lower(), 0)


def priority_to_str(priority: int) -> str:
    """Convert Linear priority int to readable string."""
    mapping = {
        0: "none",
        1: "urgent",
        2: "high",
        3: "medium",
        4: "low",
    }
    return mapping.get(priority, "none")


def format_issue_summary(issue: LinearIssueSummary) -> dict[str, object]:
    """Format an issue into a concise summary for LLM consumption."""
    return {
        "id": issue.id,
        "identifier": issue.identifier,
        "title": issue.title,
        "state": issue.state.name,
        "priority": priority_to_str(issue.priority),
        "assignee": issue.assignee.name if issue.assignee else None,
        "dueDate": issue.due_date,
        "team": issue.team.key,
        "cycle": issue.cycle.name if issue.cycle else None,
        "parent": issue.parent.identifier if issue.parent else None,
    }


QUERY_VIEWER = """
query Viewer {
    viewer {
        id
        name
        email
        assignedIssues(filter: { completedAt: { null: true } }) {
            nodes { id }
        }
    }
}
"""

QUERY_TEAMS = """
query Teams {
    teams {
        nodes {
            id
            name
            key
            activeCycle {
                id
                name
                progress
            }
        }
    }
}
"""

QUERY_USERS = """
query Users {
    users {
        nodes {
            id
            name
            email
            active
        }
    }
}
"""

QUERY_LABELS = """
query Labels($teamId: String) {
    issueLabels(filter: { team: { id: { eq: $teamId } } }) {
        nodes {
            id
            name
            color
        }
    }
}
"""

QUERY_LABELS_ALL = """
query LabelsAll {
    issueLabels {
        nodes {
            id
            name
            color
        }
    }
}
"""

QUERY_PROJECTS = """
query Projects {
    projects {
        nodes {
            id
            name
            state
            progress
        }
    }
}
"""

QUERY_STATES = """
query States($teamId: String!) {
    workflowStates(filter: { team: { id: { eq: $teamId } } }) {
        nodes {
            id
            name
            type
            position
        }
    }
}
"""

QUERY_MY_ISSUES = """
query MyIssues($assigneeId: ID!, $includeCompleted: Boolean!, $first: Int!) {
    issues(
        filter: {
            assignee: { id: { eq: $assigneeId } }
            completedAt: { null: $includeCompleted }
        }
        first: $first
    ) {
        nodes {
            id
            identifier
            title
            priority
            state { id name type }
            dueDate
            team { id key name }
            cycle { id name }
            parent { id identifier title }
            assignee { id name }
            slaBreachesAt
        }
    }
}
"""

QUERY_SEARCH_ISSUES = """
query SearchIssues($query: String!, $first: Int!) {
    searchIssues(term: $query, first: $first) {
        nodes {
            id
            identifier
            title
            priority
            state { id name type }
            dueDate
            team { id key name }
            cycle { id name }
            assignee { id name }
            createdAt
        }
    }
}
"""

QUERY_ISSUE_BY_ID = """
query IssueById($id: String!) {
    issue(id: $id) {
        id
        identifier
        title
        description
        priority
        state { id name type }
        dueDate
        estimate
        team { id key name }
        cycle { id name }
        project { id name }
        assignee { id name email }
        creator { id name }
        parent { id identifier title }
        children { nodes { id identifier title state { name } } }
        relations { nodes { id type relatedIssue { id identifier title } } }
        comments { nodes { id body createdAt user { id name } } }
        history(first: 10) {
            nodes {
                id
                createdAt
                actor { id name }
                fromState { id name }
                toState { id name }
                fromAssignee { id name }
                toAssignee { id name }
                addedLabels { id name }
                removedLabels { id name }
            }
        }
        attachments { nodes { id title url } }
    }
}
"""

QUERY_ISSUE_HISTORY = """
query IssueHistory($issueId: String!, $first: Int!) {
    issue(id: $issueId) {
        history(first: $first) {
            nodes {
                id
                createdAt
                actor { id name }
                fromState { id name }
                toState { id name }
                fromAssignee { id name }
                toAssignee { id name }
                fromPriority
                toPriority
                addedLabels { id name }
                removedLabels { id name }
            }
        }
    }
}
"""

QUERY_ACTIVE_CYCLES = """
query ActiveCycles {
    cycles(filter: { isActive: { eq: true } }) {
        nodes {
            id
            name
            number
            startsAt
            endsAt
            progress
            team { id key name }
            issues {
                nodes {
                    id
                    identifier
                    title
                    state { name type }
                    priority
                    assignee { name }
                }
            }
        }
    }
}
"""

QUERY_NOTIFICATIONS = """
query Notifications($first: Int!) {
    notifications(
        first: $first
        orderBy: createdAt
    ) {
        nodes {
            id
            type
            createdAt
            readAt
            ... on IssueNotification {
                issue {
                    id
                    identifier
                    title
                }
            }
            actor { id name }
        }
    }
}
"""

MUTATION_CREATE_ISSUE = """
mutation CreateIssue($input: IssueCreateInput!) {
    issueCreate(input: $input) {
        success
        issue {
            id
            identifier
            title
            url
        }
    }
}
"""

MUTATION_CREATE_RELATION = """
mutation CreateRelation($issueId: String!, $relatedIssueId: String!, $type: IssueRelationType!) {
    issueRelationCreate(input: {
        issueId: $issueId
        relatedIssueId: $relatedIssueId
        type: $type
    }) {
        success
        issueRelation {
            id
            type
        }
    }
}
"""

MUTATION_UPDATE_ISSUES = """
mutation UpdateIssues($issueIds: [UUID!]!, $input: IssueUpdateInput!) {
    issueBatchUpdate(ids: $issueIds, input: $input) {
        success
        issues {
            id
            identifier
            title
        }
    }
}
"""
