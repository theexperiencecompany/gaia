"""Unit tests for the Linear API helper module.

Covers the read/format boundary the strict-typing migration rewrote: the
priority mapping, the issue-summary projection, and the GraphQL request
wrapper. The Linear tool tests patch ``format_issue_summary`` out entirely, so
without this file none of that code ever runs under test.
"""

from unittest.mock import patch

import pytest

from app.utils.linear_utils import (
    LINEAR_GRAPHQL_ENDPOINT,
    LINEAR_TOOLKIT,
    format_issue_summary,
    fuzzy_match,
    graphql_request,
    history_label_names,
    priority_to_int,
    priority_to_str,
)

PROXY = "app.utils.linear_utils.proxy_request_sync"


class TestPriorityToStr:
    """Linear types ``Issue.priority`` as ``Float!`` — 2.0 is a valid wire value."""

    @pytest.mark.parametrize(
        ("wire_value", "expected"),
        [(1.0, "urgent"), (2.0, "high"), (3.0, "medium"), (4.0, "low"), (0.0, "none")],
    )
    def test_float_priority_maps_to_its_label(self, wire_value: float, expected: str) -> None:
        """A Float! off the wire resolves to the same label its int would.

        Regression: the migration read this with ``int_bag``, whose
        ``isinstance(value, int)`` check rejects a float and fell back to 0,
        reporting every issue as "none".
        """
        assert priority_to_str(wire_value) == expected

    @pytest.mark.parametrize(
        ("wire_value", "expected"),
        [(1, "urgent"), (2, "high"), (3, "medium"), (4, "low"), (0, "none")],
    )
    def test_int_priority_still_maps_to_its_label(self, wire_value: int, expected: str) -> None:
        """The int form some queries send keeps working."""
        assert priority_to_str(wire_value) == expected

    def test_value_outside_the_scale_falls_back_to_none(self) -> None:
        """An unmapped number is reported as no priority rather than raising."""
        assert priority_to_str(99.0) == "none"

    def test_unknown_label_string_falls_back_to_none(self) -> None:
        """A string that is not a canonical key is "none", as before."""
        assert priority_to_str("nonsense") == "none"


class TestPriorityToInt:
    """The inverse mapping, used when writing a priority back to Linear."""

    @pytest.mark.parametrize(
        ("label", "expected"),
        [("urgent", 1), ("high", 2), ("medium", 3), ("low", 4), ("none", 0)],
    )
    def test_label_maps_to_its_number(self, label: str, expected: int) -> None:
        assert priority_to_int(label) == expected

    def test_label_is_case_insensitive(self) -> None:
        assert priority_to_int("URGENT") == 1

    def test_unknown_label_is_no_priority(self) -> None:
        assert priority_to_int("whatever") == 0


class TestFormatIssueSummary:
    """The projection the LLM sees — every field it promises must survive."""

    def test_projects_every_field_from_a_full_issue(self) -> None:
        summary = format_issue_summary(
            {
                "id": "issue-uuid",
                "identifier": "ENG-42",
                "title": "Ship the thing",
                "state": {"name": "In Progress"},
                "priority": 2.0,
                "assignee": {"name": "Ada"},
                "dueDate": "2026-01-31",
                "team": {"key": "ENG"},
                "cycle": {"name": "Cycle 7"},
                "parent": {"identifier": "ENG-1"},
            }
        )

        assert summary["id"] == "issue-uuid"
        assert summary["identifier"] == "ENG-42"
        assert summary["title"] == "Ship the thing"
        assert summary["state"] == "In Progress"
        assert summary["priority"] == "high"
        assert summary["assignee"] == "Ada"
        assert summary["dueDate"] == "2026-01-31"
        assert summary["team"] == "ENG"
        assert summary["cycle"] == "Cycle 7"
        assert summary["parent"] == "ENG-1"

    def test_absent_nested_objects_become_none_not_errors(self) -> None:
        """A bare issue still projects — every optional slot reads None."""
        summary = format_issue_summary({"id": "i", "identifier": "ENG-1", "title": "t"})

        assert summary["state"] is None
        assert summary["assignee"] is None
        assert summary["team"] is None
        assert summary["cycle"] is None
        assert summary["parent"] is None
        assert summary["dueDate"] is None

    def test_absent_priority_is_no_priority(self) -> None:
        assert format_issue_summary({"id": "i"})["priority"] == "none"


