"""Tests for app.services.composio.account_scope."""

from unittest.mock import AsyncMock, patch

from app.services.composio.account_scope import scoped_connected_account_id
from app.utils.concurrency import run_on_captured_loop

MODULE = "app.services.composio.account_scope"


class TestScopedConnectedAccountId:
    def test_with_no_scope_the_primary_lookup_is_bounded_to_ten_seconds(self) -> None:
        primary = AsyncMock(return_value="acc_primary")
        with (
            patch(f"{MODULE}.primary_connected_account_id", primary),
            patch(f"{MODULE}.run_on_captured_loop", wraps=run_on_captured_loop) as dispatch,
        ):
            account_id = scoped_connected_account_id("user-1", "gmail")

        assert account_id == "acc_primary"
        primary.assert_awaited_once_with("user-1", "gmail")
        assert dispatch.call_args.kwargs == {"timeout": 10.0}
