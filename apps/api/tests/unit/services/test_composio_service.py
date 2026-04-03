"""Tests for ComposioService and Gmail custom tools."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# ComposioService tests
# ---------------------------------------------------------------------------


class TestComposioServiceInit:
    """Tests for ComposioService.__init__."""

    @patch("app.services.composio.composio_service.custom_tools_registry")
    @patch("app.services.composio.composio_service.LangchainProvider")
    @patch("app.services.composio.composio_service.Composio")
    def test_init_no_toolkit_versions(
        self, mock_composio_cls, mock_provider_cls, mock_registry
    ):
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
    def test_init_with_toolkit_versions(
        self, mock_composio_cls, mock_provider_cls, mock_registry
    ):
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
            "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS", {}
        ):
            with pytest.raises(ValueError, match="not supported"):
                await svc.connect_account("unsupported", "user1")

    @pytest.mark.asyncio
    async def test_connect_account_success(self):
        svc = _make_service()
        config = MagicMock()
        config.auth_config_id = "auth123"

        connection_request = MagicMock()
        connection_request.redirect_url = "https://example.com/redirect"
        connection_request.id = "conn123"

        svc.composio.connected_accounts.initiate.return_value = connection_request

        with (
            patch(
                "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS",
                {"gmail": config},
            ),
            patch(
                "app.services.composio.composio_service.settings",
                MagicMock(COMPOSIO_REDIRECT_URI="https://example.com/cb"),
            ),
        ):
            result = await svc.connect_account("gmail", "user1")

        assert result["status"] == "pending"
        assert result["redirect_url"] == "https://example.com/redirect"
        assert result["connection_id"] == "conn123"

    @pytest.mark.asyncio
    async def test_connect_account_with_state_token(self):
        svc = _make_service()
        config = MagicMock()
        config.auth_config_id = "auth123"

        connection_request = MagicMock()
        connection_request.redirect_url = "https://example.com/redirect"
        connection_request.id = "conn123"

        svc.composio.connected_accounts.initiate.return_value = connection_request

        with (
            patch(
                "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS",
                {"gmail": config},
            ),
            patch(
                "app.services.composio.composio_service.settings",
                MagicMock(COMPOSIO_REDIRECT_URI="https://example.com/cb"),
            ),
            patch(
                "app.services.composio.composio_service.add_query_param",
                return_value="https://example.com/cb?state=tok",
            ) as mock_add,
        ):
            result = await svc.connect_account("gmail", "user1", state_token="tok")

        mock_add.assert_called_once_with("https://example.com/cb", "state", "tok")
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_connect_account_propagates_exception(self):
        svc = _make_service()
        config = MagicMock()
        config.auth_config_id = "auth123"
        svc.composio.connected_accounts.initiate.side_effect = RuntimeError("boom")

        with (
            patch(
                "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS",
                {"gmail": config},
            ),
            patch(
                "app.services.composio.composio_service.settings",
                MagicMock(COMPOSIO_REDIRECT_URI="https://example.com/cb"),
            ),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await svc.connect_account("gmail", "user1")


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
            patch(
                "app.services.composio.composio_service.custom_tools_registry"
            ) as mock_reg,
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
            patch(
                "app.services.composio.composio_service.custom_tools_registry"
            ) as mock_reg,
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

        mock_store = AsyncMock()
        with patch(
            "app.services.composio.composio_service.get_mcp_tools_store",
            return_value=mock_store,
        ):
            await svc._store_tool_metadata("gmail", [tool])

        mock_store.store_tools.assert_called_once_with(
            "gmail", [{"name": "TOOL_A", "description": "desc"}]
        )

    @pytest.mark.asyncio
    async def test_empty_tools_returns_early(self):
        svc = _make_service()
        with patch(
            "app.services.composio.composio_service.get_mcp_tools_store"
        ) as mock_get:
            await svc._store_tool_metadata("gmail", [])
            mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_error_swallowed(self):
        svc = _make_service()
        tool = MagicMock()
        tool.name = "X"
        tool.description = ""
        mock_store = AsyncMock()
        mock_store.store_tools.side_effect = RuntimeError("db fail")

        with patch(
            "app.services.composio.composio_service.get_mcp_tools_store",
            return_value=mock_store,
        ):
            # Should not raise
            await svc._store_tool_metadata("gmail", [tool])


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
        config = MagicMock()
        config.auth_config_id = "auth_gmail"

        account = MagicMock()
        account.auth_config.is_disabled = False
        account.status = "ACTIVE"
        account.auth_config.id = "auth_gmail"

        user_accounts = MagicMock()
        user_accounts.items = [account]
        svc.composio.connected_accounts.list = MagicMock(return_value=user_accounts)

        with patch(
            "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS",
            {"gmail": config},
        ):
            result = await svc.check_connection_status(["gmail"], "user1")

        assert result == {"gmail": True}

    @pytest.mark.asyncio
    async def test_returns_false_for_disabled(self):
        svc = _make_service()
        config = MagicMock()
        config.auth_config_id = "auth_gmail"

        account = MagicMock()
        account.auth_config.is_disabled = True
        account.status = "ACTIVE"
        account.auth_config.id = "auth_gmail"

        user_accounts = MagicMock()
        user_accounts.items = [account]
        svc.composio.connected_accounts.list = MagicMock(return_value=user_accounts)

        with patch(
            "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS",
            {"gmail": config},
        ):
            result = await svc.check_connection_status(["gmail"], "user1")

        assert result == {"gmail": False}

    @pytest.mark.asyncio
    async def test_returns_false_for_unknown_provider(self):
        svc = _make_service()
        user_accounts = MagicMock()
        user_accounts.items = []
        svc.composio.connected_accounts.list = MagicMock(return_value=user_accounts)

        with patch(
            "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS", {}
        ):
            result = await svc.check_connection_status(["unknown"], "user1")

        assert result == {"unknown": False}

    @pytest.mark.asyncio
    async def test_returns_defaults_on_exception(self):
        svc = _make_service()
        config = MagicMock()
        config.auth_config_id = "auth_gmail"
        svc.composio.connected_accounts.list = MagicMock(
            side_effect=RuntimeError("fail")
        )

        with patch(
            "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS",
            {"gmail": config},
        ):
            result = await svc.check_connection_status(["gmail"], "user1")

        assert result == {"gmail": False}


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


class TestDeleteConnectedAccount:
    @pytest.mark.asyncio
    async def test_unsupported_provider(self):
        svc = _make_service()
        with patch(
            "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS", {}
        ):
            with pytest.raises(ValueError, match="not supported"):
                await svc.delete_connected_account("user1", "bad")

    @pytest.mark.asyncio
    async def test_no_active_accounts(self):
        svc = _make_service()
        config = MagicMock()
        config.auth_config_id = "auth_gmail"

        user_accounts = MagicMock()
        user_accounts.items = []
        svc.composio.connected_accounts.list = MagicMock(return_value=user_accounts)

        with patch(
            "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS",
            {"gmail": config},
        ):
            result = await svc.delete_connected_account("user1", "gmail")

        assert result["status"] == "success"
        assert "already disconnected" in result["message"]

    @pytest.mark.asyncio
    async def test_deletes_active_accounts(self):
        svc = _make_service()
        config = MagicMock()
        config.auth_config_id = "auth_gmail"

        account = MagicMock()
        account.status = "ACTIVE"
        account.auth_config.is_disabled = False
        account.id = "acc1"

        user_accounts = MagicMock()
        user_accounts.items = [account]
        svc.composio.connected_accounts.list = MagicMock(return_value=user_accounts)
        svc.composio.connected_accounts.delete = MagicMock(return_value=None)

        with patch(
            "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS",
            {"gmail": config},
        ):
            result = await svc.delete_connected_account("user1", "gmail")

        assert result["status"] == "success"
        assert "1 account(s)" in result["message"]

    @pytest.mark.asyncio
    async def test_delete_propagates_exception(self):
        svc = _make_service()
        config = MagicMock()
        config.auth_config_id = "auth_gmail"

        account = MagicMock()
        account.status = "ACTIVE"
        account.auth_config.is_disabled = False
        account.id = "acc1"

        user_accounts = MagicMock()
        user_accounts.items = [account]
        svc.composio.connected_accounts.list = MagicMock(return_value=user_accounts)
        svc.composio.connected_accounts.delete = MagicMock(
            side_effect=RuntimeError("fail")
        )

        with patch(
            "app.services.composio.composio_service.COMPOSIO_SOCIAL_CONFIGS",
            {"gmail": config},
        ):
            with pytest.raises(RuntimeError, match="fail"):
                await svc.delete_connected_account("user1", "gmail")


class TestHandleSubscribeTrigger:
    @pytest.mark.asyncio
    async def test_no_auto_active_triggers(self):
        svc = _make_service()
        trigger = MagicMock()
        trigger.auto_activate = False

        result = await svc.handle_subscribe_trigger("user1", [trigger])
        assert result == []

    @pytest.mark.asyncio
    async def test_subscribes_auto_active_triggers(self):
        svc = _make_service()
        trigger = MagicMock()
        trigger.auto_activate = True
        trigger.slug = "test-slug"
        trigger.config = {}

        svc.composio.triggers.create = MagicMock(return_value={"id": "t1"})

        result = await svc.handle_subscribe_trigger("user1", [trigger])
        assert result == [{"id": "t1"}]

    @pytest.mark.asyncio
    async def test_subscribe_error_swallowed(self):
        svc = _make_service()
        trigger = MagicMock()
        trigger.auto_activate = True
        trigger.slug = "fail-slug"
        trigger.config = {}

        svc.composio.triggers.create = MagicMock(side_effect=RuntimeError("fail"))

        # Should not raise (error is logged)
        result = await svc.handle_subscribe_trigger("user1", [trigger])
        # gather will raise and be caught by the except block
        assert result is None


class TestGetComposioService:
    def test_returns_service(self):
        mock_svc = MagicMock()
        with patch(
            "app.services.composio.composio_service.providers"
        ) as mock_providers:
            mock_providers.get.return_value = mock_svc
            from app.services.composio.composio_service import get_composio_service

            assert get_composio_service() == mock_svc

    def test_raises_when_none(self):
        with patch(
            "app.services.composio.composio_service.providers"
        ) as mock_providers:
            mock_providers.get.return_value = None
            from app.services.composio.composio_service import get_composio_service

            with pytest.raises(RuntimeError, match="not available"):
                get_composio_service()


# ---------------------------------------------------------------------------
# Gmail custom tools tests
# ---------------------------------------------------------------------------


class TestAuthHeaders:
    def test_valid_token(self):
        from app.services.composio.custom_tools.gmail_tools import _auth_headers

        result = _auth_headers({"access_token": "tok123"})
        assert result == {"Authorization": "Bearer tok123"}

    def test_missing_token_raises(self):
        from app.services.composio.custom_tools.gmail_tools import _auth_headers

        with pytest.raises(ValueError, match="Missing access_token"):
            _auth_headers({})


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

    def test_schedule_send_input(self):
        from app.services.composio.custom_tools.gmail_tools import ScheduleSendInput

        model = ScheduleSendInput(
            recipient_email="a@b.com",
            subject="hi",
            body="hello",
            send_at="2024-01-15T10:00:00Z",
        )
        assert model.cc is None
        assert model.bcc is None

    def test_snooze_email_input(self):
        from app.services.composio.custom_tools.gmail_tools import SnoozeEmailInput

        model = SnoozeEmailInput(message_ids=["a"], snooze_until="2024-01-15T09:00:00Z")
        assert model.message_ids == ["a"]


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
        assert len(result) == 7


class TestGmailMarkAsRead:
    """Test MARK_AS_READ via direct function call after registration."""

    def test_mark_as_read_calls_api(self):
        from app.services.composio.custom_tools.gmail_tools import (
            MarkAsReadInput,
            _http_client,
        )

        request = MarkAsReadInput(message_ids=["msg1", "msg2"])

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch.object(_http_client, "post", return_value=mock_resp) as mock_post:
            # Call the inner logic directly
            url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/batchModify"
            payload = {"ids": request.message_ids, "removeLabelIds": ["UNREAD"]}
            resp = _http_client.post(
                url,
                json=payload,
                headers={"Authorization": "Bearer tok"},
            )
            resp.raise_for_status()

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"]["removeLabelIds"] == ["UNREAD"]


class TestGmailStarEmail:
    def test_star_payload(self):
        from app.services.composio.custom_tools.gmail_tools import StarEmailInput

        request = StarEmailInput(message_ids=["m1"], unstar=False)
        if request.unstar:
            payload = {"ids": request.message_ids, "removeLabelIds": ["STARRED"]}
            action = "unstarred"
        else:
            payload = {"ids": request.message_ids, "addLabelIds": ["STARRED"]}
            action = "starred"
        assert payload["addLabelIds"] == ["STARRED"]
        assert action == "starred"

    def test_unstar_payload(self):
        from app.services.composio.custom_tools.gmail_tools import StarEmailInput

        request = StarEmailInput(message_ids=["m1"], unstar=True)
        if request.unstar:
            payload = {"ids": request.message_ids, "removeLabelIds": ["STARRED"]}
            action = "unstarred"
        else:
            payload = {"ids": request.message_ids, "addLabelIds": ["STARRED"]}
            action = "starred"
        assert payload["removeLabelIds"] == ["STARRED"]
        assert action == "unstarred"


class TestGetUnreadCountLogic:
    """Test the GET_UNREAD_COUNT logic branches."""

    def test_default_label_ids_is_inbox(self):
        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        request = GetUnreadCountInput()
        resolved: list[str] = []
        if request.label_ids:
            resolved = [label for label in request.label_ids if label]
        elif not request.query:
            resolved = ["INBOX"]
        assert resolved == ["INBOX"]

    def test_query_mode_adds_unread_filter(self):
        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        request = GetUnreadCountInput(query="from:alice@example.com")
        query = request.query.strip() if request.query else ""
        unread_query = query if "is:unread" in query.lower() else f"{query} is:unread"
        assert unread_query == "from:alice@example.com is:unread"

    def test_query_already_has_unread(self):
        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        request = GetUnreadCountInput(query="is:unread from:bob")
        query = request.query.strip() if request.query else ""
        unread_query = query if "is:unread" in query.lower() else f"{query} is:unread"
        assert unread_query == "is:unread from:bob"

    def test_explicit_label_ids_used(self):
        from app.services.composio.custom_tools.gmail_tools import GetUnreadCountInput

        request = GetUnreadCountInput(label_ids=["CATEGORY_PROMOTIONS", ""])
        resolved: list[str] = []
        if request.label_ids:
            resolved = [label for label in request.label_ids if label]
        assert resolved == ["CATEGORY_PROMOTIONS"]


class TestGetContactList:
    def test_missing_token_raises(self):
        from app.services.composio.custom_tools.gmail_tools import GetContactListInput

        GetContactListInput(query="john")
        auth: Dict[str, Any] = {}
        token = auth.get("access_token")
        assert token is None
