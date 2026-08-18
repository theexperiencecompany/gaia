"""Call-wiring, error-text and branch tests for the Linear custom tools.

The result-shape tests in ``test_linear_tool_mapping_a``–``d`` assert what each
tool returns; they say nothing about *how* it asked Linear. A tool that drops
its auth credentials, sends the wrong query constant, or mangles a GraphQL
variable name still returns the mocked payload unchanged. These tests pin the
outgoing side: the exact ``graphql_request``/``fuzzy_match`` call arguments,
the exact text of every raised error, and the loop branches that decide whether
an item is skipped or the whole loop stops.

Harness (``_capture_tools`` and the auth fixtures) is shared with
``test_integration_tools.py``; it is imported rather than re-declared.
"""

from collections.abc import Callable
from unittest.mock import MagicMock, call, patch

import pytest

from app.models.linear_models import (
    BulkUpdateIssuesInput,
    CreateIssueInput,
    CreateIssueRelationInput,
    CreateSubIssuesInput,
    GetActiveSprintInput,
    GetIssueFullContextInput,
    GetMyTasksInput,
    ResolveContextInput,
    SearchIssuesInput,
    SubIssueItem,
)
from app.utils.linear_utils import (
    MUTATION_CREATE_ISSUE,
    MUTATION_CREATE_RELATION,
    MUTATION_UPDATE_ISSUES,
    QUERY_ACTIVE_CYCLES,
    QUERY_ISSUE_BY_ID,
    QUERY_ISSUE_BY_IDENTIFIER,
    QUERY_MY_ISSUES,
    QUERY_PROJECTS,
    QUERY_TEAMS,
    QUERY_VIEWER,
)
from tests.unit.tools.test_integration_tools import (
    AUTH_CREDS,
    EXECUTE_REQUEST,
    LINEAR_MODULE,
    _capture_tools,
)


def _tool(name: str) -> Callable[..., dict[str, object]]:
    """The registered Linear custom tool with ``name``."""
    from app.agents.tools.integrations.linear_tool import register_linear_custom_tools

    tool: Callable[..., dict[str, object]] = _capture_tools(register_linear_custom_tools)[name]
    return tool


