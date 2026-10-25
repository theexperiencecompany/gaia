"""Tests for ComposioService and Gmail custom tools."""

from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import composio_client
import httpx
import pytest

from app.config.oauth_config import get_integration_by_id
from app.config.settings import settings
from app.constants.integrations import (
    COMPOSIO_ACCOUNT_LIST_LIMIT,
    COMPOSIO_AUTH_CONFIG_PAGE_SIZE,
    COMPOSIO_SERVICE_PROVIDER,
    GMAIL_INTEGRATION_ID,
)
from app.services.composio import auth_config_resolver
from app.services.providers.provider_credentials_service import ProviderConfig
from app.utils.exceptions import ProviderNotConfiguredError
from shared.py.wide_events import log
from tests.helpers import captured_wide_event

# An env override: the resolver reads it with no store or Composio project behind it.
GMAIL_AC = "ac_test_gmail"

# ---------------------------------------------------------------------------
# ComposioService tests
# ---------------------------------------------------------------------------


class TestComposioServiceInit:
    """Tests for ComposioService.__init__."""

    @patch("app.services.composio.composio_service.custom_tools_registry")
    @patch("app.services.composio.composio_service.LangchainProvider")
    @patch("app.services.composio.composio_service.Composio")
    def test_init_no_toolkit_versions(self, mock_composio_cls, mock_provider_cls, mock_registry):
        mock_provider = MagicMock()
        mock_provider_cls.return_value = mock_provider
        mock_composio_cls.return_value = MagicMock()

        with patch("app.config.oauth_config.OAUTH_INTEGRATIONS", []):
            from app.services.composio.composio_service import ComposioService

            svc = ComposioService(api_key="test-key")
        mock_composio_cls.assert_called_once_with(
            provider=mock_provider,
            api_key="test-key",
            timeout=120,
            toolkit_versions=None,
        )
        mock_registry.initialize.assert_called_once_with(svc.composio)

    @patch("app.services.composio.composio_service.custom_tools_registry")
    @patch("app.services.composio.composio_service.LangchainProvider")
    @patch("app.services.composio.composio_service.Composio")
    def test_init_with_toolkit_versions(self, mock_composio_cls, mock_provider_cls, mock_registry):
        integration = MagicMock()
        integration.composio_config.toolkit_version = "1.2.3"
        integration.composio_config.toolkit.lower.return_value = "gmail"

        with patch(
            "app.config.oauth_config.OAUTH_INTEGRATIONS",
            [integration],
        ):
            from app.services.composio.composio_service import ComposioService

            ComposioService(api_key="key")
            call_kwargs = mock_composio_cls.call_args[1]
            assert call_kwargs["toolkit_versions"] == {"gmail": "1.2.3"}

    @patch("app.services.composio.composio_service.custom_tools_registry")
    @patch("app.services.composio.composio_service.LangchainProvider")
    @patch("app.services.composio.composio_service.Composio")
    def test_init_skips_none_composio_config(
        self, mock_composio_cls, mock_provider_cls, mock_registry
    ):
        integration = MagicMock()
        integration.composio_config = None

        with patch(
            "app.config.oauth_config.OAUTH_INTEGRATIONS",
            [integration],
        ):
            from app.services.composio.composio_service import ComposioService

            ComposioService(api_key="key")
            call_kwargs = mock_composio_cls.call_args[1]
            assert call_kwargs["toolkit_versions"] is None


def _make_service():
    """Create a ComposioService with mocked internals."""
    with (
        patch("app.services.composio.composio_service.custom_tools_registry"),
        patch("app.services.composio.composio_service.LangchainProvider"),
        patch("app.services.composio.composio_service.Composio") as cls,
        patch("app.config.oauth_config.OAUTH_INTEGRATIONS", []),
    ):
        from app.services.composio.composio_service import ComposioService

        cls.return_value = MagicMock()
        svc = ComposioService(api_key="key")
    return svc


