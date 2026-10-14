"""Unit tests for the desktop tool-result bridge endpoint (POST /api/v1/desktop/tool-result)."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from tests.conftest import FAKE_USER

_MOD = "app.api.v1.endpoints.desktop"


class TestDesktopToolResult:
    async def test_result_is_relayed_for_the_calling_user(self, client: AsyncClient) -> None:
        with (
            patch(f"{_MOD}.relay_desktop_result", new_callable=AsyncMock) as mock_relay,
            patch(f"{_MOD}.log") as mock_log,
        ):
            resp = await client.post(
                "/api/v1/desktop/tool-result",
                json={"request_id": "req-1", "ok": False, "error": "denied"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"success": True}
        mock_relay.assert_awaited_once_with(
            request_id="req-1",
            user_id=FAKE_USER.user_id,
            ok=False,
            data=None,
            error="denied",
        )
        mock_log.set.assert_any_call(
            user={"id": FAKE_USER.user_id},
            desktop_tool={"request_id": "req-1", "ok": False},
        )
