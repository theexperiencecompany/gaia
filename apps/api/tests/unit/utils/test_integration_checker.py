"""Unit tests for the integration connection checker utility."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.integration_checker import (
    TOOL_INTEGRATION_MAPPING,
    check_and_prompt_integration,
    check_user_has_integration,
    get_required_integration_for_tool_category,
    stream_integration_connection_prompt,
)


# ---------------------------------------------------------------------------
# get_required_integration_for_tool_category
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetRequiredIntegrationForToolCategory:
    """Tests for mapping tool categories to integration IDs."""

    @pytest.mark.parametrize(
        "category,expected",
        [
            ("gmail", "gmail"),
            ("calendar", "googlecalendar"),
            ("googledocs", "googledocs"),
            ("google_drive", "google_drive"),
        ],
    )
    def test_known_categories(self, category: str, expected: str) -> None:
        assert get_required_integration_for_tool_category(category) == expected

    def test_unknown_category_returns_none(self) -> None:
        assert get_required_integration_for_tool_category("unknown_tool") is None

    def test_empty_string_returns_none(self) -> None:
        assert get_required_integration_for_tool_category("") is None

    def test_mapping_matches_module_constant(self) -> None:
        """Ensure the function uses the TOOL_INTEGRATION_MAPPING dict."""
        for category, integration_id in TOOL_INTEGRATION_MAPPING.items():
            assert (
                get_required_integration_for_tool_category(category) == integration_id
            )


# ---------------------------------------------------------------------------
# check_user_has_integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckUserHasIntegration:
    """Tests for checking if a user has required integration permissions."""

    @patch("app.utils.integration_checker.token_repository")
    @patch("app.utils.integration_checker.get_integration_scopes")
    async def test_returns_true_when_all_scopes_present(
        self,
        mock_get_scopes: MagicMock,
        mock_token_repo: MagicMock,
    ) -> None:
        mock_get_scopes.return_value = ["scope_a", "scope_b"]
        mock_token = MagicMock()
        mock_token.get.return_value = "scope_a scope_b scope_c"
        mock_token_repo.get_token_by_auth_token = AsyncMock(return_value=mock_token)

        result = await check_user_has_integration("valid_token", "gmail")
        assert result is True

    @patch("app.utils.integration_checker.token_repository")
    @patch("app.utils.integration_checker.get_integration_scopes")
    async def test_returns_false_when_scope_missing(
        self,
        mock_get_scopes: MagicMock,
        mock_token_repo: MagicMock,
    ) -> None:
        mock_get_scopes.return_value = ["scope_a", "scope_b"]
        mock_token = MagicMock()
        mock_token.get.return_value = "scope_a"  # missing scope_b
        mock_token_repo.get_token_by_auth_token = AsyncMock(return_value=mock_token)

        result = await check_user_has_integration("valid_token", "gmail")
        assert result is False

    @patch("app.utils.integration_checker.get_integration_scopes")
    async def test_returns_false_when_access_token_empty(
        self, mock_get_scopes: MagicMock
    ) -> None:
        result = await check_user_has_integration("", "gmail")
        assert result is False
        mock_get_scopes.assert_not_called()

    @patch("app.utils.integration_checker.token_repository")
    @patch("app.utils.integration_checker.get_integration_scopes")
    async def test_returns_false_when_no_scopes_defined(
        self,
        mock_get_scopes: MagicMock,
        mock_token_repo: MagicMock,
    ) -> None:
        mock_get_scopes.return_value = []

        result = await check_user_has_integration("valid_token", "unknown_integration")
        assert result is False
        mock_token_repo.get_token_by_auth_token.assert_not_called()

    @patch("app.utils.integration_checker.token_repository")
    @patch("app.utils.integration_checker.get_integration_scopes")
    async def test_returns_false_when_no_token_found(
        self,
        mock_get_scopes: MagicMock,
        mock_token_repo: MagicMock,
    ) -> None:
        mock_get_scopes.return_value = ["scope_a"]
        mock_token_repo.get_token_by_auth_token = AsyncMock(return_value=None)

        result = await check_user_has_integration("valid_token", "gmail")
        assert result is False

    @patch("app.utils.integration_checker.token_repository")
    @patch("app.utils.integration_checker.get_integration_scopes")
    async def test_returns_false_on_exception(
        self,
        mock_get_scopes: MagicMock,
        mock_token_repo: MagicMock,
    ) -> None:
        mock_get_scopes.return_value = ["scope_a"]
        mock_token_repo.get_token_by_auth_token = AsyncMock(
            side_effect=Exception("DB error")
        )

        result = await check_user_has_integration("valid_token", "gmail")
        assert result is False

    @patch("app.utils.integration_checker.token_repository")
    @patch("app.utils.integration_checker.get_integration_scopes")
    async def test_renews_expired_token(
        self,
        mock_get_scopes: MagicMock,
        mock_token_repo: MagicMock,
    ) -> None:
        mock_get_scopes.return_value = ["scope_a"]
        mock_token = MagicMock()
        mock_token.get.return_value = "scope_a"
        mock_token_repo.get_token_by_auth_token = AsyncMock(return_value=mock_token)

        await check_user_has_integration("valid_token", "gmail")

        mock_token_repo.get_token_by_auth_token.assert_awaited_once_with(
            "valid_token", renew_if_expired=True
        )

    @patch("app.utils.integration_checker.token_repository")
    @patch("app.utils.integration_checker.get_integration_scopes")
    async def test_returns_true_with_exact_scopes(
        self,
        mock_get_scopes: MagicMock,
        mock_token_repo: MagicMock,
    ) -> None:
        mock_get_scopes.return_value = ["scope_a"]
        mock_token = MagicMock()
        mock_token.get.return_value = "scope_a"
        mock_token_repo.get_token_by_auth_token = AsyncMock(return_value=mock_token)

        result = await check_user_has_integration("valid_token", "gmail")
        assert result is True

    @patch("app.utils.integration_checker.token_repository")
    @patch("app.utils.integration_checker.get_integration_scopes")
    async def test_empty_scope_string_on_token(
        self,
        mock_get_scopes: MagicMock,
        mock_token_repo: MagicMock,
    ) -> None:
        """Token has no scopes at all."""
        mock_get_scopes.return_value = ["scope_a"]
        mock_token = MagicMock()
        mock_token.get.return_value = ""
        mock_token_repo.get_token_by_auth_token = AsyncMock(return_value=mock_token)

        result = await check_user_has_integration("valid_token", "gmail")
        assert result is False


# ---------------------------------------------------------------------------
# stream_integration_connection_prompt
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStreamIntegrationConnectionPrompt:
    """Tests for streaming integration connection prompts to the frontend."""

    @patch("app.utils.integration_checker.get_stream_writer")
    @patch("app.utils.integration_checker.get_integration_by_id")
    async def test_streams_connection_data(
        self,
        mock_get_integration: MagicMock,
        mock_get_writer: MagicMock,
    ) -> None:
        mock_integration = MagicMock()
        mock_integration.name = "Gmail"
        mock_get_integration.return_value = mock_integration
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        await stream_integration_connection_prompt("gmail", tool_name="send_email")

        mock_writer.assert_called_once()
        call_data = mock_writer.call_args[0][0]
        assert "integration_connection_required" in call_data
        payload = call_data["integration_connection_required"]
        assert payload["integration_id"] == "gmail"
        assert "send email" in payload["message"]  # underscores replaced

    @patch("app.utils.integration_checker.get_stream_writer")
    @patch("app.utils.integration_checker.get_integration_by_id")
    async def test_uses_custom_message_when_provided(
        self,
        mock_get_integration: MagicMock,
        mock_get_writer: MagicMock,
    ) -> None:
        mock_integration = MagicMock()
        mock_integration.name = "Gmail"
        mock_get_integration.return_value = mock_integration
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        await stream_integration_connection_prompt(
            "gmail", message="Custom message here"
        )

        call_data = mock_writer.call_args[0][0]
        assert (
            call_data["integration_connection_required"]["message"]
            == "Custom message here"
        )

    @patch("app.utils.integration_checker.get_stream_writer")
    @patch("app.utils.integration_checker.get_integration_by_id")
    async def test_does_nothing_when_integration_not_found(
        self,
        mock_get_integration: MagicMock,
        mock_get_writer: MagicMock,
    ) -> None:
        mock_get_integration.return_value = None
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        await stream_integration_connection_prompt("nonexistent")

        mock_writer.assert_not_called()

    @patch("app.utils.integration_checker.get_stream_writer")
    @patch("app.utils.integration_checker.get_integration_by_id")
    async def test_handles_exception_gracefully(
        self,
        mock_get_integration: MagicMock,
        mock_get_writer: MagicMock,
    ) -> None:
        mock_get_writer.side_effect = Exception("No stream context")

        # Should not raise
        await stream_integration_connection_prompt("gmail")

    @patch("app.utils.integration_checker.get_stream_writer")
    @patch("app.utils.integration_checker.get_integration_by_id")
    async def test_default_message_with_none_tool_name(
        self,
        mock_get_integration: MagicMock,
        mock_get_writer: MagicMock,
    ) -> None:
        mock_integration = MagicMock()
        mock_integration.name = "Google Calendar"
        mock_get_integration.return_value = mock_integration
        mock_writer = MagicMock()
        mock_get_writer.return_value = mock_writer

        await stream_integration_connection_prompt("googlecalendar", tool_name=None)

        call_data = mock_writer.call_args[0][0]
        msg = call_data["integration_connection_required"]["message"]
        # str(None) produces "None"; the `or 'this feature'` branch is not taken
        # because "None" is truthy after replace('_', ' ').
        assert "None" in msg
        assert "Google Calendar" in msg

    @patch("app.utils.integration_checker.get_stream_writer")
    @patch("app.utils.integration_checker.get_integration_by_id")
    async def test_writer_exception_does_not_propagate(
        self,
        mock_get_integration: MagicMock,
        mock_get_writer: MagicMock,
    ) -> None:
        mock_integration = MagicMock()
        mock_integration.name = "Gmail"
        mock_get_integration.return_value = mock_integration
        mock_writer = MagicMock()
        mock_writer.side_effect = RuntimeError("stream closed")
        mock_get_writer.return_value = mock_writer

        # Should not raise
        await stream_integration_connection_prompt("gmail")


# ---------------------------------------------------------------------------
# check_and_prompt_integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckAndPromptIntegration:
    """Tests for the combined check-and-prompt flow."""

    @patch("app.utils.integration_checker.stream_integration_connection_prompt")
    @patch("app.utils.integration_checker.check_user_has_integration")
    @patch("app.utils.integration_checker.get_required_integration_for_tool_category")
    async def test_returns_true_when_no_integration_required(
        self,
        mock_get_req: MagicMock,
        mock_check: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        mock_get_req.return_value = None

        result = await check_and_prompt_integration("token", "random_category")
        assert result is True
        mock_check.assert_not_called()
        mock_stream.assert_not_called()

    @patch("app.utils.integration_checker.stream_integration_connection_prompt")
    @patch("app.utils.integration_checker.check_user_has_integration")
    @patch("app.utils.integration_checker.get_required_integration_for_tool_category")
    async def test_returns_true_when_user_has_integration(
        self,
        mock_get_req: MagicMock,
        mock_check: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        mock_get_req.return_value = "gmail"
        mock_check.return_value = True

        result = await check_and_prompt_integration("token", "gmail")
        assert result is True
        mock_stream.assert_not_called()

    @patch(
        "app.utils.integration_checker.stream_integration_connection_prompt",
        new_callable=AsyncMock,
    )
    @patch(
        "app.utils.integration_checker.check_user_has_integration",
        new_callable=AsyncMock,
    )
    @patch("app.utils.integration_checker.get_required_integration_for_tool_category")
    async def test_returns_false_and_prompts_when_missing(
        self,
        mock_get_req: MagicMock,
        mock_check: AsyncMock,
        mock_stream: AsyncMock,
    ) -> None:
        mock_get_req.return_value = "gmail"
        mock_check.return_value = False

        result = await check_and_prompt_integration(
            "token", "gmail", tool_name="send_email"
        )
        assert result is False
        mock_stream.assert_awaited_once_with(
            integration_id="gmail",
            tool_name="send_email",
            tool_category="gmail",
        )

    @patch(
        "app.utils.integration_checker.stream_integration_connection_prompt",
        new_callable=AsyncMock,
    )
    @patch(
        "app.utils.integration_checker.check_user_has_integration",
        new_callable=AsyncMock,
    )
    @patch("app.utils.integration_checker.get_required_integration_for_tool_category")
    async def test_passes_correct_integration_id_to_check(
        self,
        mock_get_req: MagicMock,
        mock_check: AsyncMock,
        mock_stream: AsyncMock,
    ) -> None:
        mock_get_req.return_value = "googlecalendar"
        mock_check.return_value = True

        await check_and_prompt_integration("my_token", "calendar")

        mock_check.assert_awaited_once_with("my_token", "googlecalendar")

    @patch(
        "app.utils.integration_checker.stream_integration_connection_prompt",
        new_callable=AsyncMock,
    )
    @patch(
        "app.utils.integration_checker.check_user_has_integration",
        new_callable=AsyncMock,
    )
    @patch("app.utils.integration_checker.get_required_integration_for_tool_category")
    async def test_prompt_uses_tool_name_none_by_default(
        self,
        mock_get_req: MagicMock,
        mock_check: AsyncMock,
        mock_stream: AsyncMock,
    ) -> None:
        mock_get_req.return_value = "gmail"
        mock_check.return_value = False

        await check_and_prompt_integration("token", "gmail")

        mock_stream.assert_awaited_once_with(
            integration_id="gmail",
            tool_name=None,
            tool_category="gmail",
        )

    @pytest.mark.parametrize(
        "category",
        ["gmail", "calendar", "googledocs", "google_drive"],
    )
    @patch(
        "app.utils.integration_checker.stream_integration_connection_prompt",
        new_callable=AsyncMock,
    )
    @patch(
        "app.utils.integration_checker.check_user_has_integration",
        new_callable=AsyncMock,
    )
    async def test_all_known_categories_trigger_check(
        self,
        mock_check: AsyncMock,
        mock_stream: AsyncMock,
        category: str,
    ) -> None:
        mock_check.return_value = True

        result = await check_and_prompt_integration("token", category)
        assert result is True
        mock_check.assert_awaited_once()

    @patch(
        "app.utils.integration_checker.stream_integration_connection_prompt",
        new_callable=AsyncMock,
    )
    @patch(
        "app.utils.integration_checker.check_user_has_integration",
        new_callable=AsyncMock,
    )
    async def test_unknown_category_returns_true_without_check(
        self,
        mock_check: AsyncMock,
        mock_stream: AsyncMock,
    ) -> None:
        result = await check_and_prompt_integration("token", "totally_unknown")
        assert result is True
        mock_check.assert_not_awaited()
        mock_stream.assert_not_awaited()
