"""Exact-shape tests for the Linear sprint/bulk/notification/context mapping layer.

The tools in ``linear_tool.py`` translate GraphQL payloads into result dicts key
by key. Subset assertions ("the count is right") leave every other mapped key
unpinned, so these tests drive each tool over a rich payload — a distinct value
per field, two items per list — and assert the whole result dict at once.

Harness (``_capture_tools`` and the auth fixtures) is shared with
``test_integration_tools.py``; it is imported rather than re-declared.
"""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, call, patch

from app.models.common_models import GatherContextInput
from app.models.linear_models import (
    BulkUpdateIssuesInput,
    GetActiveSprintInput,
    GetNotificationsInput,
    GetWorkspaceContextInput,
)
from tests.unit.tools.test_integration_tools import (
    AUTH_CREDS,
    EXECUTE_REQUEST,
    LINEAR_MODULE,
    _capture_tools,
)

# ── Shared Linear payload builders (workspace context + gather context) ───────


def _linear_viewer(assigned_issue_ids: list[str]) -> dict[str, Any]:
    """The viewer node returned by QUERY_VIEWER."""
    return {
        "id": "viewer-1",
        "name": "Alice",
        "email": "alice@example.com",
        "assignedIssues": {"nodes": [{"id": i} for i in assigned_issue_ids]},
    }


def _linear_team_nodes() -> list[dict[str, Any]]:
    """Two teams: one mid-cycle, one with no active cycle."""
    return [
        {
            "id": "team-1",
            "name": "Engineering",
            "key": "ENG",
            "activeCycle": {"name": "Sprint 5", "progress": 0.4567},
        },
        {"id": "team-2", "name": "Design", "key": "DES"},
    ]


def _linear_my_issue_nodes(yesterday: str, tomorrow: str) -> list[dict[str, Any]]:
    """Issues covering every urgent bucket plus the terminal states that are skipped."""
    return [
        {
            "id": "issue-1",
            "identifier": "ENG-1",
            "title": "Fix login",
            "state": {"name": "In Progress", "type": "started"},
            "priority": 1,
            "assignee": {"name": "Alice"},
            "dueDate": yesterday,
            "team": {"key": "ENG"},
            "cycle": {"name": "Sprint 5"},
            "parent": {"identifier": "ENG-0"},
            "slaBreachesAt": "2024-06-01T00:00:00Z",
        },
        {
            "id": "issue-2",
            "identifier": "ENG-2",
            "title": "Add cache",
            "state": {"name": "Todo", "type": "unstarted"},
            "priority": 2,
            "dueDate": tomorrow,
        },
        {
            "id": "issue-3",
            "identifier": "ENG-3",
            "title": "Shipped",
            "state": {"name": "Done", "type": "completed"},
            "priority": 1,
            "dueDate": yesterday,
            "slaBreachesAt": "2024-06-02T00:00:00Z",
        },
        {
            "id": "issue-4",
            "identifier": "ENG-4",
            "title": "Dropped",
            "state": {"name": "Canceled", "type": "canceled"},
            "priority": 2,
            "dueDate": yesterday,
            "slaBreachesAt": "2024-06-03T00:00:00Z",
        },
        {
            "id": "issue-5",
            "identifier": "ENG-5",
            "title": "Later",
            "state": {"name": "Backlog", "type": "backlog"},
            "priority": 3,
        },
    ]


def _expected_overdue_summary(yesterday: str) -> dict[str, Any]:
    """format_issue_summary() of the overdue, urgent, SLA-breaching issue."""
    return {
        "id": "issue-1",
        "identifier": "ENG-1",
        "title": "Fix login",
        "state": "In Progress",
        "priority": "urgent",
        "assignee": "Alice",
        "dueDate": yesterday,
        "team": "ENG",
        "cycle": "Sprint 5",
        "parent": "ENG-0",
    }


def _expected_high_priority_summary(tomorrow: str) -> dict[str, Any]:
    """format_issue_summary() of the high-priority issue that is not yet due."""
    return {
        "id": "issue-2",
        "identifier": "ENG-2",
        "title": "Add cache",
        "state": "Todo",
        "priority": "high",
        "assignee": None,
        "dueDate": tomorrow,
        "team": None,
        "cycle": None,
        "parent": None,
    }


class TestLinearActiveSprintMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_active_sprint_maps_every_field(self, mock_gql: MagicMock) -> None:
        """Every cycle and issue field is mapped exactly, including bucket counts."""
        mock_gql.return_value = {
            "cycles": {
                "nodes": [
                    {
                        "id": "cycle-77",
                        "name": "Sprint 5",
                        "number": 5,
                        "startsAt": "2024-01-01T00:00:00Z",
                        "endsAt": "2024-01-15T00:00:00Z",
                        "progress": 0.4567,
                        "team": {"id": "team-1", "name": "Engineering", "key": "ENG"},
                        "issues": {
                            "nodes": [
                                {
                                    "identifier": "ENG-1",
                                    "title": "Fix login",
                                    "priority": 1,
                                    "assignee": {"name": "Alice"},
                                    "state": {"type": "started"},
                                },
                                {
                                    "identifier": "ENG-2",
                                    "title": "Add cache",
                                    "priority": 2,
                                    "state": {"type": "started"},
                                },
                                {
                                    "identifier": "ENG-3",
                                    "title": "Write docs",
                                    "priority": 3,
                                    "assignee": {"name": "Bob"},
                                    "state": {"type": "unstarted"},
                                },
                                {
                                    "identifier": "ENG-4",
                                    "title": "Default state",
                                    "priority": 4,
                                    "assignee": {"name": "Carol"},
                                    "state": {},
                                },
                                {
                                    "identifier": "ENG-5",
                                    "title": "Someday",
                                    "priority": 0,
                                    "assignee": {"name": "Dan"},
                                    "state": {"type": "backlog"},
                                },
                                {
                                    "identifier": "ENG-6",
                                    "title": "Shipped",
                                    "priority": 1,
                                    "assignee": {"name": "Erin"},
                                    "state": {"type": "completed"},
                                },
                            ]
                        },
                    }
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ACTIVE_SPRINT"]

        result = fn(GetActiveSprintInput(), EXECUTE_REQUEST, AUTH_CREDS)

        assert result == {
            "sprint_count": 1,
            "sprints": [
                {
                    "id": "cycle-77",
                    "name": "Sprint 5",
                    "number": 5,
                    "team": "Engineering",
                    "team_key": "ENG",
                    "starts_at": "2024-01-01T00:00:00Z",
                    "ends_at": "2024-01-15T00:00:00Z",
                    "progress": 45.7,
                    "total_issues": 6,
                    "issues_by_state": {
                        "backlog": 1,
                        "unstarted": 2,
                        "started": 2,
                        "completed": 1,
                    },
                    "in_progress": [
                        {
                            "identifier": "ENG-1",
                            "title": "Fix login",
                            "priority": "urgent",
                            "assignee": "Alice",
                        },
                        {
                            "identifier": "ENG-2",
                            "title": "Add cache",
                            "priority": "high",
                            "assignee": None,
                        },
                    ],
                    "todo": [
                        {
                            "identifier": "ENG-3",
                            "title": "Write docs",
                            "priority": "medium",
                            "assignee": "Bob",
                        },
                        {
                            "identifier": "ENG-4",
                            "title": "Default state",
                            "priority": "low",
                            "assignee": "Carol",
                        },
                    ],
                }
            ],
        }

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_active_sprint_team_filter_keeps_the_matching_cycle(
        self, mock_gql: MagicMock
    ) -> None:
        """The team filter keeps the cycle whose team matches, not the others."""
        mock_gql.return_value = {
            "cycles": {
                "nodes": [
                    {
                        "id": "cycle-eng",
                        "name": "Eng Sprint",
                        "number": 1,
                        "startsAt": "2024-01-01",
                        "endsAt": "2024-01-15",
                        "progress": 0.0,
                        "team": {"id": "team-1", "name": "Engineering", "key": "ENG"},
                        "issues": {"nodes": []},
                    },
                    {
                        "id": "cycle-des",
                        "name": "Design Sprint",
                        "number": 2,
                        "startsAt": "2024-01-01",
                        "endsAt": "2024-01-15",
                        "progress": 0.0,
                        "team": {"id": "team-2", "name": "Design", "key": "DES"},
                        "issues": {"nodes": []},
                    },
                ]
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_ACTIVE_SPRINT"]

        result = fn(GetActiveSprintInput(team_id="team-1"), EXECUTE_REQUEST, AUTH_CREDS)

        assert [s["id"] for s in result["sprints"]] == ["cycle-eng"]
        assert [s["team"] for s in result["sprints"]] == ["Engineering"]


class TestLinearBulkUpdateMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_bulk_update_sends_every_field_and_maps_the_result(self, mock_gql: MagicMock) -> None:
        """Every optional field lands in the mutation input under its Linear key."""
        mock_gql.return_value = {
            "issueBatchUpdate": {
                "success": True,
                "issues": [
                    {"id": "issue-1", "identifier": "ENG-1"},
                    {"id": "issue-2", "identifier": "ENG-2"},
                ],
            },
        }

        from app.agents.tools.integrations.linear_tool import (
            MUTATION_UPDATE_ISSUES,
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_BULK_UPDATE_ISSUES"]

        result = fn(
            BulkUpdateIssuesInput(
                issue_ids=["issue-1", "issue-2"],
                state_id="state-1",
                priority=2,
                assignee_id="user-1",
                cycle_id="cycle-1",
                project_id="project-1",
                labels_to_add=["label-1", "label-2"],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        mock_gql.assert_called_once_with(
            MUTATION_UPDATE_ISSUES,
            {
                "issueIds": ["issue-1", "issue-2"],
                "input": {
                    "stateId": "state-1",
                    "priority": 2,
                    "assigneeId": "user-1",
                    "cycleId": "cycle-1",
                    "projectId": "project-1",
                    "labelIds": ["label-1", "label-2"],
                },
            },
            AUTH_CREDS,
        )
        assert result == {
            "updated_count": 2,
            "updated_issues": [
                {"id": "issue-1", "identifier": "ENG-1"},
                {"id": "issue-2", "identifier": "ENG-2"},
            ],
        }


class TestLinearNotificationsMapping:
    @staticmethod
    def _notification_nodes() -> list[dict[str, Any]]:
        """Three notifications: unread with context, read with context, unread bare."""
        return [
            {
                "id": "notif-1",
                "type": "issueAssignedToYou",
                "createdAt": "2024-01-01T00:00:00Z",
                "readAt": None,
                "issue": {"identifier": "ENG-1", "title": "Fix login"},
                "actor": {"name": "Alice"},
            },
            {
                "id": "notif-2",
                "type": "issueCommentMention",
                "createdAt": "2024-01-02T00:00:00Z",
                "readAt": "2024-01-03T00:00:00Z",
                "issue": {"identifier": "ENG-2", "title": "Add cache"},
                "actor": {"name": "Bob"},
            },
            {
                "id": "notif-3",
                "type": "issueStatusChanged",
                "createdAt": "2024-01-04T00:00:00Z",
                "readAt": None,
                "issue": None,
                "actor": None,
            },
        ]

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_notifications_maps_every_field(self, mock_gql: MagicMock) -> None:
        """Each notification is mapped exactly, including the nested issue and actor."""
        mock_gql.return_value = {"notifications": {"nodes": self._notification_nodes()}}

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_NOTIFICATIONS"]

        result = fn(GetNotificationsInput(include_read=True), EXECUTE_REQUEST, AUTH_CREDS)

        assert result == {
            "count": 3,
            "notifications": [
                {
                    "id": "notif-1",
                    "type": "issueAssignedToYou",
                    "created_at": "2024-01-01T00:00:00Z",
                    "read": False,
                    "issue": {"identifier": "ENG-1", "title": "Fix login"},
                    "actor": "Alice",
                },
                {
                    "id": "notif-2",
                    "type": "issueCommentMention",
                    "created_at": "2024-01-02T00:00:00Z",
                    "read": True,
                    "issue": {"identifier": "ENG-2", "title": "Add cache"},
                    "actor": "Bob",
                },
                {
                    "id": "notif-3",
                    "type": "issueStatusChanged",
                    "created_at": "2024-01-04T00:00:00Z",
                    "read": False,
                    "issue": None,
                    "actor": None,
                },
            ],
        }

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_notifications_drops_exactly_the_read_ones(self, mock_gql: MagicMock) -> None:
        """include_read=False keeps the unread notifications and only those."""
        mock_gql.return_value = {"notifications": {"nodes": self._notification_nodes()}}

        from app.agents.tools.integrations.linear_tool import (
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_NOTIFICATIONS"]

        result = fn(GetNotificationsInput(include_read=False), EXECUTE_REQUEST, AUTH_CREDS)

        assert result == {
            "count": 2,
            "notifications": [
                {
                    "id": "notif-1",
                    "type": "issueAssignedToYou",
                    "created_at": "2024-01-01T00:00:00Z",
                    "read": False,
                    "issue": {"identifier": "ENG-1", "title": "Fix login"},
                    "actor": "Alice",
                },
                {
                    "id": "notif-3",
                    "type": "issueStatusChanged",
                    "created_at": "2024-01-04T00:00:00Z",
                    "read": False,
                    "issue": None,
                    "actor": None,
                },
            ],
        }


class TestLinearWorkspaceContextMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_workspace_context_maps_every_field(self, mock_gql: MagicMock) -> None:
        """User, teams and each urgent bucket are mapped exactly from the three queries."""
        local_today = datetime.now().date()
        yesterday = (local_today - timedelta(days=1)).isoformat()
        tomorrow = (local_today + timedelta(days=1)).isoformat()
        mock_gql.side_effect = [
            {"viewer": _linear_viewer(assigned_issue_ids=["a1", "a2"])},
            {"teams": {"nodes": _linear_team_nodes()}},
            {"issues": {"nodes": _linear_my_issue_nodes(yesterday, tomorrow)}},
        ]

        from app.agents.tools.integrations.linear_tool import (
            QUERY_MY_ISSUES,
            QUERY_TEAMS,
            QUERY_VIEWER,
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GET_WORKSPACE_CONTEXT"]

        with patch(f"{LINEAR_MODULE}._user_local_today", return_value=local_today):
            result = fn(GetWorkspaceContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

        assert mock_gql.call_args_list == [
            call(QUERY_VIEWER, None, AUTH_CREDS),
            call(QUERY_TEAMS, None, AUTH_CREDS),
            call(
                QUERY_MY_ISSUES,
                {"assigneeId": "viewer-1", "includeCompleted": True, "first": 50},
                AUTH_CREDS,
            ),
        ]
        assert result == {
            "user": {
                "id": "viewer-1",
                "name": "Alice",
                "email": "alice@example.com",
                "assigned_issue_count": 2,
            },
            "teams": [
                {
                    "id": "team-1",
                    "name": "Engineering",
                    "key": "ENG",
                    "active_cycle": "Sprint 5",
                    "cycle_progress": 45.7,
                },
                {
                    "id": "team-2",
                    "name": "Design",
                    "key": "DES",
                    "active_cycle": None,
                    "cycle_progress": None,
                },
            ],
            "urgent_items": {
                "overdue": [_expected_overdue_summary(yesterday)],
                "high_priority": [
                    _expected_overdue_summary(yesterday),
                    _expected_high_priority_summary(tomorrow),
                ],
                "sla_at_risk": [_expected_overdue_summary(yesterday)],
            },
        }


class TestLinearGatherContextMapping:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_gather_context_maps_every_field(self, mock_gql: MagicMock) -> None:
        """User, teams and both urgent buckets are mapped exactly from the three queries."""
        local_today = datetime.now().date()
        yesterday = (local_today - timedelta(days=1)).isoformat()
        tomorrow = (local_today + timedelta(days=1)).isoformat()
        mock_gql.side_effect = [
            {"viewer": _linear_viewer(assigned_issue_ids=["a1", "a2"])},
            {"teams": {"nodes": _linear_team_nodes()}},
            {"issues": {"nodes": _linear_my_issue_nodes(yesterday, tomorrow)}},
        ]

        from app.agents.tools.integrations.linear_tool import (
            QUERY_MY_ISSUES,
            QUERY_TEAMS,
            QUERY_VIEWER,
            register_linear_custom_tools,
        )

        tools = _capture_tools(register_linear_custom_tools)
        fn = tools["CUSTOM_GATHER_CONTEXT"]

        with patch(f"{LINEAR_MODULE}._user_local_today", return_value=local_today):
            result = fn(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

        assert mock_gql.call_args_list == [
            call(QUERY_VIEWER, None, AUTH_CREDS),
            call(QUERY_TEAMS, None, AUTH_CREDS),
            call(
                QUERY_MY_ISSUES,
                {"assigneeId": "viewer-1", "includeCompleted": True, "first": 50},
                AUTH_CREDS,
            ),
        ]
        assert result == {
            "user": {"id": "viewer-1", "name": "Alice", "email": "alice@example.com"},
            "teams": [
                {"id": "team-1", "name": "Engineering", "key": "ENG"},
                {"id": "team-2", "name": "Design", "key": "DES"},
            ],
            "urgent_items": {
                "overdue": [_expected_overdue_summary(yesterday)],
                "high_priority": [
                    _expected_overdue_summary(yesterday),
                    _expected_high_priority_summary(tomorrow),
                ],
            },
        }
