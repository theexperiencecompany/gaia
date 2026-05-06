"""Tests for app.services.composio.proxy_client."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.composio import proxy_client
from app.services.composio.proxy_client import (
    _build_parameters,
    _resolve_connected_account_id,
    invalidate_connected_account_cache,
    proxy_request,
    proxy_request_sync,
)
from app.utils.errors import AppError


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_connected_account_cache()
    yield
    invalidate_connected_account_cache()


def _make_account(account_id: str = "acc_active", active: bool = True) -> MagicMock:
    account = MagicMock()
    account.id = account_id
    account.status = "ACTIVE" if active else "INACTIVE"
    account.auth_config.is_disabled = False
    return account


def _make_composio(
    account_id: str = "acc_active",
    proxy_status: int = 200,
    proxy_data: Any = None,
) -> MagicMock:
    composio = MagicMock()
    accounts = MagicMock()
    accounts.items = [_make_account(account_id=account_id)]
    composio.connected_accounts.list.return_value = accounts

    response = MagicMock()
    response.status = proxy_status
    response.data = proxy_data if proxy_data is not None else {"ok": True}
    composio.tools.proxy.return_value = response
    return composio


def _patch_composio(composio: MagicMock):
    return patch.object(proxy_client, "_get_composio", return_value=composio)


def _patch_auth_config(toolkit: str = "GMAIL", auth_config_id: str | None = "ac_test"):
    return patch.object(
        proxy_client,
        "_toolkit_to_auth_config_id",
        side_effect=lambda t: auth_config_id if t.upper() == toolkit else None,
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

    def test_raises_when_toolkit_unknown(self) -> None:
        with _patch_auth_config(auth_config_id=None):
            with pytest.raises(AppError) as exc:
                _resolve_connected_account_id("u1", "WHATSAPP")
        assert "Unknown" in exc.value.message

    def test_raises_when_no_active_account(self) -> None:
        composio = MagicMock()
        accounts = MagicMock()
        accounts.items = [_make_account(active=False)]
        composio.connected_accounts.list.return_value = accounts
        with _patch_auth_config(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                _resolve_connected_account_id("u1", "GMAIL")
        assert exc.value.status_code == 401

    def test_returns_active_account_id(self) -> None:
        composio = _make_composio(account_id="acc_xyz")
        with _patch_auth_config(), _patch_composio(composio):
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_xyz"

    def test_caches_lookup_per_user_toolkit(self) -> None:
        composio = _make_composio(account_id="acc_xyz")
        with _patch_auth_config(), _patch_composio(composio):
            _resolve_connected_account_id("u1", "GMAIL")
            _resolve_connected_account_id("u1", "GMAIL")
        assert composio.connected_accounts.list.call_count == 1

    def test_cache_keyed_per_user(self) -> None:
        composio = _make_composio()
        with _patch_auth_config(), _patch_composio(composio):
            _resolve_connected_account_id("u1", "GMAIL")
            _resolve_connected_account_id("u2", "GMAIL")
        assert composio.connected_accounts.list.call_count == 2

    def test_invalidate_clears_cache(self) -> None:
        composio = _make_composio()
        with _patch_auth_config(), _patch_composio(composio):
            _resolve_connected_account_id("u1", "GMAIL")
            invalidate_connected_account_cache(user_id="u1", toolkit="GMAIL")
            _resolve_connected_account_id("u1", "GMAIL")
        assert composio.connected_accounts.list.call_count == 2


class TestProxyRequestSync:
    def test_sends_basic_request(self) -> None:
        composio = _make_composio(proxy_data={"hello": "world"})
        with _patch_auth_config(), _patch_composio(composio):
            result = proxy_request_sync(
                user_id="u1",
                toolkit="GMAIL",
                endpoint="https://gmail.googleapis.com/x",
                method="GET",
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
        with _patch_auth_config(), _patch_composio(composio):
            proxy_request_sync(
                user_id="u1",
                toolkit="GMAIL",
                endpoint="/x",
                method="POST",
                body={"a": 1},
                headers={"Content-Type": "application/json"},
                query={"page": 2},
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
        with _patch_auth_config(), _patch_composio(composio):
            proxy_request_sync(
                user_id="u1",
                toolkit="GMAIL",
                endpoint="/upload",
                method="POST",
                body={"ignored": True},
                binary_body={"url": "https://x/y", "content_type": "image/png"},
            )
        kwargs = composio.tools.proxy.call_args.kwargs
        assert kwargs["binary_body"] == {
            "url": "https://x/y",
            "content_type": "image/png",
        }
        assert "body" not in kwargs

    def test_raises_app_error_on_non_2xx(self) -> None:
        composio = _make_composio(proxy_status=404, proxy_data={"err": "missing"})
        with _patch_auth_config(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(
                    user_id="u1",
                    toolkit="GMAIL",
                    endpoint="/x",
                    method="GET",
                )
        assert exc.value.status_code == 404
        assert exc.value.meta["provider_status"] == 404
        assert exc.value.meta["provider_response"] == {"err": "missing"}


class TestProxyRequestAsync:
    @pytest.mark.asyncio
    async def test_async_delegates_to_sync(self) -> None:
        composio = _make_composio(proxy_data={"async": True})
        with _patch_auth_config(), _patch_composio(composio):
            result = await proxy_request(
                user_id="u1",
                toolkit="GMAIL",
                endpoint="/x",
                method="GET",
            )
        assert result == {"async": True}
        composio.tools.proxy.assert_called_once()