class TestGraphqlRequest:
    """The proxy wrapper: auth guard, payload shape, error surfacing."""

    def test_missing_user_id_raises_before_any_call(self) -> None:
        """No credentials means no request — fail loud, don't call the proxy."""
        with patch(PROXY) as proxy, pytest.raises(ValueError, match="Missing user_id"):
            graphql_request("query {}", None, {})

        proxy.assert_not_called()

    def test_non_string_user_id_is_treated_as_missing(self) -> None:
        """A malformed credential bag is rejected, not passed through."""
        with patch(PROXY) as proxy, pytest.raises(ValueError, match="Missing user_id"):
            graphql_request("query {}", None, {"user_id": 12345})

        proxy.assert_not_called()

    def test_sends_the_query_to_linears_endpoint(self) -> None:
        with patch(PROXY, return_value={"data": {"ok": True}}) as proxy:
            result = graphql_request("query Q {}", None, {"user_id": "u1"})

        assert result == {"ok": True}
        kwargs = proxy.call_args.kwargs
        assert kwargs["user_id"] == "u1"
        assert kwargs["toolkit"] == LINEAR_TOOLKIT
        assert kwargs["endpoint"] == LINEAR_GRAPHQL_ENDPOINT
        assert kwargs["method"] == "POST"
        assert kwargs["body"] == {"query": "query Q {}"}

    def test_variables_are_included_when_given(self) -> None:
        with patch(PROXY, return_value={"data": {}}) as proxy:
            graphql_request("query Q {}", {"id": "x"}, {"user_id": "u1"})

        assert proxy.call_args.kwargs["body"] == {
            "query": "query Q {}",
            "variables": {"id": "x"},
        }

    def test_empty_variables_are_omitted_from_the_payload(self) -> None:
        """An empty mapping must not add a `variables` key Linear will reject."""
        with patch(PROXY, return_value={"data": {}}) as proxy:
            graphql_request("query Q {}", {}, {"user_id": "u1"})

        assert "variables" not in proxy.call_args.kwargs["body"]

    def test_graphql_errors_are_raised_with_their_messages(self) -> None:
        """An errors array is a failure, not a payload to return silently."""
        response = {"errors": [{"message": "boom"}, {"message": "also boom"}]}
        with (
            patch(PROXY, return_value=response),
            pytest.raises(Exception, match="boom") as caught,
        ):
            graphql_request("query Q {}", None, {"user_id": "u1"})

        assert "also boom" in str(caught.value)

    def test_missing_data_key_yields_an_empty_mapping(self) -> None:
        with patch(PROXY, return_value={}):
            assert graphql_request("query Q {}", None, {"user_id": "u1"}) == {}

    def test_non_mapping_response_yields_an_empty_mapping(self) -> None:
        """The proxy returns `object`; a non-dict body must not crash the caller."""
        with patch(PROXY, return_value=["unexpected"]):
            assert graphql_request("query Q {}", None, {"user_id": "u1"}) == {}


class TestHistoryLabelNames:
    """``addedLabels``/``removedLabels`` arrive as a list or a connection."""

    def test_reads_a_plain_list_of_labels(self) -> None:
        labels = history_label_names([{"id": "1", "name": "bug"}, {"id": "2", "name": "p1"}])

        assert labels == ["bug", "p1"]

    def test_reads_a_nodes_connection(self) -> None:
        assert history_label_names({"nodes": [{"name": "bug"}]}) == ["bug"]

    def test_entries_without_a_name_are_dropped(self) -> None:
        assert history_label_names([{"id": "1"}, {"name": "kept"}]) == ["kept"]

    def test_an_unexpected_shape_yields_no_labels(self) -> None:
        assert history_label_names("not-a-list") == []
        assert history_label_names(None) == []


class TestFuzzyMatch:
    """Entity resolution ranking — exact beats prefix beats substring."""

    def test_ranks_exact_above_prefix(self) -> None:
        candidates = [{"name": "engineering platform"}, {"name": "engineering"}]

        ranked = fuzzy_match("engineering", candidates, "name")

        assert ranked[0]["name"] == "engineering"
        assert ranked[1]["name"] == "engineering platform"

    def test_matching_is_case_insensitive(self) -> None:
        assert fuzzy_match("ENG", [{"name": "eng"}], "name")[0]["name"] == "eng"

    def test_respects_the_result_limit(self) -> None:
        candidates = [{"name": f"eng {i}"} for i in range(10)]

        assert len(fuzzy_match("eng", candidates, "name", limit=3)) == 3

    def test_candidates_below_the_threshold_are_dropped(self) -> None:
        assert fuzzy_match("zzzzzz", [{"name": "engineering"}], "name") == []

    def test_an_empty_query_returns_the_head_of_the_candidates(self) -> None:
        candidates = [{"name": "a"}, {"name": "b"}, {"name": "c"}]

        assert fuzzy_match("", candidates, "name", limit=2) == candidates[:2]

    def test_no_candidates_yields_no_matches(self) -> None:
        assert fuzzy_match("anything", [], "name") == []

    def test_candidates_missing_the_key_are_skipped(self) -> None:
        assert fuzzy_match("eng", [{"other": "eng"}, {"name": "eng"}], "name") == [{"name": "eng"}]
