"""Tests for app.services.composio.proxy_client."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.constants.log_tags import LogTag
from app.services.composio import proxy_client
from app.services.composio.proxy_client import (
    _build_parameters,
    _resolve_connected_account_id,
    _toolkit_to_auth_config_id,
    invalidate_connected_account_cache,
    proxy_request,
    proxy_request_full_sync,
    proxy_request_sync,
)
from app.utils.errors import AppError


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_connected_account_cache()
    yield
    invalidate_connected_account_cache()


def _make_account(
    account_id: str = "acc_active",
    active: bool = True,
    is_disabled: bool = False,
) -> MagicMock:
    account = MagicMock()
    account.id = account_id
    account.status = "ACTIVE" if active else "INACTIVE"
    account.auth_config.is_disabled = is_disabled
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


def _seed_cache(entries: dict[tuple[str, str], str]) -> None:
    proxy_client._connected_account_cache.update(
        {key: (account_id, 1_000_000_000_000.0) for key, account_id in entries.items()}
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

    def test_expands_tuple_query_values(self) -> None:
        params = _build_parameters(None, {"ids": ("a", "b")})
        assert params == [
            {"name": "ids", "type": "query", "value": "a"},
            {"name": "ids", "type": "query", "value": "b"},
        ]

    def test_coerces_header_and_query_values_to_string(self) -> None:
        params = _build_parameters({"X-Num": 5}, {"flag": True, "n": 3})
        assert params == [
            {"name": "X-Num", "type": "header", "value": "5"},
            {"name": "flag", "type": "query", "value": "True"},
            {"name": "n", "type": "query", "value": "3"},
        ]

    def test_combines_headers_and_query(self) -> None:
        params = _build_parameters({"H": "1"}, {"q": "x"})
        assert params == [
            {"name": "H", "type": "header", "value": "1"},
            {"name": "q", "type": "query", "value": "x"},
        ]


class TestToolkitToAuthConfigId:
    def test_matches_toolkit_case_insensitively(self) -> None:
        config = SimpleNamespace(toolkit="Gmail", auth_config_id="ac_1")
        with patch.object(
            proxy_client, "get_composio_social_configs", return_value={"gmail": config}
        ):
            assert _toolkit_to_auth_config_id("GMAIL") == "ac_1"
            assert _toolkit_to_auth_config_id("gmail") == "ac_1"

    def test_returns_none_when_no_config_matches(self) -> None:
        config = SimpleNamespace(toolkit="GMAIL", auth_config_id="ac_1")
        with patch.object(
            proxy_client, "get_composio_social_configs", return_value={"gmail": config}
        ):
            assert _toolkit_to_auth_config_id("SLACK") is None

    def test_skips_configs_without_a_toolkit(self) -> None:
        config = SimpleNamespace(toolkit=None, auth_config_id="ac_1")
        with patch.object(
            proxy_client, "get_composio_social_configs", return_value={"bare": config}
        ):
            assert _toolkit_to_auth_config_id("GMAIL") is None


class TestResolveConnectedAccountId:
    @pytest.mark.parametrize("user_id", ["", None])
    def test_raises_on_missing_user_id(self, user_id: str | None) -> None:
        composio = _make_composio()
        with (
            _patch_auth_config(),
            _patch_composio(composio),
            patch.object(proxy_client, "log") as mock_log,
        ):
            with pytest.raises(AppError) as exc:
                _resolve_connected_account_id(user_id, "GMAIL")
        err = exc.value
        assert err.status_code == 500
        assert err.message == "Missing user_id for Composio proxy request"
        assert err.why == "proxy_request requires a user_id to resolve the connected account"
        assert err.meta == {"toolkit": "GMAIL"}
        composio.connected_accounts.list.assert_not_called()
        mock_log.error.assert_called_once_with("composio_proxy_missing_user_id", toolkit="GMAIL")

    def test_raises_when_toolkit_unknown(self) -> None:
        composio = _make_composio()
        with (
            _patch_auth_config(auth_config_id=None),
            _patch_composio(composio),
            patch.object(proxy_client, "log") as mock_log,
        ):
            with pytest.raises(AppError) as exc:
                _resolve_connected_account_id("u1", "WHATSAPP")
        err = exc.value
        assert err.status_code == 500
        assert err.message == "Unknown Composio toolkit: WHATSAPP"
        assert err.why == "No registered auth config matches this toolkit slug"
        assert err.meta == {"toolkit": "WHATSAPP", "user_id": "u1"}
        composio.connected_accounts.list.assert_not_called()
        mock_log.error.assert_called_once_with(
            "composio_proxy_unknown_toolkit", toolkit="WHATSAPP", user_id="u1"
        )

    def test_lists_accounts_with_exact_args(self) -> None:
        composio = _make_composio(account_id="acc_xyz")
        with _patch_auth_config(), _patch_composio(composio):
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_xyz"
        composio.connected_accounts.list.assert_called_once_with(
            user_ids=["u1"], auth_config_ids=["ac_test"], limit=10
        )

    def test_propagates_app_error_from_list(self) -> None:
        composio = _make_composio()
        original = AppError(message="original", why="why", status_code=503, meta={"x": 1})
        composio.connected_accounts.list.side_effect = original
        with _patch_auth_config(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                _resolve_connected_account_id("u1", "GMAIL")
        assert exc.value is original

    def test_wraps_list_exception_in_app_error(self) -> None:
        composio = _make_composio()
        composio.connected_accounts.list.side_effect = RuntimeError("list boom")
        with (
            _patch_auth_config(),
            _patch_composio(composio),
            patch.object(proxy_client, "log") as mock_log,
        ):
            with pytest.raises(AppError) as exc:
                _resolve_connected_account_id("u1", "GMAIL")
        err = exc.value
        assert err.status_code == 502
        assert err.message == "Composio connected_accounts.list failed: list boom"
        assert err.why == "SDK or transport error while resolving the connected account"
        assert err.meta == {
            "toolkit": "GMAIL",
            "user_id": "u1",
            "exception": "list boom",
        }
        assert isinstance(err.__cause__, RuntimeError)
        mock_log.error.assert_called_once_with(
            f"{LogTag.COMPOSIO} composio.connected_accounts.list failed",
            user_id="u1",
            toolkit="GMAIL",
            error="list boom",
            error_type="RuntimeError",
        )

    def test_raises_when_no_active_account(self) -> None:
        composio = MagicMock()
        accounts = MagicMock()
        accounts.items = [_make_account(active=False)]
        composio.connected_accounts.list.return_value = accounts
        with _patch_auth_config(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                _resolve_connected_account_id("u1", "GMAIL")
        err = exc.value
        assert err.status_code == 403
        assert err.message == "No active GMAIL connection"
        assert err.why == "User u1 has no active connected account for GMAIL"
        assert err.fix == "Reconnect the GMAIL integration"
        assert err.meta == {
            "toolkit": "GMAIL",
            "user_id": "u1",
            "error_code": INTEGRATION_NOT_CONNECTED,
        }

    def test_raises_when_only_disabled_accounts(self) -> None:
        composio = MagicMock()
        accounts = MagicMock()
        accounts.items = [_make_account(active=True, is_disabled=True)]
        composio.connected_accounts.list.return_value = accounts
        with _patch_auth_config(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                _resolve_connected_account_id("u1", "GMAIL")
        assert exc.value.status_code == 403

    def test_selects_first_active_non_disabled_account(self) -> None:
        composio = MagicMock()
        accounts = MagicMock()
        accounts.items = [
            _make_account("acc_disabled", active=True, is_disabled=True),
            _make_account("acc_inactive", active=False),
            _make_account("acc_first"),
            _make_account("acc_second"),
        ]
        composio.connected_accounts.list.return_value = accounts
        with _patch_auth_config(), _patch_composio(composio):
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_first"

    def test_no_active_account_logs_summary_of_first_five(self) -> None:
        composio = MagicMock()
        accounts = MagicMock()
        accounts.items = [_make_account(f"acc_{i}", active=False) for i in range(7)]
        composio.connected_accounts.list.return_value = accounts
        with (
            _patch_auth_config(),
            _patch_composio(composio),
            patch.object(proxy_client, "log") as mock_log,
        ):
            with pytest.raises(AppError):
                _resolve_connected_account_id("u1", "GMAIL")
        mock_log.warning.assert_called_once_with(
            f"{LogTag.COMPOSIO} composio: no ACTIVE account for this user and toolkit",
            user_id="u1",
            toolkit="GMAIL",
            total_accounts=7,
            account_summary=[
                {"id": "acc_0", "status": "INACTIVE", "is_disabled": False},
                {"id": "acc_1", "status": "INACTIVE", "is_disabled": False},
                {"id": "acc_2", "status": "INACTIVE", "is_disabled": False},
                {"id": "acc_3", "status": "INACTIVE", "is_disabled": False},
                {"id": "acc_4", "status": "INACTIVE", "is_disabled": False},
            ],
        )

    def test_no_active_account_logs_missing_attribute_defaults(self) -> None:
        composio = MagicMock()
        accounts = MagicMock()
        accounts.items = [SimpleNamespace(status="INACTIVE") for _ in range(3)]
        composio.connected_accounts.list.return_value = accounts
        with (
            _patch_auth_config(),
            _patch_composio(composio),
            patch.object(proxy_client, "log") as mock_log,
        ):
            with pytest.raises(AppError):
                _resolve_connected_account_id("u1", "GMAIL")
        mock_log.warning.assert_called_once_with(
            f"{LogTag.COMPOSIO} composio: no ACTIVE account for this user and toolkit",
            user_id="u1",
            toolkit="GMAIL",
            total_accounts=3,
            account_summary=[
                {"id": "?", "status": "INACTIVE", "is_disabled": "?"},
                {"id": "?", "status": "INACTIVE", "is_disabled": "?"},
                {"id": "?", "status": "INACTIVE", "is_disabled": "?"},
            ],
        )

    def test_returns_active_account_id(self) -> None:
        composio = _make_composio(account_id="acc_xyz")
        with _patch_auth_config(), _patch_composio(composio):
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_xyz"

    def test_caches_lookup_per_user_toolkit(self) -> None:
        composio = _make_composio(account_id="acc_xyz")
        with _patch_auth_config(), _patch_composio(composio):
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_xyz"
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_xyz"
        assert composio.connected_accounts.list.call_count == 1

    def test_cache_key_is_case_insensitive_for_toolkit(self) -> None:
        composio = _make_composio(account_id="acc_xyz")
        with _patch_auth_config(), _patch_composio(composio):
            _resolve_connected_account_id("u1", "gmail")
            _resolve_connected_account_id("u1", "GMAIL")
        assert composio.connected_accounts.list.call_count == 1

    def test_cache_keyed_per_user(self) -> None:
        composio = _make_composio()
        with _patch_auth_config(), _patch_composio(composio):
            _resolve_connected_account_id("u1", "GMAIL")
            _resolve_connected_account_id("u2", "GMAIL")
        assert composio.connected_accounts.list.call_count == 2

    def test_resolves_again_when_cache_entry_expired(self) -> None:
        composio = _make_composio(account_id="acc_fresh")
        now = 1_000_000.0
        with (
            patch.object(proxy_client.time, "time", return_value=now),
            _patch_auth_config(),
            _patch_composio(composio),
        ):
            proxy_client._connected_account_cache[("u1", "GMAIL")] = ("acc_stale", now - 1)
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_fresh"
        assert composio.connected_accounts.list.call_count == 1

    def test_cache_hit_at_exact_expiry_is_treated_as_expired(self) -> None:
        composio = _make_composio(account_id="acc_fresh")
        now = 1_000_000.0
        with (
            patch.object(proxy_client.time, "time", return_value=now),
            _patch_auth_config(),
            _patch_composio(composio),
        ):
            proxy_client._connected_account_cache[("u1", "GMAIL")] = ("acc_stale", now)
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_fresh"
        assert composio.connected_accounts.list.call_count == 1

    def test_caches_account_id_with_ttl(self) -> None:
        composio = _make_composio(account_id="acc_xyz")
        now = 1_000_000.0
        with (
            patch.object(proxy_client.time, "time", return_value=now),
            _patch_auth_config(),
            _patch_composio(composio),
            patch.object(proxy_client, "log") as mock_log,
        ):
            assert _resolve_connected_account_id("u1", "GMAIL") == "acc_xyz"
        assert proxy_client._connected_account_cache == {("u1", "GMAIL"): ("acc_xyz", now + 600)}
        mock_log.info.assert_called_once_with(
            f"{LogTag.COMPOSIO} composio: resolved connected_account_id and cached it",
            user_id="u1",
            toolkit="GMAIL",
            id="acc_xyz",
            _connected_account_cache_ttl_seconds=600,
        )

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
        composio.tools.proxy.assert_called_once_with(
            endpoint="https://gmail.googleapis.com/x",
            method="GET",
            connected_account_id="acc_active",
        )

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
        composio.tools.proxy.assert_called_once_with(
            endpoint="/x",
            method="POST",
            connected_account_id="acc_active",
            parameters=[
                {"name": "Content-Type", "type": "header", "value": "application/json"},
                {"name": "page", "type": "query", "value": "2"},
            ],
            body={"a": 1},
        )

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
        composio.tools.proxy.assert_called_once_with(
            endpoint="/upload",
            method="POST",
            connected_account_id="acc_active",
            binary_body={"url": "https://x/y", "content_type": "image/png"},
        )

    def test_empty_binary_body_still_sent(self) -> None:
        composio = _make_composio()
        with _patch_auth_config(), _patch_composio(composio):
            proxy_request_sync(
                user_id="u1",
                toolkit="GMAIL",
                endpoint="/upload",
                method="POST",
                body={"ignored": True},
                binary_body={},
            )
        composio.tools.proxy.assert_called_once_with(
            endpoint="/upload",
            method="POST",
            connected_account_id="acc_active",
            binary_body={},
        )

    def test_empty_dict_body_still_sent(self) -> None:
        composio = _make_composio()
        with _patch_auth_config(), _patch_composio(composio):
            proxy_request_sync(
                user_id="u1",
                toolkit="GMAIL",
                endpoint="/x",
                method="POST",
                body={},
            )
        composio.tools.proxy.assert_called_once_with(
            endpoint="/x", method="POST", connected_account_id="acc_active", body={}
        )

    def test_empty_headers_and_query_omit_parameters(self) -> None:
        composio = _make_composio()
        with _patch_auth_config(), _patch_composio(composio):
            proxy_request_sync(
                user_id="u1",
                toolkit="GMAIL",
                endpoint="/x",
                method="GET",
                headers={},
                query={},
            )
        composio.tools.proxy.assert_called_once_with(
            endpoint="/x", method="GET", connected_account_id="acc_active"
        )

    def test_sets_proxy_context_on_log(self) -> None:
        composio = _make_composio()
        with (
            _patch_auth_config(),
            _patch_composio(composio),
            patch.object(proxy_client, "log") as mock_log,
        ):
            proxy_request_sync(
                user_id="u1",
                toolkit="GMAIL",
                endpoint="/x",
                method="POST",
            )
        mock_log.set.assert_called_once_with(
            composio_proxy={
                "toolkit": "GMAIL",
                "endpoint": "/x",
                "method": "POST",
                "user_id": "u1",
            }
        )

    def test_raises_app_error_on_non_2xx(self) -> None:
        composio = _make_composio(proxy_status=404, proxy_data={"err": "missing"})
        with _patch_auth_config(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET")
        err = exc.value
        assert err.status_code == 404
        assert err.message == "GMAIL API error (404)"
        assert err.why == "Provider returned non-2xx for GET /x"
        assert err.meta == {
            "toolkit": "GMAIL",
            "endpoint": "/x",
            "method": "GET",
            "provider_status": 404,
            "provider_response": {"err": "missing"},
        }

    def test_400_passes_provider_status(self) -> None:
        composio = _make_composio(proxy_status=400, proxy_data={"err": "bad"})
        with _patch_auth_config(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET")
        assert exc.value.status_code == 400

    def test_500_passes_through(self) -> None:
        composio = _make_composio(proxy_status=500, proxy_data={"err": "oops"})
        with _patch_auth_config(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET")
        assert exc.value.status_code == 500

    def test_600_maps_to_502(self) -> None:
        composio = _make_composio(proxy_status=600, proxy_data={"err": "weird"})
        with _patch_auth_config(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET")
        assert exc.value.status_code == 502

    def test_401_maps_to_403_and_invalidates_cache(self) -> None:
        composio = _make_composio(proxy_status=401, proxy_data={"err": "expired"})
        _seed_cache(
            {
                ("u1", "GMAIL"): "a",
                ("u1", "SLACK"): "b",
                ("u2", "GMAIL"): "c",
                ("u2", "SLACK"): "d",
            }
        )
        with _patch_auth_config(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET")
        err = exc.value
        assert err.status_code == 403
        assert err.meta == {
            "toolkit": "GMAIL",
            "endpoint": "/x",
            "method": "GET",
            "provider_status": 401,
            "provider_response": {"err": "expired"},
            "error_code": INTEGRATION_NOT_CONNECTED,
        }
        assert proxy_client._connected_account_cache == {
            ("u1", "SLACK"): ("b", 1_000_000_000_000.0),
            ("u2", "GMAIL"): ("c", 1_000_000_000_000.0),
            ("u2", "SLACK"): ("d", 1_000_000_000_000.0),
        }

    def test_propagates_app_error_from_proxy(self) -> None:
        composio = _make_composio()
        original = AppError(message="provider said no", why="w", status_code=429, meta={"m": 1})
        composio.tools.proxy.side_effect = original
        with _patch_auth_config(), _patch_composio(composio):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET")
        assert exc.value is original

    def test_wraps_proxy_exception_in_app_error(self) -> None:
        composio = _make_composio()
        composio.tools.proxy.side_effect = RuntimeError("proxy boom")
        with (
            _patch_auth_config(),
            _patch_composio(composio),
            patch.object(proxy_client, "log") as mock_log,
        ):
            with pytest.raises(AppError) as exc:
                proxy_request_sync(user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET")
        err = exc.value
        assert err.status_code == 502
        assert err.message == "Composio tools.proxy failed: proxy boom"
        assert err.why == "SDK or transport error while calling the provider"
        assert err.meta == {
            "toolkit": "GMAIL",
            "endpoint": "/x",
            "method": "GET",
            "exception": "proxy boom",
        }
        assert isinstance(err.__cause__, RuntimeError)
        mock_log.error.assert_called_once_with(
            f"{LogTag.COMPOSIO} composio.tools.proxy raised",
            user_id="u1",
            toolkit="GMAIL",
            method="GET",
            endpoint="/x",
            error="proxy boom",
            error_type="RuntimeError",
        )


class TestProxyRequestFullSync:
    def test_returns_status_data_and_normalized_headers(self) -> None:
        composio = _make_composio()
        response = MagicMock()
        response.status = "201"
        response.data = {"id": "n1"}
        response.headers = {"X-RestLi-Id": "123", "Content-Type": "application/json"}
        composio.tools.proxy.return_value = response
        with _patch_auth_config(), _patch_composio(composio):
            result = proxy_request_full_sync(
                user_id="u1",
                toolkit="GMAIL",
                endpoint="/x",
                method="POST",
                body={},
            )
        assert result == {
            "status": 201,
            "data": {"id": "n1"},
            "headers": {"x-restli-id": "123", "content-type": "application/json"},
        }
        composio.tools.proxy.assert_called_once_with(
            endpoint="/x", method="POST", connected_account_id="acc_active", body={}
        )

    def test_forwards_all_call_arguments(self) -> None:
        composio = _make_composio()
        with _patch_auth_config(), _patch_composio(composio):
            proxy_request_full_sync(
                user_id="u1",
                toolkit="GMAIL",
                endpoint="/x",
                method="POST",
                body={"a": 1},
                query={"page": 2},
                headers={"X-H": "1"},
                binary_body={"url": "u"},
            )
        composio.tools.proxy.assert_called_once_with(
            endpoint="/x",
            method="POST",
            connected_account_id="acc_active",
            parameters=[
                {"name": "X-H", "type": "header", "value": "1"},
                {"name": "page", "type": "query", "value": "2"},
            ],
            binary_body={"url": "u"},
        )

    def test_missing_headers_yield_empty_headers(self) -> None:
        composio = _make_composio()
        response = MagicMock()
        response.status = 200
        response.data = {"ok": True}
        response.headers = None
        composio.tools.proxy.return_value = response
        with _patch_auth_config(), _patch_composio(composio):
            result = proxy_request_full_sync(
                user_id="u1", toolkit="GMAIL", endpoint="/x", method="GET"
            )
        assert result == {"status": 200, "data": {"ok": True}, "headers": {}}


class TestProxyRequestAsync:
    @pytest.mark.asyncio
    async def test_async_delegates_to_sync_with_exact_args(self) -> None:
        sentinel = {"async": True}
        with patch(
            "app.services.composio.proxy_client.asyncio.to_thread", new_callable=AsyncMock
        ) as mock_thread:
            mock_thread.return_value = sentinel
            result = await proxy_request(
                user_id="u1",
                toolkit="GMAIL",
                endpoint="/x",
                method="POST",
                body={"a": 1},
                query={"q": "v"},
                headers={"H": "1"},
                binary_body={"url": "u"},
            )
        assert result == sentinel
        mock_thread.assert_awaited_once_with(
            proxy_request_sync,
            user_id="u1",
            toolkit="GMAIL",
            endpoint="/x",
            method="POST",
            body={"a": 1},
            query={"q": "v"},
            headers={"H": "1"},
            binary_body={"url": "u"},
        )


class TestInvalidateConnectedAccountCache:
    def test_clear_all_when_no_args(self) -> None:
        _seed_cache({("u1", "GMAIL"): "a", ("u1", "SLACK"): "b", ("u2", "GMAIL"): "c"})
        invalidate_connected_account_cache()
        assert proxy_client._connected_account_cache == {}

    def test_invalidate_by_user_keeps_other_users(self) -> None:
        _seed_cache({("u1", "GMAIL"): "a", ("u1", "SLACK"): "b", ("u2", "GMAIL"): "c"})
        invalidate_connected_account_cache(user_id="u1")
        assert proxy_client._connected_account_cache == {
            ("u2", "GMAIL"): ("c", 1_000_000_000_000.0)
        }

    def test_invalidate_by_toolkit_keeps_other_toolkits(self) -> None:
        _seed_cache({("u1", "GMAIL"): "a", ("u1", "SLACK"): "b", ("u2", "GMAIL"): "c"})
        invalidate_connected_account_cache(toolkit="GMAIL")
        assert proxy_client._connected_account_cache == {
            ("u1", "SLACK"): ("b", 1_000_000_000_000.0)
        }

    def test_invalidate_by_toolkit_is_case_insensitive(self) -> None:
        _seed_cache({("u1", "GMAIL"): "a", ("u1", "SLACK"): "b"})
        invalidate_connected_account_cache(toolkit="gmail")
        assert proxy_client._connected_account_cache == {
            ("u1", "SLACK"): ("b", 1_000_000_000_000.0)
        }

    def test_invalidate_by_both_only_removes_matching_key(self) -> None:
        _seed_cache({("u1", "GMAIL"): "a", ("u1", "SLACK"): "b", ("u2", "GMAIL"): "c"})
        invalidate_connected_account_cache(user_id="u1", toolkit="GMAIL")
        assert proxy_client._connected_account_cache == {
            ("u1", "SLACK"): ("b", 1_000_000_000_000.0),
            ("u2", "GMAIL"): ("c", 1_000_000_000_000.0),
        }

    def test_invalidate_with_no_matches_leaves_cache_intact(self) -> None:
        _seed_cache({("u1", "GMAIL"): "a", ("u1", "SLACK"): "b"})
        invalidate_connected_account_cache(user_id="ghost", toolkit="GMAIL")
        assert proxy_client._connected_account_cache == {
            ("u1", "GMAIL"): ("a", 1_000_000_000_000.0),
            ("u1", "SLACK"): ("b", 1_000_000_000_000.0),
        }
