"""Cover create_live_view_link's call into mint_live_code.

test_live_code.py already covers the link create_live_view_link returns with an
exact-match assertion; this file targets what that leaves open: that
mint_live_code is called with the right arguments in the right order (an
AsyncMock return value alone cannot catch an argument swap).
"""

from unittest.mock import AsyncMock

import pytest

from app.services.browser import live_view


@pytest.mark.unit
async def test_create_live_view_link_mints_code_with_session_and_user_in_order(
    monkeypatch,
):
    mint = AsyncMock(return_value="Xk3p9qR2mN4t")
    monkeypatch.setattr(live_view, "mint_live_code", mint)

    await live_view.create_live_view_link("sess-abc", "user-1", "h1")

    # Order matters: swapping the arguments would still return a link (the mock
    # ignores its inputs) but would mint a code for the wrong session/owner pair.
    mint.assert_called_once_with("sess-abc", "user-1", "h1")
