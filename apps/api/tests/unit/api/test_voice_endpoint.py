"""Unit tests for the voice mode endpoints.

Covers the LiveKit token minting route (with real JWT minting against fake
keys) and the voice catalog/selection/star routes. Service layer is mocked;
status codes, response shapes, and payload forwarding are verified.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from jose import jwt
import pytest

from app.config.settings import settings
from app.models.payment_models import PlanType
from app.schemas.voice_schemas import VoiceListResponse, VoiceOption
from app.services.analytics_service import AnalyticsEvents
from app.utils.errors import AppError

VOICE_BASE = "/api/v1"
USER_ID = "507f1f77bcf86cd799439011"
FAKE_API_KEY = "test_api_key"
FAKE_API_SECRET = "test_api_secret"  # nosec B105 — fake test credential

# The `client` fixture's user is FREE by default (root conftest patches
# get_user_subscription_status to FREE) — voice is paid-only, so /token 402s
# before the handler runs. Classes exercising token behavior (not the paywall
# itself) opt into PRO through the same seam the gate reads.
_GET_SUBSCRIPTION_STATUS = (
    "app.services.payments.payment_service.payment_service.get_user_subscription_status"
)


def _subscription_mock(plan_type: PlanType = PlanType.PRO) -> MagicMock:
    sub = MagicMock()
    sub.plan_type = plan_type
    return sub


@pytest.fixture(autouse=True)
def _no_real_redis_plan_cache():
    """``get_cached_plan_type`` caches the tier in Redis under a key derived
    from the user id, and every test here shares FAKE_USER's id — without this
    a tier cached by one test leaks into the next (the stray local-Redis
    singleton flake noted in ``apps/api/CLAUDE.md``)."""
    with (
        patch(
            "app.services.payments.payment_service.redis_cache.get",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.payments.payment_service.redis_cache.set",
            new=AsyncMock(),
        ),
    ):
        yield


def _voice_option(voice_id: str = "v1", name: str = "Aria") -> VoiceOption:
    return VoiceOption(
        voice_id=voice_id,
        name=name,
        language="English",
        accent="American",
        country_code="US",
        gender="Female",
        description="Warm and clear",
        preview_url=None,
        source="account",
        languages=["English"],
        starred=False,
    )


def _decode_token(token: str) -> dict:
    """Decode the participant JWT without verifying (payload inspection only)."""
    return jwt.decode(token, "", options={"verify_signature": False})


# ---------------------------------------------------------------------------
# GET /token
# ---------------------------------------------------------------------------


class TestGetVoiceToken:
    """GET /api/v1/token — LiveKit room token minting"""

    @pytest.fixture(autouse=True)
    def _pro_subscription(self):
        with patch(
            _GET_SUBSCRIPTION_STATUS,
            new_callable=AsyncMock,
            return_value=_subscription_mock(),
        ):
            yield

    def _enable_livekit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "LIVEKIT_API_KEY", FAKE_API_KEY)
        monkeypatch.setattr(settings, "LIVEKIT_API_SECRET", FAKE_API_SECRET)
        monkeypatch.setattr(settings, "LIVEKIT_URL", "wss://test.livekit.cloud")

    @patch("app.api.v1.endpoints.voice.get_user_voice", new_callable=AsyncMock)
    async def test_token_success(
        self, mock_get_voice: AsyncMock, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        self._enable_livekit(monkeypatch)
        mock_get_voice.return_value = "voice-1"
        resp = await client.get(VOICE_BASE + "/token")
        assert resp.status_code == 200
        body = resp.json()
        assert body["serverUrl"] == "wss://test.livekit.cloud"
        assert body["roomName"].startswith("voice_session_")
        assert body["participantIdentity"] == f"user_{USER_ID}"
        assert body["participantName"] == "test@example.com"
        assert body["conversation_id"] is None

        claims = _decode_token(body["participantToken"])
        assert claims["sub"] == f"user_{USER_ID}"
        assert claims["iss"] == FAKE_API_KEY
        metadata = json.loads(claims["metadata"])
        assert metadata["identity"] == f"user_{USER_ID}"
        assert metadata["roomName"] == body["roomName"]
        assert metadata["voiceId"] == "voice-1"

    @patch("app.api.v1.endpoints.voice.get_user_voice", new_callable=AsyncMock)
    async def test_token_carries_conversation_id_and_backend_url(
        self, mock_get_voice: AsyncMock, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        self._enable_livekit(monkeypatch)
        monkeypatch.setattr(settings, "VOICE_AGENT_BACKEND_URL", "http://api.test")
        mock_get_voice.return_value = None
        resp = await client.get(VOICE_BASE + "/token", params={"conversationId": "conv-42"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["conversation_id"] == "conv-42"
        metadata = json.loads(_decode_token(body["participantToken"])["metadata"])
        assert metadata["conversationId"] == "conv-42"
        assert metadata["backendUrl"] == "http://api.test"
        # No stored voice → no voiceId key (the agent uses its default).
        assert "voiceId" not in metadata
        mock_get_voice.assert_awaited_once_with(USER_ID)

    @patch("app.api.v1.endpoints.voice.get_user_voice", new_callable=AsyncMock)
    async def test_token_fails_when_livekit_keys_are_missing(
        self, mock_get_voice: AsyncMock, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "LIVEKIT_API_KEY", None)
        monkeypatch.setattr(settings, "LIVEKIT_API_SECRET", None)
        mock_get_voice.return_value = None
        resp = await client.get(VOICE_BASE + "/token")
        assert resp.status_code == 500
        assert "Failed to generate voice token" in resp.json()["detail"]

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.get(VOICE_BASE + "/token")
        assert resp.status_code == 401


class TestVoicePaidOnlyGate:
    """402 contract on /token — a voice session is spend, so it is Pro-only."""

    @patch("app.api.v1.endpoints.voice.get_user_voice", new_callable=AsyncMock)
    async def test_free_user_gets_402_and_never_mints_a_token(
        self, mock_get_voice: AsyncMock, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "LIVEKIT_API_KEY", FAKE_API_KEY)
        monkeypatch.setattr(settings, "LIVEKIT_API_SECRET", FAKE_API_SECRET)
        monkeypatch.setattr(settings, "LIVEKIT_URL", "wss://test.livekit.cloud")

        resp = await client.get(VOICE_BASE + "/token")

        assert resp.status_code == 402
        assert resp.json()["detail"]["code"] == "subscription_required"
        mock_get_voice.assert_not_called()

    @patch("app.api.v1.endpoints.voice.get_user_voice", new_callable=AsyncMock)
    async def test_pro_user_still_gets_a_token(
        self, mock_get_voice: AsyncMock, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "LIVEKIT_API_KEY", FAKE_API_KEY)
        monkeypatch.setattr(settings, "LIVEKIT_API_SECRET", FAKE_API_SECRET)
        monkeypatch.setattr(settings, "LIVEKIT_URL", "wss://test.livekit.cloud")
        mock_get_voice.return_value = None

        with patch(
            _GET_SUBSCRIPTION_STATUS,
            new_callable=AsyncMock,
            return_value=_subscription_mock(),
        ):
            resp = await client.get(VOICE_BASE + "/token")

        assert resp.status_code == 200
        assert resp.json()["participantToken"]


# ---------------------------------------------------------------------------
# GET /voice/voices
# ---------------------------------------------------------------------------


class TestListVoices:
    """GET /api/v1/voice/voices"""

    @patch("app.api.v1.endpoints.voice.list_voices", new_callable=AsyncMock)
    async def test_list_voices_success(self, mock_list: AsyncMock, client: AsyncClient):
        mock_list.return_value = VoiceListResponse(
            voices=[_voice_option("v1", "Aria"), _voice_option("v2", "Orion")],
            selected_voice_id="v1",
        )
        resp = await client.get(f"{VOICE_BASE}/voice/voices")
        assert resp.status_code == 200
        body = resp.json()
        assert body["selected_voice_id"] == "v1"
        assert [v["voice_id"] for v in body["voices"]] == ["v1", "v2"]
        assert body["voices"][0]["name"] == "Aria"
        mock_list.assert_awaited_once_with(USER_ID)

    @patch("app.api.v1.endpoints.voice.list_voices", new_callable=AsyncMock)
    async def test_list_voices_service_error(self, mock_list: AsyncMock, client: AsyncClient):
        mock_list.side_effect = Exception("elevenlabs down")
        resp = await client.get(f"{VOICE_BASE}/voice/voices")
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.get(f"{VOICE_BASE}/voice/voices")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /voice/voices/selected
# ---------------------------------------------------------------------------


class TestSelectVoice:
    """PUT /api/v1/voice/voices/selected"""

    @patch("app.api.v1.endpoints.voice.set_user_voice", new_callable=AsyncMock)
    async def test_select_voice_success(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.return_value = "voice-1"
        with (
            patch("app.api.v1.endpoints.voice.capture_context_event") as mock_capture,
            patch("app.api.v1.endpoints.voice.schedule_account_sync") as mock_schedule_sync,
        ):
            resp = await client.put(
                f"{VOICE_BASE}/voice/voices/selected", json={"voice_id": "voice-1"}
            )
        assert resp.status_code == 200
        assert resp.json() == {"selected_voice_id": "voice-1"}
        mock_set.assert_awaited_once_with(USER_ID, "voice-1")
        mock_schedule_sync.assert_called_once_with(USER_ID)
        mock_capture.assert_called_once_with(
            AnalyticsEvents.SETTINGS_PREFERENCES_CHANGED,
            {"setting": "voice", "voice_id": "voice-1"},
        )

    @patch("app.api.v1.endpoints.voice.set_user_voice", new_callable=AsyncMock)
    async def test_unknown_voice_is_404(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.side_effect = AppError(
            message="Unknown voice",
            why="Voice id 'nope' is not on the account or in the voice library",
            status_code=404,
        )
        resp = await client.put(f"{VOICE_BASE}/voice/voices/selected", json={"voice_id": "nope"})
        assert resp.status_code == 404
        assert resp.json()["message"] == "Unknown voice"

    async def test_empty_voice_id_is_rejected(self, client: AsyncClient):
        resp = await client.put(f"{VOICE_BASE}/voice/voices/selected", json={"voice_id": ""})
        assert resp.status_code == 422

    @patch("app.api.v1.endpoints.voice.set_user_voice", new_callable=AsyncMock)
    async def test_service_error_is_500(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.side_effect = Exception("mongo down")
        resp = await client.put(f"{VOICE_BASE}/voice/voices/selected", json={"voice_id": "voice-1"})
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.put(
            f"{VOICE_BASE}/voice/voices/selected", json={"voice_id": "voice-1"}
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /voice/voices/{voice_id}/star
# ---------------------------------------------------------------------------


class TestStarVoice:
    """PUT /api/v1/voice/voices/{voice_id}/star"""

    @patch("app.api.v1.endpoints.voice.set_voice_star", new_callable=AsyncMock)
    async def test_star_voice_success(self, mock_star: AsyncMock, client: AsyncClient):
        mock_star.return_value = ["voice-1", "voice-2"]
        with patch("app.api.v1.endpoints.voice.capture_context_event") as mock_capture:
            resp = await client.put(
                f"{VOICE_BASE}/voice/voices/voice-1/star", json={"starred": True}
            )
        assert resp.status_code == 200
        assert resp.json() == {"starred_voice_ids": ["voice-1", "voice-2"]}
        mock_star.assert_awaited_once_with(USER_ID, "voice-1", True)
        mock_capture.assert_called_once_with(
            AnalyticsEvents.SETTINGS_PREFERENCES_CHANGED,
            {"setting": "voice_star", "voice_id": "voice-1", "is_starred": True},
        )

    @patch("app.api.v1.endpoints.voice.set_voice_star", new_callable=AsyncMock)
    async def test_unstar_voice_success(self, mock_star: AsyncMock, client: AsyncClient):
        mock_star.return_value = []
        with patch("app.api.v1.endpoints.voice.capture_context_event") as mock_capture:
            resp = await client.put(
                f"{VOICE_BASE}/voice/voices/voice-1/star", json={"starred": False}
            )
        assert resp.status_code == 200
        assert resp.json() == {"starred_voice_ids": []}
        mock_star.assert_awaited_once_with(USER_ID, "voice-1", False)
        mock_capture.assert_called_once_with(
            AnalyticsEvents.SETTINGS_PREFERENCES_CHANGED,
            {"setting": "voice_star", "voice_id": "voice-1", "is_starred": False},
        )

    @patch("app.api.v1.endpoints.voice.set_voice_star", new_callable=AsyncMock)
    async def test_service_error_is_500(self, mock_star: AsyncMock, client: AsyncClient):
        mock_star.side_effect = Exception("mongo down")
        resp = await client.put(f"{VOICE_BASE}/voice/voices/voice-1/star", json={"starred": True})
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.put(
            f"{VOICE_BASE}/voice/voices/voice-1/star", json={"starred": True}
        )
        assert resp.status_code == 401
