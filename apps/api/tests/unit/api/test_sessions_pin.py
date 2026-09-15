"""POST /api/v1/sessions/{conv_id}/pin — the pinned path comes back, errors are the envelope."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.services.analytics_service import AnalyticsEvents
from app.services.storage import JuiceFSUnavailable
from tests.conftest import FAKE_USER

PIN_URL = "/api/v1/sessions/conv_1/pin"
_MODULE = "app.api.v1.endpoints.sessions"


@pytest.fixture
def owns_conversation():
    with patch(f"{_MODULE}.conversation_repository.exists", new_callable=AsyncMock) as exists:
        exists.return_value = True
        yield exists


@pytest.mark.usefixtures("owns_conversation")
class TestPinArtifact:
    async def test_returns_the_pinned_workspace_path(self, client: AsyncClient) -> None:
        with (
            patch(f"{_MODULE}.pin_session_artifact", new_callable=AsyncMock) as pin,
            patch(f"{_MODULE}.capture_context_event") as capture,
        ):
            pin.return_value = "/workspace/pinned/report.pdf"
            resp = await client.post(PIN_URL, json={"path": "out/report.pdf"})

        assert resp.status_code == 201
        assert resp.json() == {"pinned_path": "/workspace/pinned/report.pdf"}
        pin.assert_awaited_once_with(FAKE_USER["user_id"], "conv_1", "out/report.pdf", None)
        capture.assert_called_once_with(AnalyticsEvents.SESSION_ARTIFACT_PINNED)

    async def test_a_target_name_is_handed_through(self, client: AsyncClient) -> None:
        with patch(f"{_MODULE}.pin_session_artifact", new_callable=AsyncMock) as pin:
            pin.return_value = "/workspace/pinned/final.pdf"
            await client.post(PIN_URL, json={"path": "out/report.pdf", "target_name": "final.pdf"})

        pin.assert_awaited_once_with(FAKE_USER["user_id"], "conv_1", "out/report.pdf", "final.pdf")

    @pytest.mark.parametrize(
        ("raised", "status", "message"),
        [
            (ValueError("escapes"), 400, "Invalid path"),
            (FileNotFoundError("gone"), 404, "Artifact not found"),
            (JuiceFSUnavailable("mount down"), 503, "Workspace storage offline"),
        ],
    )
    async def test_storage_failures_are_the_envelope(
        self, client: AsyncClient, raised: Exception, status: int, message: str
    ) -> None:
        with patch(f"{_MODULE}.pin_session_artifact", new_callable=AsyncMock, side_effect=raised):
            resp = await client.post(PIN_URL, json={"path": "out/report.pdf"})

        assert resp.status_code == status
        assert resp.json() == {"message": message}


async def test_a_conversation_the_user_does_not_own_is_403(client: AsyncClient) -> None:
    with (
        patch(f"{_MODULE}.conversation_repository.exists", new_callable=AsyncMock) as exists,
        patch(f"{_MODULE}.pin_session_artifact", new_callable=AsyncMock) as pin,
    ):
        exists.return_value = False
        resp = await client.post(PIN_URL, json={"path": "out/report.pdf"})

    assert resp.status_code == 403
    assert resp.json() == {"message": "Conversation not found or not owned by this user"}
    pin.assert_not_awaited()
