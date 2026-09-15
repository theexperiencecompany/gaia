"""Unit tests for app.utils.linear_utils (GraphQL over the Composio proxy)."""

from unittest.mock import patch

from pydantic import BaseModel, ValidationError
import pytest

from app.models.integrations.linear import (
    LinearFirstVariables,
    LinearIssueSummary,
    LinearIssueUpdateInput,
    LinearProject,
    LinearViewerData,
)
from app.services.composio.proxy_client import ProxyRequest
from app.utils.linear_utils import (
    LINEAR_GRAPHQL_ENDPOINT,
    format_issue_summary,
    fuzzy_match,
    graphql_request,
)

USER_ID = "user_test_123"
PROXY_PATH = "app.utils.linear_utils.proxy_request_sync"
QUERY = "query { viewer { id } }"
VIEWER = {
    "viewer": {
        "id": "u1",
        "name": "Ada",
        "email": "ada@example.com",
        "assignedIssues": {"nodes": [{"id": "i1"}]},
    }
}


class _Empty(BaseModel):
    """A ``data`` model for operations whose payload the test does not read."""


@pytest.fixture
def mock_proxy():
    with patch(PROXY_PATH) as proxy:
        proxy.return_value = {"data": {}}
        yield proxy


class TestGraphqlRequest:
    def test_posts_the_query_and_variables_as_the_users_linear_call(self, mock_proxy):
        graphql_request(QUERY, LinearFirstVariables(first=5), USER_ID, _Empty)

        assert mock_proxy.call_args.args[0] == ProxyRequest(
            user_id=USER_ID,
            toolkit="LINEAR",
            endpoint=LINEAR_GRAPHQL_ENDPOINT,
            method="POST",
            body={"query": QUERY, "variables": {"first": 5}},
        )

    def test_no_variables_are_left_out_of_the_payload(self, mock_proxy):
        graphql_request(QUERY, None, USER_ID, _Empty)

        assert mock_proxy.call_args.args[0].body == {"query": QUERY}

    def test_variables_are_sent_camel_cased_and_only_when_assigned(self, mock_proxy):
        variables = LinearIssueUpdateInput()
        variables.state_id = "s1"
        variables.assignee_id = None

        graphql_request(QUERY, variables, USER_ID, _Empty)

        assert mock_proxy.call_args.args[0].body == {
            "query": QUERY,
            "variables": {"stateId": "s1", "assigneeId": None},
        }

    def test_returns_the_data_field_parsed_into_the_model(self, mock_proxy):
        mock_proxy.return_value = {"data": VIEWER}

        data = graphql_request(QUERY, None, USER_ID, LinearViewerData)

        assert data.viewer.id == "u1"
        assert data.viewer.email == "ada@example.com"
        assert [issue.id for issue in data.viewer.assigned_issues.nodes] == ["i1"]

    def test_data_missing_the_selection_fails_validation(self, mock_proxy):
        mock_proxy.return_value = {"data": {}}

        with pytest.raises(ValidationError):
            graphql_request(QUERY, None, USER_ID, LinearViewerData)

    def test_a_non_object_response_fails_validation(self, mock_proxy):
        mock_proxy.return_value = None

        with pytest.raises(ValidationError):
            graphql_request(QUERY, None, USER_ID, _Empty)

    def test_graphql_errors_raise_with_every_message(self, mock_proxy):
        mock_proxy.return_value = {
            "errors": [{"message": "Not found"}, {"message": "Forbidden"}],
            "data": None,
        }

        with pytest.raises(Exception, match=r"GraphQL errors: Not found; Forbidden"):
            graphql_request(QUERY, None, USER_ID, _Empty)


def _project(name: str) -> LinearProject:
    return LinearProject(id=f"p-{name}", name=name, state="started", progress=0.0)


class TestFuzzyMatch:
    def test_exact_beats_prefix_beats_substring_beats_similarity(self):
        candidates = [_project("Website"), _project("aweb"), _project("Web"), _project("wxb")]

        assert [p.name for p in fuzzy_match("web", candidates, limit=4)] == [
            "Web",
            "Website",
            "aweb",
            "wxb",
        ]

    def test_below_threshold_is_dropped_and_limit_caps_the_result(self):
        candidates = [_project("Web"), _project("Website"), _project("zzzzzz")]

        assert [p.name for p in fuzzy_match("web", candidates, limit=1)] == ["Web"]
        assert [p.name for p in fuzzy_match("web", candidates, limit=5)] == ["Web", "Website"]

    def test_empty_query_returns_the_first_candidates(self):
        candidates = [_project("A"), _project("B"), _project("C")]

        assert fuzzy_match("", candidates, limit=2) == candidates[:2]
        assert fuzzy_match("a", [], limit=2) == []


class TestFormatIssueSummary:
    def test_summarises_every_related_name(self):
        issue = LinearIssueSummary.model_validate(
            {
                "id": "i1",
                "identifier": "ENG-1",
                "title": "Fix",
                "priority": 2,
                "state": {"id": "s1", "name": "In Progress", "type": "started"},
                "dueDate": "2026-01-02",
                "team": {"id": "t1", "key": "ENG", "name": "Engineering"},
                "cycle": {"id": "c1", "name": "Sprint 1"},
                "parent": {"id": "i0", "identifier": "ENG-0", "title": "Epic"},
                "assignee": {"id": "u1", "name": "Ada"},
            }
        )

        assert format_issue_summary(issue) == {
            "id": "i1",
            "identifier": "ENG-1",
            "title": "Fix",
            "state": "In Progress",
            "priority": "high",
            "assignee": "Ada",
            "dueDate": "2026-01-02",
            "team": "ENG",
            "cycle": "Sprint 1",
            "parent": "ENG-0",
        }

    def test_null_relations_summarise_as_none(self):
        issue = LinearIssueSummary.model_validate(
            {
                "id": "i1",
                "identifier": "ENG-1",
                "title": "Fix",
                "priority": 0,
                "state": {"id": "s1", "name": "Backlog", "type": "backlog"},
                "dueDate": None,
                "team": {"id": "t1", "key": "ENG", "name": "Engineering"},
                "cycle": None,
                "parent": None,
                "assignee": None,
            }
        )

        assert format_issue_summary(issue) == {
            "id": "i1",
            "identifier": "ENG-1",
            "title": "Fix",
            "state": "Backlog",
            "priority": "none",
            "assignee": None,
            "dueDate": None,
            "team": "ENG",
            "cycle": None,
            "parent": None,
        }
