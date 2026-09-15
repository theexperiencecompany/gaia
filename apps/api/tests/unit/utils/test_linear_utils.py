"""Unit tests for app.utils.linear_utils (GraphQL over the Composio proxy)."""

from unittest.mock import patch

import pytest

from app.services.composio.proxy_client import ProxyRequest
from app.utils.linear_utils import (
    LINEAR_GRAPHQL_ENDPOINT,
    graphql_request,
)

USER_ID = "user_test_123"
AUTH = {"user_id": USER_ID}
PROXY_PATH = "app.utils.linear_utils.proxy_request_sync"
QUERY = "query { viewer { id } }"


@pytest.fixture
def mock_proxy():
    with patch(PROXY_PATH) as proxy:
        proxy.return_value = {"data": {}}
        yield proxy


class TestGraphqlRequest:
    def test_posts_the_query_and_variables_as_the_users_linear_call(self, mock_proxy):
        graphql_request(QUERY, {"first": 5}, AUTH)

        assert mock_proxy.call_args.args[0] == ProxyRequest(
            user_id=USER_ID,
            toolkit="LINEAR",
            endpoint=LINEAR_GRAPHQL_ENDPOINT,
            method="POST",
            body={"query": QUERY, "variables": {"first": 5}},
        )

    @pytest.mark.parametrize("variables", [None, {}])
    def test_empty_variables_are_left_out_of_the_payload(self, mock_proxy, variables):
        graphql_request(QUERY, variables, AUTH)

        assert mock_proxy.call_args.args[0].body == {"query": QUERY}

    def test_returns_the_data_field(self, mock_proxy):
        mock_proxy.return_value = {"data": {"viewer": {"id": "u1"}}}

        assert graphql_request(QUERY, None, AUTH) == {"viewer": {"id": "u1"}}

    def test_a_response_without_data_is_an_empty_dict(self, mock_proxy):
        mock_proxy.return_value = {}

        assert graphql_request(QUERY, None, AUTH) == {}

    def test_a_non_dict_response_is_an_empty_dict(self, mock_proxy):
        mock_proxy.return_value = None

        assert graphql_request(QUERY, None, AUTH) == {}

    def test_graphql_errors_raise_with_every_message(self, mock_proxy):
        mock_proxy.return_value = {
            "errors": [{"message": "Not found"}, {"message": "Forbidden"}],
            "data": None,
        }

        with pytest.raises(Exception, match=r"GraphQL errors: Not found; Forbidden"):
            graphql_request(QUERY, None, AUTH)

    def test_missing_user_id_fails_before_any_call(self, mock_proxy):
        with pytest.raises(ValueError, match="Missing user_id"):
            graphql_request(QUERY, None, {})

        mock_proxy.assert_not_called()