class TestLinearGraphqlCallWiring:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_resolve_context_sends_each_query_with_its_credentials(
        self, mock_gql: MagicMock
    ) -> None:
        """Every lookup sends its own query constant and the caller's credentials."""
        mock_gql.side_effect = [
            {"viewer": {"id": "u1", "name": "Alice", "email": "alice@example.com"}},
            {"teams": {"nodes": [{"id": "t1", "name": "Engineering"}]}},
        ]

        _tool("CUSTOM_RESOLVE_CONTEXT")(
            ResolveContextInput(team_name="engineering"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert mock_gql.call_args_list == [
            call(QUERY_VIEWER, None, AUTH_CREDS),
            call(QUERY_TEAMS, None, AUTH_CREDS),
        ]

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_issue_sends_the_mutation_with_every_field(self, mock_gql: MagicMock) -> None:
        """Each optional field lands under its own Linear input key."""
        mock_gql.return_value = {
            "issueCreate": {
                "success": True,
                "issue": {"id": "i1", "identifier": "ENG-1", "title": "Ship it", "url": "u"},
            }
        }

        _tool("CUSTOM_CREATE_ISSUE")(
            CreateIssueInput(
                team_id="t1",
                title="Ship it",
                description="why",
                assignee_id="u1",
                priority=2,
                state_id="s1",
                label_ids=["l1"],
                project_id="p1",
                cycle_id="c1",
                due_date="2024-05-01",
                estimate=5,
                parent_id="par1",
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert mock_gql.call_args_list == [
            call(
                MUTATION_CREATE_ISSUE,
                {
                    "input": {
                        "teamId": "t1",
                        "title": "Ship it",
                        "description": "why",
                        "assigneeId": "u1",
                        "priority": 2,
                        "stateId": "s1",
                        "labelIds": ["l1"],
                        "projectId": "p1",
                        "cycleId": "c1",
                        "dueDate": "2024-05-01",
                        "estimate": 5,
                        "parentId": "par1",
                    }
                },
                AUTH_CREDS,
            )
        ]

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_sub_issues_resolves_the_parent_then_creates_each_sub(
        self, mock_gql: MagicMock
    ) -> None:
        """The identifier lookup, the parent read and the create all carry credentials."""
        mock_gql.side_effect = [
            {"teams": {"nodes": [{"issue": {"id": "p1"}}]}},
            {"issue": {"id": "p1", "team": {"id": "t1"}}},
            {
                "issueCreate": {
                    "success": True,
                    "issue": {"id": "s1", "identifier": "ENG-43", "title": "Sub one"},
                }
            },
        ]

        _tool("CUSTOM_CREATE_SUB_ISSUES")(
            CreateSubIssuesInput(
                parent_identifier="ENG-42",
                sub_issues=[
                    SubIssueItem(title="Sub one", description="d1", assignee_id="a1", priority=3)
                ],
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert mock_gql.call_args_list == [
            call(QUERY_ISSUE_BY_IDENTIFIER, {"teamKey": "ENG", "number": 42.0}, AUTH_CREDS),
            call(QUERY_ISSUE_BY_ID, {"id": "p1"}, AUTH_CREDS),
            call(
                MUTATION_CREATE_ISSUE,
                {
                    "input": {
                        "teamId": "t1",
                        "title": "Sub one",
                        "parentId": "p1",
                        "description": "d1",
                        "assigneeId": "a1",
                        "priority": 3,
                    }
                },
                AUTH_CREDS,
            ),
        ]

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_relation_sends_the_mapped_type_and_both_issue_ids(
        self, mock_gql: MagicMock
    ) -> None:
        """The relation variables use Linear's key names and the mapped type."""
        mock_gql.return_value = {
            "issueRelationCreate": {"success": True, "issueRelation": {"id": "r1"}}
        }

        _tool("CUSTOM_CREATE_ISSUE_RELATION")(
            CreateIssueRelationInput(
                issue_id="i1", related_issue_id="i2", relation_type="is_blocked_by"
            ),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert mock_gql.call_args_list == [
            call(
                MUTATION_CREATE_RELATION,
                {"issueId": "i1", "relatedIssueId": "i2", "type": "blocked_by"},
                AUTH_CREDS,
            )
        ]

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_active_sprint_sends_the_cycles_query_with_credentials(
        self, mock_gql: MagicMock
    ) -> None:
        """The sprint read sends the active-cycles query and no variables."""
        mock_gql.return_value = {"cycles": {"nodes": []}}

        _tool("CUSTOM_GET_ACTIVE_SPRINT")(GetActiveSprintInput(), EXECUTE_REQUEST, AUTH_CREDS)

        assert mock_gql.call_args_list == [call(QUERY_ACTIVE_CYCLES, None, AUTH_CREDS)]

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_get_my_tasks_sends_the_viewer_id_and_completion_flag(
        self, mock_gql: MagicMock
    ) -> None:
        """The issue query asks for twice the limit and inverts include_completed."""
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {"issues": {"nodes": []}},
        ]

        _tool("CUSTOM_GET_MY_TASKS")(GetMyTasksInput(limit=20), EXECUTE_REQUEST, AUTH_CREDS)

        assert mock_gql.call_args_list == [
            call(QUERY_VIEWER, None, AUTH_CREDS),
            call(
                QUERY_MY_ISSUES,
                {"assigneeId": "u1", "includeCompleted": True, "first": 40},
                AUTH_CREDS,
            ),
        ]


class TestLinearFuzzyMatchWiring:
    @patch(f"{LINEAR_MODULE}.fuzzy_match", return_value=[])
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_each_label_name_is_matched_separately_at_limit_one(
        self, mock_gql: MagicMock, mock_fuzzy: MagicMock
    ) -> None:
        """Every requested label name gets its own single-best-match lookup."""
        labels = [{"id": "l1", "name": "bug"}, {"id": "l2", "name": "chore"}]
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {"issueLabels": {"nodes": labels}},
        ]

        _tool("CUSTOM_RESOLVE_CONTEXT")(
            ResolveContextInput(label_names=["bug", "chore"], team_id="t1"),
            EXECUTE_REQUEST,
            AUTH_CREDS,
        )

        assert mock_fuzzy.call_args_list == [
            call("bug", labels, "name", limit=1),
            call("chore", labels, "name", limit=1),
        ]

    @patch(f"{LINEAR_MODULE}.fuzzy_match", return_value=[])
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_the_project_name_is_matched_against_projects_at_limit_three(
        self, mock_gql: MagicMock, mock_fuzzy: MagicMock
    ) -> None:
        """The project lookup offers three candidates, not one and not four."""
        projects = [{"id": "p1", "name": "GAIA Core"}]
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {"projects": {"nodes": projects}},
        ]

        _tool("CUSTOM_RESOLVE_CONTEXT")(
            ResolveContextInput(project_name="gaia"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert mock_gql.call_args_list[1] == call(QUERY_PROJECTS, None, AUTH_CREDS)
        assert mock_fuzzy.call_args_list == [call("gaia", projects, "name", limit=3)]


class TestLinearErrorMessages:
    def test_full_context_without_any_identifier_names_both_options(self) -> None:
        """The tool says which of the two inputs it needs."""
        with pytest.raises(ValueError) as excinfo:
            _tool("CUSTOM_GET_ISSUE_FULL_CONTEXT")(
                GetIssueFullContextInput(), EXECUTE_REQUEST, AUTH_CREDS
            )

        assert str(excinfo.value) == "Provide either issue_id or issue_identifier"

    @patch(f"{LINEAR_MODULE}.graphql_request", return_value={})
    def test_full_context_reports_the_identifier_it_looked_up(self, mock_gql: MagicMock) -> None:
        """A missing issue is reported with the id the caller supplied."""
        with pytest.raises(ValueError) as excinfo:
            _tool("CUSTOM_GET_ISSUE_FULL_CONTEXT")(
                GetIssueFullContextInput(issue_id="i404"), EXECUTE_REQUEST, AUTH_CREDS
            )

        assert str(excinfo.value) == "Issue not found: i404"

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_create_issue_failure_raises_its_exact_message(self, mock_gql: MagicMock) -> None:
        """An unsuccessful create surfaces as a RuntimeError, not an empty result."""
        mock_gql.return_value = {"issueCreate": {"success": False}}

        with pytest.raises(RuntimeError) as excinfo:
            _tool("CUSTOM_CREATE_ISSUE")(
                CreateIssueInput(team_id="t1", title="Ship it"), EXECUTE_REQUEST, AUTH_CREDS
            )

        assert str(excinfo.value) == "Failed to create issue"

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_sub_issues_without_a_parent_team_raises_its_exact_message(
        self, mock_gql: MagicMock
    ) -> None:
        """A parent issue carrying no team cannot seed the sub-issue create."""
        mock_gql.return_value = {"issue": {"id": "p1"}}

        with pytest.raises(ValueError) as excinfo:
            _tool("CUSTOM_CREATE_SUB_ISSUES")(
                CreateSubIssuesInput(
                    parent_issue_id="p1", sub_issues=[SubIssueItem(title="Sub one")]
                ),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

        assert str(excinfo.value) == "Could not get parent's team"

    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_bulk_update_failure_raises_its_exact_message(self, mock_gql: MagicMock) -> None:
        """An unsuccessful batch update raises rather than reporting zero updates."""
        mock_gql.return_value = {"issueBatchUpdate": {"success": False}}

        with pytest.raises(RuntimeError) as excinfo:
            _tool("CUSTOM_BULK_UPDATE_ISSUES")(
                BulkUpdateIssuesInput(issue_ids=["i1"], state_id="s1"),
                EXECUTE_REQUEST,
                AUTH_CREDS,
            )

        assert str(excinfo.value) == "Batch update failed"
        assert mock_gql.call_args_list == [
            call(
                MUTATION_UPDATE_ISSUES,
                {"issueIds": ["i1"], "input": {"stateId": "s1"}},
                AUTH_CREDS,
            )
        ]


class TestLinearFilterBranches:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_high_priority_filter_keeps_urgent_and_high_only(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
        """P1 and P2 pass the high-priority filter; P3 does not."""
        started = {"type": "started"}
        mock_gql.side_effect = [
            {"viewer": {"id": "u1"}},
            {
                "issues": {
                    "nodes": [
                        {"id": "i_p1", "priority": 1, "state": started},
                        {"id": "i_p2", "priority": 2, "state": started},
                        {"id": "i_p3", "priority": 3, "state": started},
                    ]
                }
            },
        ]

        result = _tool("CUSTOM_GET_MY_TASKS")(
            GetMyTasksInput(filter="high_priority"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result == {
            "filter": "high_priority",
            "count": 2,
            "issues": [{"id": "i_p1"}, {"id": "i_p2"}],
        }

    @patch(f"{LINEAR_MODULE}.graphql_request")
    @patch(
        f"{LINEAR_MODULE}.format_issue_summary",
        side_effect=lambda i: {"id": i.get("id")},
    )
    def test_team_filter_skips_a_leading_mismatch_and_keeps_the_later_match(
        self, mock_fmt: MagicMock, mock_gql: MagicMock
    ) -> None:
        """A wrong-team issue is skipped, not treated as the end of the results."""
        mock_gql.return_value = {
            "searchIssues": {
                "nodes": [
                    {"id": "i_other", "team": {"id": "t2"}, "state": {"type": "started"}},
                    {"id": "i_match", "team": {"id": "t1"}, "state": {"type": "started"}},
                ]
            }
        }

        result = _tool("CUSTOM_SEARCH_ISSUES")(
            SearchIssuesInput(query="test", team_id="t1"), EXECUTE_REQUEST, AUTH_CREDS
        )

        assert result == {"query": "test", "count": 1, "issues": [{"id": "i_match"}]}


class TestLinearIssueContextActivity:
    @patch(f"{LINEAR_MODULE}.graphql_request")
    def test_state_history_needs_only_one_side_and_unknown_entries_are_skipped(
        self, mock_gql: MagicMock
    ) -> None:
        """A state change with only one side still records; an unknown entry is skipped."""
        mock_gql.return_value = {
            "issue": {
                "id": "i1",
                "identifier": "ENG-1",
                "title": "Ship it",
                "history": {
                    "nodes": [
                        {"createdAt": "t0", "actor": {"name": "Ann"}},
                        {"createdAt": "t1", "actor": {"name": "Bo"}, "fromState": {"name": "Todo"}},
                        {"createdAt": "t2", "actor": {"name": "Cy"}, "toState": {"name": "Done"}},
                    ]
                },
            }
        }

        result = _tool("CUSTOM_GET_ISSUE_FULL_CONTEXT")(
            GetIssueFullContextInput(issue_id="i1"), EXECUTE_REQUEST, AUTH_CREDS
        )

        issue = result["issue"]
        assert isinstance(issue, dict)
        assert issue["activity"] == [
            {"timestamp": "t1", "actor": "Bo", "change": "state", "from": "Todo", "to": None},
            {"timestamp": "t2", "actor": "Cy", "change": "state", "from": None, "to": "Done"},
        ]
