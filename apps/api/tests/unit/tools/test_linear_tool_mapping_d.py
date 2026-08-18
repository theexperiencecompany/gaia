"""The completed/canceled state filters and missing-state paths.

Every consumer of ``state.type`` filters or buckets on it, and no test ever
fed a completed, canceled, or state-LESS issue through those loops — so the
key reads and list membership could mutate unnoticed. One issue per state
shape, per tool.
"""

from typing import ClassVar
from unittest.mock import MagicMock, patch

from app.models.common_models import GatherContextInput
from app.models.linear_models import (
    GetActiveSprintInput,
    GetMyTasksInput,
    GetWorkspaceContextInput,
    SearchIssuesInput,
)
from tests.unit.tools.test_integration_tools import (
    AUTH_CREDS,
    EXECUTE_REQUEST,
    LINEAR_MODULE,
    _capture_tools,
)

_STARTED = {"id": "i-open", "title": "Open", "priority": 3, "state": {"type": "started"}}
_DONE = {"id": "i-done", "title": "Done", "priority": 1, "state": {"type": "completed"}}
_CANCELED = {"id": "i-can", "title": "Gone", "priority": 2, "state": {"type": "canceled"}}
_STATELESS = {"id": "i-raw", "title": "Raw", "priority": 4}


def _tool(name: str):
    from app.agents.tools.integrations.linear_tool import register_linear_custom_tools

    return _capture_tools(register_linear_custom_tools)[name]


class TestMyTasksStateFilter:
    @patch(f"{LINEAR_MODULE}.format_issue_summary", side_effect=lambda i: {"id": i.get("id")})
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_completed_and_canceled_drop_and_stateless_stays(
        self, mock_gql: MagicMock, _fmt: MagicMock
    ) -> None:
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {"issues": {"nodes": [_STARTED, _DONE, _CANCELED, _STATELESS]}},
        ]

        result = _tool("CUSTOM_GET_MY_TASKS")(
            GetMyTasksInput(filter="all", limit=10), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert [i["id"] for i in result["issues"]] == ["i-open", "i-raw"]

    @patch(f"{LINEAR_MODULE}.format_issue_summary", side_effect=lambda i: {"id": i.get("id")})
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_include_completed_keeps_all_and_sorts_missing_fields_last(
        self, mock_gql: MagicMock, _fmt: MagicMock
    ) -> None:
        # Same priority pair: a real dueDate sorts before a missing one.
        dated = {
            "id": "i-dated",
            "priority": 3,
            "state": {"type": "started"},
            "dueDate": "2026-01-02",
        }
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {"issues": {"nodes": [_STATELESS, _DONE, dated, _STARTED]}},
        ]

        result = _tool("CUSTOM_GET_MY_TASKS")(
            GetMyTasksInput(filter="all", limit=10, include_completed=True),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        # priority asc (1,3,3,4); within priority 3 the dated issue first;
        # the priority-less shape would sort last if present.
        assert [i["id"] for i in result["issues"]] == ["i-done", "i-dated", "i-open", "i-raw"]


class TestSearchStateFilter:
    @patch(f"{LINEAR_MODULE}.format_issue_summary", side_effect=lambda i: {"id": i.get("id")})
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_state_filter_matches_case_insensitively_and_skips_stateless(
        self, mock_gql: MagicMock, _fmt: MagicMock
    ) -> None:
        upper = {"id": "i-up", "state": {"type": "COMPLETED"}}
        mock_gql.return_value = {"searchIssues": {"nodes": [upper, _STARTED, _STATELESS]}}

        result = _tool("CUSTOM_SEARCH_ISSUES")(
            SearchIssuesInput(query="q", state_filter="completed", limit=10),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert [i["id"] for i in result["issues"]] == ["i-up"]


class TestSprintBuckets:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_a_stateless_issue_lands_in_the_unstarted_bucket(self, mock_gql: MagicMock) -> None:
        cycle = {
            "id": "c1",
            "name": "Sprint 1",
            "issues": {"nodes": [_STATELESS, _STARTED]},
        }
        mock_gql.return_value = {"cycles": {"nodes": [cycle]}}

        result = _tool("CUSTOM_GET_ACTIVE_SPRINT")(
            GetActiveSprintInput(), EXECUTE_REQUEST, AUTH_CREDS
        )

        sprint = result["sprints"][0]
        assert sprint["issues_by_state"] == {
            "backlog": 0,
            "unstarted": 1,
            "started": 1,
            "completed": 0,
        }
        assert [i["title"] for i in sprint["todo"]] == ["Raw"]
        assert [i["title"] for i in sprint["in_progress"]] == ["Open"]


class TestWorkspaceAndGatherStateFilter:
    _GQL: ClassVar[list[dict[str, object]]] = [
        {"viewer": {"id": "u1", "name": "U", "email": "u@x", "assignedIssues": {"nodes": []}}},
        {"teams": {"nodes": []}},
        {
            "issues": {
                "nodes": [
                    {**_DONE, "dueDate": "2020-01-01"},
                    {**_CANCELED, "dueDate": "2020-01-01"},
                    {
                        "id": "i-late",
                        "title": "Late",
                        "priority": 1,
                        "state": {"type": "started"},
                        "dueDate": "2020-01-01",
                    },
                    {**_STATELESS, "priority": 1},
                ]
            }
        },
    ]

    @patch(f"{LINEAR_MODULE}.format_issue_summary", side_effect=lambda i: {"id": i.get("id")})
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_workspace_excludes_done_and_counts_stateless(
        self, mock_gql: MagicMock, _fmt: MagicMock
    ) -> None:
        mock_gql.side_effect = list(self._GQL)

        result = _tool("CUSTOM_GET_WORKSPACE_CONTEXT")(
            GetWorkspaceContextInput(), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert [i["id"] for i in result["urgent_items"]["overdue"]] == ["i-late"]
        assert [i["id"] for i in result["urgent_items"]["high_priority"]] == ["i-late", "i-raw"]

    @patch(f"{LINEAR_MODULE}.format_issue_summary", side_effect=lambda i: {"id": i.get("id")})
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_gather_excludes_done_and_counts_stateless(
        self, mock_gql: MagicMock, _fmt: MagicMock
    ) -> None:
        mock_gql.side_effect = list(self._GQL)

        result = _tool("CUSTOM_GATHER_CONTEXT")(GatherContextInput(), EXECUTE_REQUEST, AUTH_CREDS)

        assert [i["id"] for i in result["urgent_items"]["overdue"]] == ["i-late"]
        assert [i["id"] for i in result["urgent_items"]["high_priority"]] == ["i-late", "i-raw"]
