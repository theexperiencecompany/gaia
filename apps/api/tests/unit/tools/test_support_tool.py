"""Unit tests for app.agents.tools.support_tool."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = "507f1f77bcf86cd799439011"
MODULE = "app.agents.tools.support_tool"


def _cfg(user_id: str = FAKE_USER_ID) -> Dict[str, Any]:
    return {"metadata": {"user_id": user_id}}


def _cfg_no_user() -> Dict[str, Any]:
    return {"metadata": {}}


def _writer() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests: create_support_ticket
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSupportTicket:
    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_service")
    async def test_happy_path_support(
        self, mock_user_svc: MagicMock, mock_gsw: MagicMock
    ) -> None:
        w = _writer()
        mock_gsw.return_value = w
        mock_user_svc.get_user_by_id = AsyncMock(
            return_value={"email": "test@example.com", "name": "Test User"}
        )

        from app.agents.tools.support_tool import create_support_ticket

        result = await create_support_ticket.coroutine(
            config=_cfg(),
            type="support",
            title="App crashes on login",
            description="When I try to log in with Google, the app crashes immediately.",
        )
        assert "support ticket" in result
        assert "review" in result.lower()
        # Verify writer was called with progress and data
        assert w.call_count == 2
        progress_call = w.call_args_list[0][0][0]
        assert "progress" in progress_call
        data_call = w.call_args_list[1][0][0]
        assert "support_ticket_data" in data_call
        ticket = data_call["support_ticket_data"][0]
        assert ticket["type"] == "support"
        assert ticket["title"] == "App crashes on login"
        assert ticket["user_email"] == "test@example.com"

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_service")
    async def test_happy_path_feature(
        self, mock_user_svc: MagicMock, mock_gsw: MagicMock
    ) -> None:
        mock_gsw.return_value = _writer()
        mock_user_svc.get_user_by_id = AsyncMock(
            return_value={"email": "test@example.com", "name": "Test User"}
        )

        from app.agents.tools.support_tool import create_support_ticket

        result = await create_support_ticket.coroutine(
            config=_cfg(),
            type="feature",
            title="Add dark mode",
            description="I would love to have a dark mode option in the settings.",
        )
        assert "feature request" in result

    async def test_no_user_id(self) -> None:
        from app.agents.tools.support_tool import create_support_ticket

        result = await create_support_ticket.coroutine(
            config=_cfg_no_user(),
            type="support",
            title="Test",
            description="A test description for the ticket.",
        )
        assert "authentication required" in result.lower()

    @patch(f"{MODULE}.user_service")
    async def test_user_not_found(self, mock_user_svc: MagicMock) -> None:
        mock_user_svc.get_user_by_id = AsyncMock(return_value=None)

        from app.agents.tools.support_tool import create_support_ticket

        result = await create_support_ticket.coroutine(
            config=_cfg(),
            type="support",
            title="Test",
            description="A test description for the ticket.",
        )
        assert "not found" in result.lower()

    @patch(f"{MODULE}.user_service")
    async def test_user_no_email(self, mock_user_svc: MagicMock) -> None:
        mock_user_svc.get_user_by_id = AsyncMock(return_value={"name": "Test User"})

        from app.agents.tools.support_tool import create_support_ticket

        result = await create_support_ticket.coroutine(
            config=_cfg(),
            type="support",
            title="Test",
            description="A test description for the ticket.",
        )
        assert "email is required" in result.lower()

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_service")
    async def test_strips_whitespace(
        self, mock_user_svc: MagicMock, mock_gsw: MagicMock
    ) -> None:
        w = _writer()
        mock_gsw.return_value = w
        mock_user_svc.get_user_by_id = AsyncMock(
            return_value={"email": "test@example.com", "name": "Test User"}
        )

        from app.agents.tools.support_tool import create_support_ticket

        await create_support_ticket.coroutine(
            config=_cfg(),
            type="support",
            title="  Padded title  ",
            description="  Padded description  ",
        )
        data_call = w.call_args_list[1][0][0]
        ticket = data_call["support_ticket_data"][0]
        assert ticket["title"] == "Padded title"
        assert ticket["description"] == "Padded description"

    @patch(f"{MODULE}.user_service")
    async def test_service_error(self, mock_user_svc: MagicMock) -> None:
        mock_user_svc.get_user_by_id = AsyncMock(side_effect=RuntimeError("DB down"))

        from app.agents.tools.support_tool import create_support_ticket

        result = await create_support_ticket.coroutine(
            config=_cfg(),
            type="support",
            title="Test",
            description="A test description for the ticket.",
        )
        assert "error" in result.lower()
        assert "DB down" in result

    @patch(f"{MODULE}.get_stream_writer")
    @patch(f"{MODULE}.user_service")
    async def test_user_name_defaults(
        self, mock_user_svc: MagicMock, mock_gsw: MagicMock
    ) -> None:
        w = _writer()
        mock_gsw.return_value = w
        mock_user_svc.get_user_by_id = AsyncMock(
            return_value={"email": "test@example.com"}
        )

        from app.agents.tools.support_tool import create_support_ticket

        await create_support_ticket.coroutine(
            config=_cfg(),
            type="support",
            title="Test",
            description="A test description for the ticket.",
        )
        data_call = w.call_args_list[1][0][0]
        ticket = data_call["support_ticket_data"][0]
        assert ticket["user_name"] == "User"  # default
