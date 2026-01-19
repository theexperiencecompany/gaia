"""Linear utility functions for API operations.

This module provides helper functions for Linear GraphQL API interactions including:
- Access token extraction and header generation
- GraphQL request helper
- Fuzzy name matching for entity resolution
"""

from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import httpx

from app.config.loggers import general_logger as logger

LINEAR_GRAPHQL_ENDPOINT = "https://api.linear.app/graphql"

# Reusable sync HTTP client
_http_client = httpx.Client(timeout=30)


def get_access_token(auth_credentials: Dict[str, Any]) -> str:
    """Extract access token from auth_credentials."""
    token = auth_credentials.get("access_token")
    if not token:
        raise ValueError("Missing access_token in auth_credentials")
    return token


def auth_headers(access_token: str) -> Dict[str, str]:
    """Return headers for Linear GraphQL API requests."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def graphql_request(
    query: str,
    variables: Optional[Dict[str, Any]],
    auth_credentials: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute a GraphQL request against Linear's API.

    Args:
        query: GraphQL query or mutation string
        variables: Optional variables for the query
        auth_credentials: Auth credentials containing access_token

    Returns:
        The 'data' field from the GraphQL response

    Raises:
        Exception: If the request fails or returns errors
    """
    access_token = get_access_token(auth_credentials)
    headers = auth_headers(access_token)

    payload: Dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables

    resp = _http_client.post(
        LINEAR_GRAPHQL_ENDPOINT,
        headers=headers,
        json=payload,
    )
    resp.raise_for_status()
    result = resp.json()

    if "errors" in result:
        error_messages = [e.get("message", str(e)) for e in result["errors"]]
        logger.error(
            f"GraphQL Errors: {error_messages} Query: {query} Variables: {variables}"
        )
        raise Exception(f"GraphQL errors: {'; '.join(error_messages)}")

    return result.get("data", {})


def fuzzy_match(
    query: str,
    candidates: List[Dict[str, Any]],
    key: str,
    limit: int = 3,
    threshold: float = 0.4,
) -> List[Dict[str, Any]]:
    """
    Fuzzy match a query string against a list of candidates.

    Args:
        query: The search query
        candidates: List of dicts to search through
        key: The key in each dict to match against
        limit: Maximum number of results to return
        threshold: Minimum similarity score (0-1) to include

    Returns:
        List of matching candidates sorted by similarity (best first)
    """
    if not query or not candidates:
        return candidates[:limit] if candidates else []

    query_lower = query.lower().strip()

    scored = []
    for candidate in candidates:
        value = candidate.get(key, "")
        if not value:
            continue

        value_lower = str(value).lower()

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


def format_issue_summary(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Format an issue into a concise summary for LLM consumption."""
    return {
        "id": issue.get("id"),
        "identifier": issue.get("identifier"),
        "title": issue.get("title"),
        "state": issue.get("state", {}).get("name") if issue.get("state") else None,
        "priority": priority_to_str(issue.get("priority", 0)),
        "assignee": issue.get("assignee", {}).get("name")
        if issue.get("assignee")
        else None,
        "dueDate": issue.get("dueDate"),
        "team": issue.get("team", {}).get("key") if issue.get("team") else None,
        "cycle": issue.get("cycle", {}).get("name") if issue.get("cycle") else None,
        "parent": issue.get("parent", {}).get("identifier")
        if issue.get("parent")
        else None,
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

QUERY_ISSUE_BY_IDENTIFIER = """
query IssueByIdentifier($identifier: String!) {
    issue(id: $identifier) {
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
