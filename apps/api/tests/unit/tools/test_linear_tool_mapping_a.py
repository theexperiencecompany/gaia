"""Exact-shape tests for the Linear lookup, task-list and issue-context mapping.

``CUSTOM_RESOLVE_CONTEXT``, ``CUSTOM_GET_MY_TASKS``, ``CUSTOM_SEARCH_ISSUES`` and
``CUSTOM_GET_ISSUE_FULL_CONTEXT`` translate GraphQL payloads into result dicts
key by key. Subset assertions ("the count is 1") leave every other mapped key
unpinned, so these tests drive each tool over a rich payload — a distinct value
per field, two items per list — and assert the whole result dict at once.

Harness (``_capture_tools`` and the auth fixtures) is shared with
``test_integration_tools.py``; it is imported rather than re-declared.
"""

from unittest.mock import MagicMock, patch

from app.models.linear_models import (
    GetIssueFullContextInput,
    GetMyTasksInput,
    ResolveContextInput,
    SearchIssuesInput,
)
from tests.unit.tools.test_integration_tools import (
    AUTH_CREDS,
    EXECUTE_REQUEST,
    LINEAR_MODULE,
    _capture_tools,
)


class TestLinearResolveContextMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_resolve_context_maps_every_lookup_into_its_own_slot(self, mock_gql: MagicMock) -> None:
        """Every lookup reads its own GraphQL connection and lands in its own slot."""
        mock_gql.side_effect = [
            {"viewer": {"id": "u1", "name": "Alice Admin", "email": "alice@example.com"}},
            {
                "teams": {
                    "nodes": [
                        {"id": "t1", "name": "Engineering"},
                        {"id": "t2", "name": "Support"},
                    ]
                }
            },
            {
                "users": {
                    "nodes": [
                        {"id": "u2", "name": "Bob Barker", "active": True},
                        {"id": "u3", "name": "Bob Inactive", "active": False},
                        {"id": "u4", "name": "Bob NoFlag"},
                    ]
                }
            },
            {
                "issueLabels": {
                    "nodes": [
                        {"id": "l1", "name": "bug"},
                        {"id": "l2", "name": "feature"},
                    ]
                }
            },
            {
                "projects": {
                    "nodes": [
                        {"id": "p1", "name": "GAIA Core"},
                        {"id": "p2", "name": "Website"},
                    ]
                }
            },
            {
                "workflowStates": {
                    "nodes": [
                        {"id": "s1", "name": "In Progress"},
                        {"id": "s2", "name": "Done"},
                    ]
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_RESOLVE_CONTEXT"]

        result = fn(
            ResolveContextInput(
                team_name="eng",
                user_name="bob",
                label_names=["bug"],
                project_name="gaia",
                state_name="in prog",
                team_id="t1",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert result == {
            "data": {
                "current_user": {
                    "id": "u1",
                    "name": "Alice Admin",
                    "email": "alice@example.com",
                },
                "teams": [{"id": "t1", "name": "Engineering"}],
                "users": [
                    {"id": "u2", "name": "Bob Barker", "active": True},
                    {"id": "u4", "name": "Bob NoFlag"},
                ],
                "labels": [{"id": "l1", "name": "bug"}],
                "projects": [{"id": "p1", "name": "GAIA Core"}],
                "states": [{"id": "s1", "name": "In Progress"}],
            }
        }


class TestLinearGetMyTasksMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_get_my_tasks_sorts_by_priority_then_due_date(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
        """Issues sort by priority then due date; missing values sort last."""
        started = {"type": "started"}
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {
                "issues": {
                    "nodes": [
                        {
                            "id": "i_late",
                            "priority": 2,
                            "state": started,
                            "dueDate": "2024-03-01",
                        },
                        {
                            "id": "i_early",
                            "priority": 2,
                            "state": started,
                            "dueDate": "2024-01-01",
                        },
                        {"id": "i_nodue", "priority": 2, "state": started},
                        {
                            "id": "i_sentinel",
                            "priority": 2,
                            "state": started,
                            "dueDate": "9999-12-31",
                        },
                        {"id": "i_nopriority", "state": started, "dueDate": "2024-02-01"},
                    ]
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_MY_TASKS"]

        result = fn(GetMyTasksInput(), EXECUTE_REQUEST, AUTH_CREDS)

        assert result == {
            "filter": "all",
            "count": 5,
            "issues": [
                {"id": "i_early"},
                {"id": "i_late"},
                {"id": "i_nodue"},
                {"id": "i_sentinel"},
                {"id": "i_nopriority"},
            ],
        }


class TestLinearSearchIssuesMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_search_issues_team_filter_drops_other_teams(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
        """A team filter keeps the requested team's issues, not the others."""
        mock_gql.return_value = {
            "searchIssues": {
                "nodes": [
                    {"id": "i1", "team": {"id": "t1"}, "state": {"type": "started"}},
                    {"id": "i2", "team": {"id": "t2"}, "state": {"type": "started"}},
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_SEARCH_ISSUES"]

        result = fn(SearchIssuesInput(query="test", team_id="t1"), EXECUTE_REQUEST, AUTH_CREDS)

        assert result == {"query": "test", "count": 1, "issues": [{"id": "i1"}]}

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_search_issues_assignee_filter_drops_other_assignees(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
        """An assignee filter keeps that assignee's issues and drops unassigned ones."""
        mock_gql.return_value = {
            "searchIssues": {
                "nodes": [
                    {"id": "i1", "assignee": {"id": "u1"}, "state": {"type": "started"}},
                    {"id": "i2", "assignee": {"id": "u2"}, "state": {"type": "started"}},
                    {"id": "i3", "state": {"type": "started"}},
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_SEARCH_ISSUES"]

        result = fn(SearchIssuesInput(query="test", assignee_id="u1"), EXECUTE_REQUEST, AUTH_CREDS)

        assert result == {"query": "test", "count": 1, "issues": [{"id": "i1"}]}

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_search_issues_state_filter_drops_issues_without_a_state(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
        """An issue carrying no state is filtered out, not crashed on."""
        mock_gql.return_value = {
            "searchIssues": {
                "nodes": [
                    {"id": "i1", "state": {"type": "started"}},
                    {"id": "i2", "state": {"type": "completed"}},
                    {"id": "i3"},
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_SEARCH_ISSUES"]

        result = fn(
            SearchIssuesInput(query="test", state_filter="started"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result == {"query": "test", "count": 1, "issues": [{"id": "i1"}]}


class TestLinearGetIssueFullContextMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_issue_full_context_maps_every_field_to_its_own_slot(
        self, mock_gql: MagicMock
    ) -> None:
        """Every field of a fully populated issue lands in its own slot, once."""
        mock_gql.return_value = {
            "issue": {
                "id": "issue-uuid-1",
                "identifier": "ENG-42",
                "title": "Ship the mapper",
                "description": "Full description text",
                "priority": 2,
                "state": {"name": "In Review"},
                "dueDate": "2024-05-01",
                "estimate": 5,
                "team": {"name": "Engineering"},
                "project": {"name": "GAIA Core"},
                "cycle": {"name": "Cycle 7"},
                "assignee": {"name": "Alice Admin"},
                "creator": {"name": "Bob Barker"},
                "parent": {"identifier": "ENG-1", "title": "Parent epic"},
                "children": {
                    "nodes": [
                        {
                            "identifier": "ENG-43",
                            "title": "Child one",
                            "state": {"name": "Todo"},
                        },
                        {
                            "identifier": "ENG-44",
                            "title": "Child two",
                            "state": {"name": "Done"},
                        },
                    ]
                },
                "relations": {
                    "nodes": [
                        {
                            "type": "blocks",
                            "relatedIssue": {
                                "identifier": "ENG-50",
                                "title": "Blocked issue",
                            },
                        },
                        {
                            "type": "related",
                            "relatedIssue": {
                                "identifier": "ENG-51",
                                "title": "Related issue",
                            },
                        },
                    ]
                },
                "comments": {
                    "nodes": [
                        {
                            "user": {"name": "Carol Commenter"},
                            "body": "First comment",
                            "createdAt": "2024-04-01T00:00:00Z",
                        },
                        {
                            "user": {"name": "Dave Discussant"},
                            "body": "Second comment",
                            "createdAt": "2024-04-02T00:00:00Z",
                        },
                    ]
                },
                "history": {
                    "nodes": [
                        {
                            "createdAt": "2024-04-03T00:00:00Z",
                            "actor": {"name": "Erin Editor"},
                            "fromState": {"name": "Todo"},
                            "toState": {"name": "In Review"},
                        },
                        {
                            "createdAt": "2024-04-04T00:00:00Z",
                            "actor": {"name": "Frank Fixer"},
                            "fromAssignee": {"name": "Gina Gone"},
                            "toAssignee": {"name": "Alice Admin"},
                        },
                        {
                            "createdAt": "2024-04-05T00:00:00Z",
                            "actor": {"name": "Hank Helper"},
                            "addedLabels": [{"id": "l1", "name": "bug"}],
                        },
                        {
                            "createdAt": "2024-04-06T00:00:00Z",
                            "actor": {"name": "Ivy Inspector"},
                            "removedLabels": [{"id": "l2", "name": "stale"}],
                        },
                        {
                            "createdAt": "2024-04-07T00:00:00Z",
                            "actor": {"name": "Jack Nothing"},
                        },
                    ]
                },
                "attachments": {
                    "nodes": [
                        {"title": "spec.pdf", "url": "https://example.com/spec.pdf"},
                        {"title": "design.fig", "url": "https://example.com/design.fig"},
                    ]
                },
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_FULL_CONTEXT"]

        result = fn(GetIssueFullContextInput(issue_id="issue-uuid-1"), EXECUTE_REQUEST, AUTH_CREDS)

        assert result == {
            "issue": {
                "id": "issue-uuid-1",
                "identifier": "ENG-42",
                "title": "Ship the mapper",
                "description": "Full description text",
                "priority": "high",
                "state": "In Review",
                "dueDate": "2024-05-01",
                "estimate": 5,
                "team": "Engineering",
                "project": "GAIA Core",
                "cycle": "Cycle 7",
                "assignee": "Alice Admin",
                "creator": "Bob Barker",
                "parent": {"identifier": "ENG-1", "title": "Parent epic"},
                "sub_issues": [
                    {"identifier": "ENG-43", "title": "Child one", "state": "Todo"},
                    {"identifier": "ENG-44", "title": "Child two", "state": "Done"},
                ],
                "relations": [
                    {
                        "type": "blocks",
                        "issue": {"identifier": "ENG-50", "title": "Blocked issue"},
                    },
                    {
                        "type": "related",
                        "issue": {"identifier": "ENG-51", "title": "Related issue"},
                    },
                ],
                "comments": [
                    {
                        "author": "Carol Commenter",
                        "body": "First comment",
                        "createdAt": "2024-04-01T00:00:00Z",
                    },
                    {
                        "author": "Dave Discussant",
                        "body": "Second comment",
                        "createdAt": "2024-04-02T00:00:00Z",
                    },
                ],
                "activity": [
                    {
                        "timestamp": "2024-04-03T00:00:00Z",
                        "actor": "Erin Editor",
                        "change": "state",
                        "from": "Todo",
                        "to": "In Review",
                    },
                    {
                        "timestamp": "2024-04-04T00:00:00Z",
                        "actor": "Frank Fixer",
                        "change": "assignee",
                        "from": "Gina Gone",
                        "to": "Alice Admin",
                    },
                    {
                        "timestamp": "2024-04-05T00:00:00Z",
                        "actor": "Hank Helper",
                        "change": "labels_added",
                        "labels": ["bug"],
                    },
                    {
                        "timestamp": "2024-04-06T00:00:00Z",
                        "actor": "Ivy Inspector",
                        "change": "labels_removed",
                        "labels": ["stale"],
                    },
                ],
                "attachments": [
                    {"title": "spec.pdf", "url": "https://example.com/spec.pdf"},
                    {"title": "design.fig", "url": "https://example.com/design.fig"},
                ],
            }
        }
