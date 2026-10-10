"""Tests for app.services.composio.proxy_client."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.models.agent_config import ComposioAccountSelection
from app.services.composio import proxy_client
from app.services.composio.account_scope import account_scope
from app.services.composio.dead_account import ConnectedAccountGoneError
from app.services.composio.proxy_client import (
    ProxyRequest,
    _build_parameters,
    _resolve_connected_account_id,
    proxy_request,
    proxy_request_sync,
)
from app.utils.errors import AppError
from shared.py.wide_events import log
from tests.factories import make_composio_not_found


def _make_composio(
    proxy_status: int = 200,
    proxy_data: Any = None,
) -> MagicMock:
    composio = MagicMock()
    response = MagicMock()
    response.status = proxy_status
    response.data = proxy_data if proxy_data is not None else {"ok": True}
    composio.tools.proxy.return_value = response
    return composio


def _patch_composio(composio: MagicMock):
    return patch.object(proxy_client, "_get_composio", return_value=composio)


def _patch_primary(account_id: str = "acc_active"):
    """Pin the user's primary account, as the account scope resolves it from Mongo."""
    return patch(
        "app.services.composio.account_scope.primary_connected_account_id",
        AsyncMock(return_value=account_id),
    )


class TestBuildParameters:
    def test_returns_empty_when_no_inputs(self) -> None:
        assert _build_parameters(None, None) == []

    def test_builds_header_entries(self) -> None:
        params = _build_parameters({"X-Foo": "bar"}, None)
        assert params == [{"name": "X-Foo", "type": "header", "value": "bar"}]

    def test_builds_query_entries(self) -> None:
        params = _build_parameters(None, {"q": "abc", "n": 5})
        assert {"name": "q", "type": "query", "value": "abc"} in params
        assert {"name": "n", "type": "query", "value": "5"} in params

    def test_skips_none_query_values(self) -> None:
        params = _build_parameters(None, {"q": None, "k": "v"})
        assert params == [{"name": "k", "type": "query", "value": "v"}]

    def test_expands_list_query_values(self) -> None:
        params = _build_parameters(None, {"ids": ["a", "b"]})
        assert params == [
            {"name": "ids", "type": "query", "value": "a"},
            {"name": "ids", "type": "query", "value": "b"},
        ]

    def test_combines_headers_and_query(self) -> None:
        params = _build_parameters({"H": "1"}, {"q": "x"})
        assert params == [
            {"name": "H", "type": "header", "value": "1"},
            {"name": "q", "type": "query", "value": "x"},
        ]


class TestResolveConnectedAccountId:
    def test_raises_on_missing_user_id(self) -> None:
        with pytest.raises(AppError) as exc:
            _resolve_connected_account_id("", "GMAIL")
        assert exc.value.status_code == 500

    def test_without_a_scope_it_is_the_users_primary(self) -> None:
        with _patch_primary("acc_primary") as primary:
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_primary"
        primary.assert_awaited_once_with("u1", "GMAIL")

    def test_the_account_the_call_was_scoped_to_wins(self) -> None:
        selection = ComposioAccountSelection(toolkit="GMAIL", connected_account_id="acc_work")
        with _patch_primary("acc_primary") as primary, account_scope(selection):
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_work"
        primary.assert_not_awaited()

    def test_a_scope_on_another_toolkit_does_not_leak_into_this_one(self) -> None:
        selection = ComposioAccountSelection(toolkit="NOTION", connected_account_id="acc_notion")
        with _patch_primary("acc_primary"), account_scope(selection):
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_primary"

    def test_no_connected_primary_is_the_reconnect_error(self) -> None:
        not_connected = AppError(message="x", status_code=403, code=INTEGRATION_NOT_CONNECTED)
        with patch(
            "app.services.composio.account_scope.primary_connected_account_id",
            AsyncMock(side_effect=not_connected),
        ):
            with pytest.raises(AppError) as exc:
                _resolve_connected_account_id("u1", "GMAIL")
        assert exc.value.code == INTEGRATION_NOT_CONNECTED