class TestConnectAccount:
    @pytest.mark.asyncio
    async def test_unsupported_provider_raises(self):
        svc = _make_service()
        with patch(
            "app.services.composio.composio_service.get_composio_integrations_by_provider",
            return_value={},
        ):
            with pytest.raises(ValueError, match="not supported"):
                await svc.connect_account("unsupported", "user1", "tok")

    @pytest.mark.asyncio
    async def test_a_new_account_link_returns_to_the_callback_with_its_state(self):
        svc = _make_service()

        connection_request = MagicMock()
        connection_request.redirect_url = "https://example.com/redirect"
        connection_request.id = "conn123"

        svc.composio.connected_accounts.link.return_value = connection_request

        with (
            patch.object(settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {"gmail": GMAIL_AC}),
            patch(
                "app.services.composio.composio_service.settings",
                MagicMock(COMPOSIO_REDIRECT_URI="https://example.com/cb"),
            ),
        ):
            result = await svc.connect_account("gmail", "user1", state_token="tok")

        assert result == {
            "status": "pending",
            "redirect_url": "https://example.com/redirect",
            "connection_id": "conn123",
        }
        svc.composio.connected_accounts.link.assert_called_once_with(
            user_id="user1",
            auth_config_id=GMAIL_AC,
            callback_url="https://example.com/cb?state=tok",
            allow_multiple=True,
        )

    @pytest.mark.asyncio
    async def test_connect_account_propagates_exception(self):
        svc = _make_service()
        svc.composio.connected_accounts.link.side_effect = RuntimeError("boom")

        with (
            patch.object(settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {"gmail": GMAIL_AC}),
            patch(
                "app.services.composio.composio_service.settings",
                MagicMock(COMPOSIO_REDIRECT_URI="https://example.com/cb"),
            ),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await svc.connect_account("gmail", "user1", "tok")


class TestReauthorizeAccount:
    @pytest.mark.asyncio
    async def test_the_same_account_is_sent_back_through_sign_in(self):
        svc = _make_service()
        svc.composio.connected_accounts.refresh.return_value = MagicMock(
            id="ca_work", status="INITIATED", redirect_url="https://composio.dev/s/abc"
        )

        with patch(
            "app.services.composio.composio_service.settings",
            MagicMock(COMPOSIO_REDIRECT_URI="https://example.com/cb"),
        ):
            async with captured_wide_event() as event:
                result = await svc.reauthorize_account("ca_work", "tok")

        assert event["composio_connected_account_id"] == "ca_work"
        assert result == {
            "status": "pending",
            "redirect_url": "https://composio.dev/s/abc",
            "connection_id": "ca_work",
        }
        svc.composio.connected_accounts.refresh.assert_called_once_with(
            "ca_work", body_redirect_url="https://example.com/cb?state=tok"
        )

    @pytest.mark.asyncio
    async def test_no_sign_in_url_is_an_error_not_a_dead_link(self):
        svc = _make_service()
        svc.composio.connected_accounts.refresh.return_value = MagicMock(
            id="ca_work", status="ACTIVE", redirect_url=None
        )

        with (
            patch(
                "app.services.composio.composio_service.settings",
                MagicMock(COMPOSIO_REDIRECT_URI="https://example.com/cb"),
            ),
            pytest.raises(RuntimeError) as exc,
        ):
            await svc.reauthorize_account("ca_work", "tok")

        assert str(exc.value) == "Composio returned no sign-in URL for ca_work (ACTIVE)"


class TestGetTools:
    @pytest.mark.asyncio
    async def test_get_tools_returns_filtered(self):
        svc = _make_service()
        tool1 = MagicMock(name="TOOL_A")
        tool1.name = "TOOL_A"
        tool1.description = "desc A"
        tool2 = MagicMock(name="TOOL_B")
        tool2.name = "TOOL_B"
        tool2.description = "desc B"

        # First call returns tool names, second call returns tools with modifiers
        svc.composio.tools.get = MagicMock(side_effect=[[tool1, tool2], [tool1, tool2]])

        with (
            patch("app.services.composio.composio_service.custom_tools_registry") as mock_reg,
            patch(
                "app.services.composio.composio_service.before_execute",
                return_value=lambda f: f,
            ),
            patch(
                "app.services.composio.composio_service.after_execute",
                return_value=lambda f: f,
            ),
            patch(
                "app.services.composio.composio_service.schema_modifier",
                return_value=lambda f: f,
            ),
        ):
            mock_reg.get_tool_names.return_value = []
            svc._store_tool_metadata = AsyncMock()

            result = await svc.get_tools("gmail", exclude_tools=["TOOL_B"])

        assert len(result) == 1
        assert result[0].name == "TOOL_A"

    @pytest.mark.asyncio
    async def test_get_tools_appends_custom_tools(self):
        svc = _make_service()
        tool1 = MagicMock()
        tool1.name = "TOOL_A"
        tool1.description = "desc"
        custom_tool = MagicMock()
        custom_tool.name = "CUSTOM_TOOL"
        custom_tool.description = "custom"

        svc.composio.tools.get = MagicMock(side_effect=[[tool1], [tool1]])

        with (
            patch("app.services.composio.composio_service.custom_tools_registry") as mock_reg,
            patch(
                "app.services.composio.composio_service.before_execute",
                return_value=lambda f: f,
            ),
            patch(
                "app.services.composio.composio_service.after_execute",
                return_value=lambda f: f,
            ),
            patch(
                "app.services.composio.composio_service.schema_modifier",
                return_value=lambda f: f,
            ),
        ):
            mock_reg.get_tool_names.return_value = ["CUSTOM_TOOL"]
            svc.get_tools_by_name = AsyncMock(return_value=[custom_tool])
            svc._store_tool_metadata = AsyncMock()

            result = await svc.get_tools("gmail")

        assert len(result) == 2
        names = [t.name for t in result]
        assert "TOOL_A" in names
        assert "CUSTOM_TOOL" in names


class TestStoreToolMetadata:
    @pytest.mark.asyncio
    async def test_stores_metadata(self):
        svc = _make_service()
        tool = MagicMock()
        tool.name = "TOOL_A"
        tool.description = "desc"

        with patch(
            "app.services.composio.composio_service.store_mcp_tools",
            new_callable=AsyncMock,
        ) as mock_store:
            await svc._store_tool_metadata("gmail", [tool])

        mock_store.assert_awaited_once_with("gmail", [{"name": "TOOL_A", "description": "desc"}])

    @pytest.mark.asyncio
    async def test_a_tool_without_a_description_is_stored_with_an_empty_one(self):
        svc = _make_service()
        tool = SimpleNamespace(name="TOOL_B")

        with patch(
            "app.services.composio.composio_service.store_mcp_tools",
            new_callable=AsyncMock,
        ) as mock_store:
            await svc._store_tool_metadata("gmail", [tool])

        mock_store.assert_awaited_once_with("gmail", [{"name": "TOOL_B", "description": ""}])

    @pytest.mark.asyncio
    async def test_empty_tools_returns_early(self):
        svc = _make_service()
        with patch(
            "app.services.composio.composio_service.store_mcp_tools",
            new_callable=AsyncMock,
        ) as mock_store:
            await svc._store_tool_metadata("gmail", [])
            mock_store.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_store_error_swallowed(self):
        svc = _make_service()
        tool = MagicMock()
        tool.name = "X"
        tool.description = ""

        with patch(
            "app.services.composio.composio_service.store_mcp_tools",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db fail"),
        ):
            # Should not raise
            await svc._store_tool_metadata("gmail", [tool])


class TestComposioEventTotals:
    """get_tools and get_tools_by_name add to the request's composio totals, never replace them."""

    @pytest.mark.asyncio
    async def test_get_tools_appends_its_toolkit_and_adds_its_tool_count(self):
        svc = _make_service()
        kept = MagicMock()
        kept.name = "TOOL_A"
        svc.composio.tools.get = MagicMock(side_effect=[[kept], [kept]])
        svc._store_tool_metadata = AsyncMock()
        log.reset()
        log.set(composio={"toolkits": ["slack"], "tools_loaded": 2, "provider": "kept"})

        with (
            patch("app.services.composio.composio_service.custom_tools_registry") as mock_reg,
            patch(
                "app.services.composio.composio_service.before_execute", return_value=lambda f: f
            ),
            patch("app.services.composio.composio_service.after_execute", return_value=lambda f: f),
            patch(
                "app.services.composio.composio_service.schema_modifier", return_value=lambda f: f
            ),
        ):
            mock_reg.get_tool_names.return_value = []
            await svc.get_tools("gmail")

        assert log.get()["composio"] == {
            "toolkits": ["slack", "gmail"],
            "tools_loaded": 3,
            "provider": "kept",
        }

    @pytest.mark.asyncio
    async def test_get_tools_by_name_adds_its_tool_count(self):
        svc = _make_service()
        tool = MagicMock()
        tool.name = "TOOL_A"
        svc.composio.tools.get = MagicMock(return_value=[tool])
        log.reset()
        log.set(composio={"tools_loaded": 4})

        with (
            patch(
                "app.services.composio.composio_service.before_execute", return_value=lambda f: f
            ),
            patch("app.services.composio.composio_service.after_execute", return_value=lambda f: f),
            patch(
                "app.services.composio.composio_service.schema_modifier", return_value=lambda f: f
            ),
        ):
            await svc.get_tools_by_name(["TOOL_A"])

        assert log.get()["composio"] == {"tools_loaded": 5}


class TestGetToolsByName:
    @pytest.mark.asyncio
    async def test_get_tools_by_name_all_hooks(self):
        svc = _make_service()
        tool = MagicMock()
        tool.name = "TOOL_A"
        svc.composio.tools.get = MagicMock(return_value=[tool])

        with (
            patch(
                "app.services.composio.composio_service.before_execute",
                return_value=lambda f: f,
            ),
            patch(
                "app.services.composio.composio_service.after_execute",
                return_value=lambda f: f,
            ),
            patch(
                "app.services.composio.composio_service.schema_modifier",
                return_value=lambda f: f,
            ),
        ):
            result = await svc.get_tools_by_name(["TOOL_A"])

        assert result == [tool]

    @pytest.mark.asyncio
    async def test_get_tools_by_name_no_hooks(self):
        svc = _make_service()
        svc.composio.tools.get = MagicMock(return_value=[])

        result = await svc.get_tools_by_name(
            ["TOOL_A"],
            use_before_hook=False,
            use_after_hook=False,
            use_schema_modifier=False,
        )

        assert result == []
        # Verify modifiers list is empty
        call_kwargs = svc.composio.tools.get.call_args[1]
        assert call_kwargs["modifiers"] == []


class TestGetTool:
    def test_get_tool_success(self):
        svc = _make_service()
        tool = MagicMock()
        tool.name = "TOOL_A"
        svc.composio.tools.get = MagicMock(return_value=[tool])

        with (
            patch(
                "app.services.composio.composio_service.before_execute",
                return_value=lambda f: f,
            ),
            patch(
                "app.services.composio.composio_service.after_execute",
                return_value=lambda f: f,
            ),
            patch(
                "app.services.composio.composio_service.schema_modifier",
                return_value=lambda f: f,
            ),
        ):
            result = svc.get_tool("TOOL_A")

        assert result == tool

    def test_get_tool_returns_none_on_empty(self):
        svc = _make_service()
        svc.composio.tools.get = MagicMock(return_value=[])

        with (
            patch(
                "app.services.composio.composio_service.before_execute",
                return_value=lambda f: f,
            ),
            patch(
                "app.services.composio.composio_service.after_execute",
                return_value=lambda f: f,
            ),
            patch(
                "app.services.composio.composio_service.schema_modifier",
                return_value=lambda f: f,
            ),
        ):
            result = svc.get_tool("MISSING")

        assert result is None

    def test_get_tool_returns_none_on_exception(self):
        svc = _make_service()
        svc.composio.tools.get = MagicMock(side_effect=RuntimeError("fail"))

        result = svc.get_tool("BAD")
        assert result is None

    def test_get_tool_no_hooks(self):
        svc = _make_service()
        svc.composio.tools.get = MagicMock(return_value=[])

        result = svc.get_tool(
            "X",
            use_before_hook=False,
            use_after_hook=False,
            use_schema_modifier=False,
        )
        assert result is None
        call_kwargs = svc.composio.tools.get.call_args[1]
        assert call_kwargs["modifiers"] == []


class TestCheckConnectionStatus:
    @pytest.mark.asyncio
    async def test_returns_connected_status(self):
        svc = _make_service()

        account = MagicMock()
        account.auth_config.is_disabled = False
        account.status = "ACTIVE"
        account.auth_config.id = GMAIL_AC

        user_accounts = MagicMock()
        user_accounts.items = [account]
        svc.composio.connected_accounts.list = MagicMock(return_value=user_accounts)

        with patch.object(settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {"gmail": GMAIL_AC}):
            result = await svc.check_connection_status(["gmail"], "user1")

        assert result == {"gmail": True}
        svc.composio.connected_accounts.list.assert_called_once_with(
            user_ids=["user1"],
            auth_config_ids=[GMAIL_AC],
            statuses=["ACTIVE"],
            limit=COMPOSIO_ACCOUNT_LIST_LIMIT,
        )

    @pytest.mark.asyncio
    async def test_returns_false_for_disabled(self):
        svc = _make_service()

        account = MagicMock()
        account.auth_config.is_disabled = True
        account.status = "ACTIVE"
        account.auth_config.id = GMAIL_AC

        user_accounts = MagicMock()
        user_accounts.items = [account]
        svc.composio.connected_accounts.list = MagicMock(return_value=user_accounts)

        with patch.object(settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {"gmail": GMAIL_AC}):
            result = await svc.check_connection_status(["gmail"], "user1")

        assert result == {"gmail": False}

    @pytest.mark.asyncio
    async def test_returns_false_for_unknown_provider(self):
        svc = _make_service()
        user_accounts = MagicMock()
        user_accounts.items = []
        svc.composio.connected_accounts.list = MagicMock(return_value=user_accounts)

        with patch(
            "app.services.composio.composio_service.get_composio_integrations_by_provider",
            return_value={},
        ):
            result = await svc.check_connection_status(["unknown"], "user1")

        assert result == {"unknown": False}

    @pytest.mark.asyncio
    async def test_returns_defaults_on_exception(self):
        svc = _make_service()
        svc.composio.connected_accounts.list = MagicMock(side_effect=RuntimeError("fail"))

        with patch.object(settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {"gmail": GMAIL_AC}):
            result = await svc.check_connection_status(["gmail"], "user1")

        assert result == {"gmail": False}


class TestListEnabledAuthConfigs:
    @pytest.mark.asyncio
    async def test_every_page_is_read_and_disabled_configs_are_dropped(self):
        svc = _make_service()
        pages = [
            SimpleNamespace(
                items=[
                    SimpleNamespace(id="ac_1", status="ENABLED"),
                    SimpleNamespace(id="ac_off", status="DISABLED"),
                ],
                next_cursor="page-2",
            ),
            SimpleNamespace(items=[SimpleNamespace(id="ac_2", status="ENABLED")], next_cursor=None),
        ]
        svc.composio.auth_configs.list = MagicMock(side_effect=pages)

        configs = await svc.list_enabled_auth_configs()

        assert [c.id for c in configs] == ["ac_1", "ac_2"]
        assert [c.kwargs for c in svc.composio.auth_configs.list.call_args_list] == [
            {"limit": COMPOSIO_AUTH_CONFIG_PAGE_SIZE},
            {"limit": COMPOSIO_AUTH_CONFIG_PAGE_SIZE, "cursor": "page-2"},
        ]


class TestNotSetUpOnThisInstance:
    @pytest.fixture(autouse=True)
    def _selfhost_with_nothing_stored(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "ENV", "selfhost")
        monkeypatch.setattr(settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {})
        monkeypatch.setattr(
            auth_config_resolver,
            "instance_settings_repository",
            SimpleNamespace(find_by_key=AsyncMock(return_value=None)),
        )
        auth_config_resolver.invalidate_auth_config_cache()
        yield
        auth_config_resolver.invalidate_auth_config_cache()

    @pytest.mark.asyncio
    async def test_connect_refuses_without_minting_a_link(self):
        svc = _make_service()

        with pytest.raises(ValueError, match="Gmail is not set up on this instance"):
            await svc.connect_account("gmail", "user1", state_token="tok")
        svc.composio.connected_accounts.link.assert_not_called()

    @pytest.mark.asyncio
    async def test_status_is_false_without_asking_composio(self):
        svc = _make_service()

        assert await svc.check_connection_status(["gmail"], "user1") == {"gmail": False}
        svc.composio.connected_accounts.list.assert_not_called()

    @pytest.mark.asyncio
    async def test_disconnect_has_nothing_to_revoke(self):
        svc = _make_service()

        assert await svc.delete_all_connected_accounts("user1", "gmail") == 0
        svc.composio.connected_accounts.list.assert_not_called()


class TestGetConnectedAccountById:
    def test_success(self):
        svc = _make_service()
        account = MagicMock()
        svc.composio.connected_accounts.get = MagicMock(return_value=account)
        assert svc.get_connected_account_by_id("abc") == account

    def test_returns_none_on_error(self):
        svc = _make_service()
        svc.composio.connected_accounts.get = MagicMock(side_effect=RuntimeError("x"))
        assert svc.get_connected_account_by_id("abc") is None


class TestDeleteAllConnectedAccounts:
    @pytest.mark.asyncio
    async def test_unsupported_provider(self):
        svc = _make_service()
        with patch(
            "app.services.composio.composio_service.get_composio_integrations_by_provider",
            return_value={},
        ):
            with pytest.raises(ValueError, match="not supported"):
                await svc.delete_all_connected_accounts("user1", "bad")

    @pytest.mark.asyncio
    async def test_every_account_goes_whatever_its_status(self):
        """Expired and abandoned reconnect leftovers are revoked with the live ones."""
        svc = _make_service()
        accounts = []
        for account_id, status in (("acc1", "ACTIVE"), ("acc2", "EXPIRED"), ("acc3", "INITIATED")):
            account = MagicMock()
            account.id = account_id
            account.status = status
            accounts.append(account)
        svc.composio.connected_accounts.list = MagicMock(return_value=MagicMock(items=accounts))
        svc.composio.connected_accounts.delete = MagicMock(return_value=None)

        with patch.object(settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {"gmail": GMAIL_AC}):
            async with captured_wide_event() as event:
                deleted = await svc.delete_all_connected_accounts("user1", "gmail")

        assert deleted == 3
        assert event["composio_user_id"] == "user1"
        assert event["composio_provider"] == "gmail"
        svc.composio.connected_accounts.list.assert_called_once_with(
            user_ids=["user1"], auth_config_ids=[GMAIL_AC], limit=COMPOSIO_ACCOUNT_LIST_LIMIT
        )
        assert {
            c.kwargs["nanoid"] for c in svc.composio.connected_accounts.delete.call_args_list
        } == {
            "acc1",
            "acc2",
            "acc3",
        }

    @pytest.mark.asyncio
    async def test_a_failed_revoke_propagates(self):
        svc = _make_service()
        account = MagicMock()
        account.id = "acc1"
        svc.composio.connected_accounts.list = MagicMock(return_value=MagicMock(items=[account]))
        svc.composio.connected_accounts.delete = MagicMock(side_effect=RuntimeError("fail"))

        with patch.object(settings, "COMPOSIO_AUTH_CONFIG_OVERRIDES", {"gmail": GMAIL_AC}):
            with pytest.raises(RuntimeError, match="fail"):
                await svc.delete_all_connected_accounts("user1", "gmail")


class TestDeleteConnectedAccount:
    @pytest.mark.asyncio
    async def test_revokes_exactly_that_account(self):
        svc = _make_service()
        svc.composio.connected_accounts.delete = MagicMock(return_value=None)

        async with captured_wide_event() as event:
            await svc.delete_connected_account("ca_1")

        svc.composio.connected_accounts.delete.assert_called_once_with(nanoid="ca_1")
        assert event["composio_connected_account_id"] == "ca_1"

    @pytest.mark.asyncio
    async def test_an_account_composio_no_longer_has_counts_as_revoked(self):
        """Removed from Composio's side already, it must still be removable from GAIA."""
        svc = _make_service()
        request = httpx.Request(
            "DELETE", "https://backend.composio.dev/api/v3/connected_accounts/ca_1"
        )
        svc.composio.connected_accounts.delete = MagicMock(
            side_effect=composio_client.NotFoundError(
                "gone", response=httpx.Response(404, request=request), body=None
            )
        )

        await svc.delete_connected_account("ca_1")

    @pytest.mark.asyncio
    async def test_any_other_revoke_failure_propagates(self):
        svc = _make_service()
        svc.composio.connected_accounts.delete = MagicMock(side_effect=RuntimeError("down"))

        with pytest.raises(RuntimeError, match="down"):
            await svc.delete_connected_account("ca_1")


class TestHandleSubscribeTrigger:
    @pytest.mark.asyncio
    async def test_no_auto_active_triggers(self):
        svc = _make_service()
        trigger = MagicMock()
        trigger.auto_activate = False

        result = await svc.handle_subscribe_trigger("user1", "ca_1", [trigger])
        assert result == []

    @pytest.mark.asyncio
    async def test_subscribes_auto_active_triggers(self):
        svc = _make_service()
        trigger = MagicMock()
        trigger.auto_activate = True
        trigger.slug = "test-slug"
        trigger.config = {}

        svc.composio.triggers.create = MagicMock(return_value={"id": "t1"})
        inactive = MagicMock()
        inactive.auto_activate = False

        async with captured_wide_event() as event:
            result = await svc.handle_subscribe_trigger("user1", "ca_1", [trigger, inactive])
        assert result == [{"id": "t1"}]
        assert event["composio_user_id"] == "user1"
        assert event["composio_connected_account_id"] == "ca_1"
        assert event["composio_trigger_count"] == 2
        # The account is named, so Composio cannot attach it to whichever account it picks.
        svc.composio.triggers.create.assert_called_once_with(
            connected_account_id="ca_1", slug="test-slug", trigger_config={}
        )

    @pytest.mark.asyncio
    async def test_subscribe_error_swallowed(self):
        svc = _make_service()
        trigger = MagicMock()
        trigger.auto_activate = True
        trigger.slug = "fail-slug"
        trigger.config = {}

        svc.composio.triggers.create = MagicMock(side_effect=RuntimeError("fail"))

        # Should not raise (error is logged)
        result = await svc.handle_subscribe_trigger("user1", "ca_1", [trigger])
        # gather will raise and be caught by the except block
        assert result is None


class TestGmailConnectTriggers:
    @pytest.mark.asyncio
    async def test_connecting_gmail_arms_the_inbox_and_the_sent_mail_triggers(self):
        # Without the sent-mail instance a thread todo never sees the user's own
        # replies, which Gmail labels SENT, not INBOX.
        svc = _make_service()
        svc.composio.triggers.create = MagicMock(return_value={"id": "t"})
        gmail = get_integration_by_id(GMAIL_INTEGRATION_ID)
        assert gmail is not None

        await svc.handle_subscribe_trigger("user1", "ca_1", gmail.associated_triggers)

        created = sorted(
            (c.kwargs["slug"], c.kwargs["trigger_config"])
            for c in svc.composio.triggers.create.call_args_list
        )
        assert created == [
            ("GMAIL_EMAIL_SENT_TRIGGER", {"interval": 1}),
            ("GMAIL_NEW_GMAIL_MESSAGE", {"labelIds": "INBOX", "user_id": "me", "interval": 1}),
        ]


class TestGetComposioService:
    def test_returns_service(self):
        mock_svc = MagicMock()
        with patch("app.services.composio.composio_service.providers") as mock_providers:
            mock_providers.get.return_value = mock_svc
            from app.services.composio.composio_service import get_composio_service

            assert get_composio_service() == mock_svc
        # The same name @lazy_provider registered the service under.
        mock_providers.get.assert_called_once_with(COMPOSIO_SERVICE_PROVIDER)

    def test_no_key_raises_not_configured(self):
        from app.services.composio import composio_service as mod

        with (
            patch.object(mod, "providers") as mock_providers,
            patch.object(mod, "resolved_config", return_value=None),
        ):
            mock_providers.get.return_value = None

            with pytest.raises(ProviderNotConfiguredError) as refused:
                mod.get_composio_service()

        assert refused.value.message == (
            "COMPOSIO_KEY is not set in settings and no composio credential is stored"
        )

    def test_a_key_whose_service_failed_to_build_is_a_real_failure(self):
        from app.services.composio import composio_service as mod

        with (
            patch.object(mod, "providers") as mock_providers,
            patch.object(mod, "resolved_config", return_value=ProviderConfig(api_key="k")),
        ):
            mock_providers.get.return_value = None

            with pytest.raises(RuntimeError, match="not available"):
                mod.get_composio_service()


class TestInitComposioService:
    """The loader resolves store-first (runtime snapshot) with an env fallback.

    Sync loader on purpose — the Composio SDK is synchronous and its consumers
    call it from worker threads — so it reads the credential service's runtime
    snapshot instead of awaiting resolve().
    """

    _STORED: ClassVar[dict[str, str | None]] = ProviderConfig(
        api_key="stored-key",
    )

    def test_stored_credential_wins_over_env(self):
        from app.services.composio import composio_service as mod

        fake_sdk = MagicMock()
        with (
            patch.object(mod, "resolved_config", return_value=self._STORED),
            patch.object(mod, "settings") as mock_settings,
            patch.object(mod, "Composio", return_value=fake_sdk) as mock_composio_cls,
        ):
            mock_settings.COMPOSIO_KEY = "env-key"
            service = mod.init_composio_service().loader_func()
        assert mock_composio_cls.call_args.kwargs["api_key"] == "stored-key"
        assert service.composio is fake_sdk

    def test_env_fallback_when_nothing_is_stored(self):
        from app.config.settings import settings
        from app.services.composio import composio_service as mod

        fake_sdk = MagicMock()
        with (
            patch.object(settings, "COMPOSIO_KEY", "env-key"),
            patch.object(mod, "Composio", return_value=fake_sdk) as mock_composio_cls,
        ):
            service = mod.init_composio_service().loader_func()
        assert mock_composio_cls.call_args.kwargs["api_key"] == "env-key"
        assert service.composio is fake_sdk

    def test_unconfigured_fails_loud_instead_of_building_a_dead_service(self):
        from app.services.composio import composio_service as mod

        with (
            patch.object(mod, "resolved_config", return_value=None),
            patch.object(mod, "settings") as mock_settings,
        ):
            mock_settings.COMPOSIO_KEY = None
            with pytest.raises(ProviderNotConfiguredError, match="COMPOSIO_KEY"):
                mod.init_composio_service().loader_func()


# ---------------------------------------------------------------------------
# Gmail custom tools tests
# ---------------------------------------------------------------------------


class TestAuthHeaders:
    """The _auth_headers helper was removed in the Composio proxy migration.

    Gmail tools now route every request through proxy_request_sync, which
    Composio authenticates server-side. Bearer-token construction is no longer
    a Gmail-tools concern, so the helper and its tests no longer exist.
    See test_composio_gmail_tools.py for the replacement coverage.
    """

    def test_helper_no_longer_exists(self):
        from app.services.composio.custom_tools import gmail_tools

        assert not hasattr(gmail_tools, "_auth_headers")
        assert not hasattr(gmail_tools, "_http_client")


class TestGmailInputModels:
    def test_mark_as_read_input(self):
        from app.services.composio.custom_tools.gmail_tools import MarkAsReadInput

        model = MarkAsReadInput(message_ids=["a", "b"])
        assert model.message_ids == ["a", "b"]

    def test_star_email_input_defaults(self):
        from app.services.composio.custom_tools.gmail_tools import StarEmailInput

        model = StarEmailInput(message_ids=["a"])
        assert model.unstar is False

    def test_get_unread_count_input_defaults(self):
        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        model = GetUnreadCountInput()
        assert model.label_ids is None
        assert model.query is None
        assert model.include_spam_trash is False

    def test_get_contact_list_input(self):
        from app.services.composio.custom_tools.gmail_tools import GetContactListInput

        model = GetContactListInput(query="john")
        assert model.max_results == 30


class TestRegisterGmailCustomTools:
    def test_returns_tool_names(self):
        mock_composio = MagicMock()
        mock_composio.tools.custom_tool.return_value = lambda f: f

        from app.services.composio.custom_tools.gmail_tools import (
            register_gmail_custom_tools,
        )

        result = register_gmail_custom_tools(mock_composio)
        assert isinstance(result, list)
        assert "GMAIL_MARK_AS_READ" in result
        assert "GMAIL_MARK_AS_UNREAD" in result
        assert "GMAIL_ARCHIVE_EMAIL" in result
        assert "GMAIL_STAR_EMAIL" in result
        assert "GMAIL_GET_UNREAD_COUNT" in result
        assert "GMAIL_GET_CONTACT_LIST" in result
        assert "GMAIL_CUSTOM_GATHER_CONTEXT" in result
        assert "GMAIL_FETCH_MESSAGES" in result
        assert "GMAIL_FETCH_THREAD" in result
        assert len(result) == 9


# Behavior tests for MARK_AS_READ/STAR_EMAIL/GET_UNREAD_COUNT/GET_CONTACT_LIST
# live in test_composio_gmail_tools.py. Removed here: they duplicated
# production logic inline, giving false confidence.
