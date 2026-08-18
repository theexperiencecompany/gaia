"""Exact-shape tests for the Linear create/relation/activity mapping layer.

The tools in ``linear_tool.py`` translate GraphQL payloads into result dicts key
by key. Subset assertions ("the id is right") leave every other mapped key
unpinned, so these tests drive each tool over a rich payload — a distinct value
per field, two items per list — and assert the whole result dict at once.

Harness (``_capture_tools`` and the auth fixtures) is shared with
``test_integration_tools.py``; it is imported rather than re-declared.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models.linear_models import (
    CreateIssueInput,
    CreateIssueRelationInput,
    CreateIssueSubItem,
    CreateSubIssuesInput,
    GetIssueActivityInput,
    SubIssueItem,
)
from tests.unit.tools.test_integration_tools import (
    AUTH_CREDS,
    EXECUTE_REQUEST,
    LINEAR_MODULE,
    _capture_tools,
)


class TestLinearCreateIssueMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_issue_with_sub_issues_exact_shape(self, mock_gql: MagicMock) -> None:
        """Every mapped field of the parent and of each sub-issue, plus the mutations sent."""
        mock_gql.side_effect = [
            {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": "issue-main",
                        "identifier": "ENG-10",
                        "title": "Parent title",
                        "url": "https://linear.app/eng/issue/ENG-10",
                    },
                }
            },
            {
                "issueCreate": {
                    "success": True,
                    "issue": {"id": "issue-sub-1", "identifier": "ENG-11", "title": "Sub one"},
                }
            },
            {
                "issueCreate": {
                    "success": True,
                    "issue": {"id": "issue-sub-2", "identifier": "ENG-12", "title": "Sub two"},
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_CREATE_ISSUE"]

        request = CreateIssueInput(
            team_id="team-7",
            title="Parent title",
            description="Parent description",
            sub_issues=[
                CreateIssueSubItem(
                    title="Sub one",
                    description="Sub one description",
                    assignee_id="user-1",
                    priority=1,
                ),
                CreateIssueSubItem(
                    title="Sub two",
                    description="Sub two description",
                    assignee_id="user-2",
                    priority=4,
                ),
            ],
        )
        result = fn(request, EXECUTE_REQUEST, AUTH_CREDS)

        assert result == {
            "issue": {
                "id": "issue-main",
                "identifier": "ENG-10",
                "title": "Parent title",
                "url": "https://linear.app/eng/issue/ENG-10",
            },
            "sub_issues": [
                {"id": "issue-sub-1", "identifier": "ENG-11", "title": "Sub one"},
                {"id": "issue-sub-2", "identifier": "ENG-12", "title": "Sub two"},
            ],
        }
        assert [call.args[1] for call in mock_gql.call_args_list[1:]] == [
            {
                "input": {
                    "teamId": "team-7",
                    "title": "Sub one",
                    "parentId": "issue-main",
                    "description": "Sub one description",
                    "assigneeId": "user-1",
                    "priority": 1,
                }
            },
            {
                "input": {
                    "teamId": "team-7",
                    "title": "Sub two",
                    "parentId": "issue-main",
                    "description": "Sub two description",
                    "assigneeId": "user-2",
                    "priority": 4,
                }
            },
        ]


class TestLinearCreateSubIssuesMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_sub_issues_resolves_identifier_exact_shape(self, mock_gql: MagicMock) -> None:
        """Parent resolved from its identifier, then every sub-issue field mapped back."""
        mock_gql.side_effect = [
            {"teams": {"nodes": [{"issue": {"id": "parent-99"}}]}},
            {"issue": {"id": "parent-99", "team": {"id": "team-7"}}},
            {
                "issueCreate": {
                    "success": True,
                    "issue": {"id": "issue-sub-1", "identifier": "ENG-21", "title": "Sub one"},
                }
            },
            {
                "issueCreate": {
                    "success": True,
                    "issue": {"id": "issue-sub-2", "identifier": "ENG-22", "title": "Sub two"},
                }
            },
        ]

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_CREATE_SUB_ISSUES"]

        result = fn(
            CreateSubIssuesInput(
                parent_identifier="ENG-9",
                sub_issues=[
                    SubIssueItem(
                        title="Sub one",
                        description="Sub one description",
                        assignee_id="user-1",
                        priority=1,
                    ),
                    SubIssueItem(
                        title="Sub two",
                        description="Sub two description",
                        assignee_id="user-2",
                        priority=4,
                    ),
                ],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert result == {
            "parent": "ENG-9",
            "created_count": 2,
            "sub_issues": [
                {"id": "issue-sub-1", "identifier": "ENG-21", "title": "Sub one"},
                {"id": "issue-sub-2", "identifier": "ENG-22", "title": "Sub two"},
            ],
        }
        assert [call.args[1] for call in mock_gql.call_args_list] == [
            {"teamKey": "ENG", "number": 9.0},
            {"id": "parent-99"},
            {
                "input": {
                    "teamId": "team-7",
                    "title": "Sub one",
                    "parentId": "parent-99",
                    "description": "Sub one description",
                    "assigneeId": "user-1",
                    "priority": 1,
                }
            },
            {
                "input": {
                    "teamId": "team-7",
                    "title": "Sub two",
                    "parentId": "parent-99",
                    "description": "Sub two description",
                    "assigneeId": "user-2",
                    "priority": 4,
                }
            },
        ]

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_sub_issues_identifier_matches_no_team(self, mock_gql: MagicMock) -> None:
        """An identifier that resolves to no team leaves the parent unresolved."""
        mock_gql.return_value = {"teams": {"nodes": []}}

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_CREATE_SUB_ISSUES"]

        with pytest.raises(ValueError, match="Could not resolve parent"):
            fn(
                CreateSubIssuesInput(
                    parent_identifier="ENG-9",
                    sub_issues=[SubIssueItem(title="Sub one")],
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )


class TestLinearCreateIssueRelationMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_relation_exact_shape(self, mock_gql: MagicMock) -> None:
        """The id comes from the API; the rest of the relation echoes the request."""
        mock_gql.return_value = {
            "issueRelationCreate": {
                "success": True,
                "issueRelation": {"id": "relation-77", "type": "blocked_by"},
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_CREATE_ISSUE_RELATION"]

        result = fn(
            CreateIssueRelationInput(
                issue_id="issue-a",
                related_issue_id="issue-b",
                relation_type="is_blocked_by",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert result == {
            "relation": {
                "id": "relation-77",
                "type": "is_blocked_by",
                "from_issue": "issue-a",
                "to_issue": "issue-b",
            },
        }


class TestLinearGetIssueActivityMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_activity_exact_shape_across_change_types(self, mock_gql: MagicMock) -> None:
        """One entry per change kind, each field distinct, asserted as a whole."""
        mock_gql.return_value = {
            "issue": {
                "history": {
                    "nodes": [
                        {
                            "createdAt": "2024-01-01T09:00:00Z",
                            "actor": {"name": "Alice"},
                            "fromState": {"name": "Todo"},
                            "toState": {"name": "In Progress"},
                            "fromAssignee": None,
                            "toAssignee": None,
                            "fromPriority": None,
                            "toPriority": None,
                            "addedLabels": None,
                            "removedLabels": None,
                        },
                        {
                            "createdAt": "2024-01-02T10:00:00Z",
                            "actor": {"name": "Bob"},
                            "fromState": None,
                            "toState": None,
                            "fromAssignee": {"name": "Carol"},
                            "toAssignee": {"name": "Dave"},
                            "fromPriority": None,
                            "toPriority": None,
                            "addedLabels": None,
                            "removedLabels": None,
                        },
                        {
                            "createdAt": "2024-01-03T11:00:00Z",
                            "actor": None,
                            "fromState": None,
                            "toState": None,
                            "fromAssignee": None,
                            "toAssignee": None,
                            "fromPriority": 1,
                            "toPriority": 3,
                            "addedLabels": None,
                            "removedLabels": None,
                        },
                    ]
                }
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ISSUE_ACTIVITY"]

        result = fn(GetIssueActivityInput(issue_id="issue-1"), EXECUTE_REQUEST, AUTH_CREDS)

        assert result == {
            "issue": "issue-1",
            "activity_count": 3,
            "activities": [
                {
                    "timestamp": "2024-01-01T09:00:00Z",
                    "actor": "Alice",
                    "change_type": "state",
                    "from": "Todo",
                    "to": "In Progress",
                },
                {
                    "timestamp": "2024-01-02T10:00:00Z",
                    "actor": "Bob",
                    "change_type": "assignee",
                    "from": "Carol",
                    "to": "Dave",
                },
                {
                    "timestamp": "2024-01-03T11:00:00Z",
                    "actor": "System",
                    "change_type": "priority",
                    "from": "urgent",
                    "to": "medium",
                },
            ],
        }