class TestProxyRequestSync:
    def test_sends_basic_request(self) -> None:
        composio = _make_composio(proxy_data={"hello": "world"})
        with _patch_primary(), _patch_composio(composio):
            result = proxy_request_sync(
                ProxyRequest(
                    user_id="u1",
                    toolkit="GMAIL",
                    endpoint="https://gmail.googleapis.com/x",
                    method="GET",
                )
            )
        assert result == {"hello": "world"}
        composio.tools.proxy.assert_called_once()
        kwargs = composio.tools.proxy.call_args.kwargs
        assert kwargs["endpoint"] == "https://gmail.googleapis.com/x"
        assert kwargs["method"] == "GET"
        assert kwargs["connected_account_id"] == "acc_active"
        assert "body" not in kwargs
        assert "binary_body" not in kwargs
        assert "parameters" not in kwargs

    def test_passes_body_and_parameters(self) -> None:
        composio = _make_composio()
        with _patch_primary(), _patch_composio(composio):
            proxy_request_sync(
                ProxyRequest(
                    user_id="u1",
                    toolkit="GMAIL",
                    endpoint="/x",
                    method="POST",
                    body={"a": 1},
                    headers={"Content-Type": "application/json"},
                    query={"page": 2},
                )
            )
        kwargs = composio.tools.proxy.call_args.kwargs
        assert kwargs["body"] == {"a": 1}
        assert {
            "name": "Content-Type",
            "type": "header",
            "value": "application/json",
        } in kwargs["parameters"]
        assert {"name": "page", "type": "query", "value": "2"} in kwargs["parameters"]

    def test_binary_body_takes_precedence_over_body(self) -> None:
        composio = _make_composio()
        with _patch_primary(), _patch_composio(composio):
            proxy_request_sync(
                ProxyRequest(
                    user_id="u1",
                    toolkit="GMAIL",
                    endpoint="/upload",
                    method="POST",
                    body={"ignored": True},
                    binary_body={"url": "https://x/y", "content_type": "image/png"},
                )
            )
        kwargs = composio.tools.proxy.call_args.kwargs
        assert kwargs["binary_body"] == {
            "url": "https://x/y",
            "content_type": "image/png",
        }
        assert "body" not in kwargs

    def test_raises_app_error_on_non_2xx(self) -> None:
        composio = _make_composio(proxy_status=404, proxy_data={"err": "missing"})
        with _patch_primary(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(
                    ProxyRequest(
                        user_id="u1",
                        toolkit="GMAIL",
                        endpoint="/x",
                        method="GET",
                    )
                )
        assert exc.value.status_code == 404
        assert exc.value.public == {"toolkit": "GMAIL"}
        assert exc.value.why == "The provider rejected the request", (
            "the endpoint that failed is internal; the user gets the plain fact"
        )
        assert exc.value.code == "", "only a rejected token routes to the reconnect flow"
        assert exc.value.meta == {
            "endpoint": "/x",
            "method": "GET",
            "provider_status": 404,
            "provider_response": {"err": "missing"},
        }, "the provider's own body never reaches the client"

    def test_provider_401_is_surfaced_as_403_with_the_not_connected_code(self) -> None:
        # A rejected token means the *integration* needs reconnecting, not the
        # GAIA session — the client routes on the 403 + code pair.
        composio = _make_composio(proxy_status=401, proxy_data={"error": "invalid_grant"})
        with _patch_primary(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(
                    ProxyRequest(user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET")
                )
        assert exc.value.status_code == 403
        assert exc.value.code == INTEGRATION_NOT_CONNECTED
        assert exc.value.public == {"toolkit": "GMAIL"}
        assert exc.value.meta == {
            "endpoint": "/x",
            "method": "GET",
            "provider_status": 401,
            "provider_response": {"error": "invalid_grant"},
        }

    def test_sdk_failure_is_a_502_carrying_the_request_identity(self) -> None:
        composio = _make_composio()
        composio.tools.proxy.side_effect = ConnectionError("boom")
        with _patch_primary(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(
                    ProxyRequest(user_id="u1", toolkit="GMAIL", endpoint="/x", method="POST")
                )
        assert exc.value.status_code == 502
        assert exc.value.meta == {
            "toolkit": "GMAIL",
            "endpoint": "/x",
            "method": "POST",
            "exception": "boom",
        }

    def test_an_account_composio_no_longer_holds_is_reported_as_gone(self) -> None:
        """Seen live: the tool path never recognised this 404, so the agent retried a dead account."""
        composio = _make_composio()
        composio.tools.proxy.side_effect = make_composio_not_found(
            {"error": {"code": 606, "slug": "ConnectedAccount_ResourceNotFound"}},
            'Connected account "ca_gone" not found',
        )
        with _patch_primary("ca_gone"), _patch_composio(composio):
            with pytest.raises(ConnectedAccountGoneError) as exc:
                proxy_request_sync(
                    ProxyRequest(user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET")
                )
        assert exc.value.code == INTEGRATION_NOT_CONNECTED
        assert exc.value.public == {"toolkit": "GMAIL"}

    def test_any_other_composio_404_stays_a_loud_502(self) -> None:
        composio = _make_composio()
        composio.tools.proxy.side_effect = make_composio_not_found(
            {"error": {"code": 1404, "slug": "Tool_NotFound"}}, "Tool not found"
        )
        with _patch_primary(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(
                    ProxyRequest(user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET")
                )
        assert not isinstance(exc.value, ConnectedAccountGoneError)
        assert exc.value.status_code == 502

    def test_request_identity_is_recorded_on_the_wide_event(self) -> None:
        log.reset()
        composio = _make_composio()
        with _patch_primary(), _patch_composio(composio):
            proxy_request_sync(
                ProxyRequest(user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET")
            )
        assert log.get()["composio_proxy"] == {
            "toolkit": "GMAIL",
            "endpoint": "/x",
            "method": "GET",
            "user_id": "u1",
        }


class TestProxyRequestAsync:
    @pytest.mark.asyncio
    async def test_async_delegates_to_sync(self) -> None:
        composio = _make_composio(proxy_data={"async": True})
        with _patch_primary(), _patch_composio(composio):
            result = await proxy_request(
                ProxyRequest(
                    user_id="u1",
                    toolkit="GMAIL",
                    endpoint="/x",
                    method="GET",
                )
            )
        assert result == {"async": True}
        composio.tools.proxy.assert_called_once()
