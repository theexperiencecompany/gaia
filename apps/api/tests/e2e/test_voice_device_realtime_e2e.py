"""Voice and device pairing as the user experiences them: pick a voice, link a device.

Unit tests prove each half with the other mocked (voice selection with
list_voices patched out, device cap with the cache patched out, websocket
broadcast with Redis patched out). Nothing proved the joins: a spoken name
resolving through the real catalog to a persisted voice id, a pairing code
flowing start → browser approve → daemon poll exactly once, a broadcast
reaching every live socket while the dead one is pruned.

Real: select_voice → list_voices → set_user_voice, the pairing handshake,
token crypto, broadcast publish + local fan-out. Doubled: ElevenLabs (HTTP),
Postgres (fake session), the sockets (mocks).
"""

from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.core.websocket_manager import WebSocketManager, websocket_manager
from app.models.voice_models import ElevenLabsAccountVoice, ElevenLabsSharedVoice
from app.services.account_settings import select_voice
from app.services.device import device_service
from app.services.device.device_auth import (
    create_device_token,
    hash_refresh_token,
    verify_device_token,
)
from app.services.voice_service import list_voices, set_user_voice
from app.utils.errors import AppError

pytestmark = pytest.mark.e2e

VOICE_MOD = "app.services.voice_service"
USER_ID = "507f1f77bcf86cd799439011"


def _account_voice(**overrides: object) -> ElevenLabsAccountVoice:
    data: dict[str, object] = {
        "voice_id": "v-9",
        "name": "Rachel",
        "preview_url": None,
        "labels": {},
        "language_codes": ["en"],
    }
    data.update(overrides)
    return ElevenLabsAccountVoice(**data)


def _shared_voice(**overrides: object) -> ElevenLabsSharedVoice:
    data: dict[str, object] = {
        "voice_id": "lib-1",
        "name": "Library Voice",
        "preview_url": None,
        "public_owner_id": "owner-1",
        "gender": "female",
        "accent": "american",
        "language": "en",
        "descriptive": "warm",
        "use_case": "narration",
        "language_codes": ["en"],
    }
    data.update(overrides)
    return ElevenLabsSharedVoice(**data)


def _voice_seams(
    account: list | None = None, shared: list | None = None, selected: str | None = None
):
    """Double the provider reads at the names list_voices actually calls.

    Patching _fetch_* instead would leave the @Cacheable wrappers live: a
    warm cache (real Redis in CI) serves the real catalog and the test
    asserts against data it never scripted.
    """
    user_repo = MagicMock()
    user_repo.get = AsyncMock(
        return_value=SimpleNamespace(selected_voice_id=selected) if selected else None
    )
    user_repo.set_selected_voice = AsyncMock()
    user_repo.get_starred_voice_ids = AsyncMock(return_value=[])
    user_repo.set_starred_voices = AsyncMock()
    return (
        patch(f"{VOICE_MOD}.get_elevenlabs_voices", AsyncMock(return_value=account or [])),
        patch(f"{VOICE_MOD}.get_shared_voices", AsyncMock(return_value=shared or [])),
        patch(f"{VOICE_MOD}.user_repository", user_repo),
    ), user_repo


class TestVoiceSelectRoundtrip:
    async def test_spoken_name_resolves_to_id_and_persists(self) -> None:
        seams, user_repo = _voice_seams(account=[_account_voice()], shared=[_shared_voice()])
        with seams[0], seams[1], seams[2]:
            message = await select_voice(USER_ID, voice="rachel")

        assert message == "Voice switched to Rachel."
        user_repo.set_selected_voice.assert_awaited_once_with(USER_ID, "v-9")

    async def test_voice_id_resolves_directly(self) -> None:
        seams, user_repo = _voice_seams(account=[_account_voice()], shared=[_shared_voice()])
        with seams[0], seams[1], seams[2]:
            message = await select_voice(USER_ID, voice="v-9")

        assert "Rachel" in message
        user_repo.set_selected_voice.assert_awaited_once_with(USER_ID, "v-9")

    async def test_unknown_voice_is_404_and_persists_nothing(self) -> None:
        seams, user_repo = _voice_seams(account=[_account_voice()], shared=[_shared_voice()])
        with seams[0], seams[1], seams[2]:
            with pytest.raises(AppError) as err:
                await set_user_voice(USER_ID, "ghost-voice")

        assert err.value.status_code == 404
        user_repo.set_selected_voice.assert_not_awaited()

    async def test_catalog_lists_account_first(self) -> None:
        seams, _ = _voice_seams(account=[_account_voice()], shared=[_shared_voice()])
        with seams[0], seams[1], seams[2]:
            catalog = await list_voices(USER_ID)

        ids = [v.voice_id for v in catalog.voices]
        assert "v-9" in ids and "lib-1" in ids
        assert ids.index("v-9") < ids.index("lib-1")


class _FakeResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeSession:
    def __init__(self, active_count: int = 0) -> None:
        self._active_count = active_count
        self.added: list[object] = []

    async def execute(self, _stmt: object) -> _FakeResult:
        return _FakeResult(self._active_count)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        return None


def _fake_session_factory(session: _FakeSession):
    @contextlib.asynccontextmanager
    async def _cm():
        yield session

    return _cm


class TestDevicePairingHandshake:
    async def test_start_lookup_approve_poll_flows_once(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        session = _FakeSession(active_count=0)
        with patch(
            "app.services.device.device_service.get_db_session",
            _fake_session_factory(session),
        ):
            started = await device_service.start_pairing("My Mac", "macos", "1.2.3")
            pending = await device_service.lookup_pending_by_user_code(started.user_code)
            assert pending is not None
            assert pending["device_code"] == started.device_code

            device_id, name = await device_service.approve_pairing(USER_ID, started.user_code)
            assert name == "My Mac"
            assert len(session.added) == 1
            assert session.added[0].id == device_id

            # The user_code is spent — the browser cannot approve twice.
            assert await device_service.lookup_pending_by_user_code(started.user_code) is None

            first_poll = await device_service.poll_pairing(started.device_code)
            assert first_poll.status == "approved"
            # The daemon gets the credential the row was created with.
            assert (
                hash_refresh_token(first_poll.refresh_token) == session.added[0].refresh_token_hash
            )

            # The daemon consumes the approval — a second poll finds nothing.
            second_poll = await device_service.poll_pairing(started.device_code)
            assert second_poll.status == "expired"

    async def test_unknown_codes_are_expired_not_errors(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        assert await device_service.lookup_pending_by_user_code("NOPE-12") is None
        assert (await device_service.poll_pairing("no-such-device")).status == "expired"

    def test_device_token_verifies_and_tampering_fails(self) -> None:
        token, expires_in = create_device_token("dev-1", USER_ID)
        assert expires_in > 0
        claims = verify_device_token(token)
        assert claims is not None
        assert verify_device_token(token + "tampered") is None


class TestWebsocketFanout:
    async def test_broadcast_publishes_user_scoped_envelope(self) -> None:
        redis = MagicMock()
        redis.publish = AsyncMock(return_value=1)
        manager = WebSocketManager()
        with patch("app.core.websocket_manager.redis_cache") as cache:
            cache.redis = redis
            await manager.broadcast_to_user(USER_ID, {"type": "ping"})

        redis.publish.assert_awaited_once()
        channel, payload = redis.publish.await_args.args
        body = json.loads(payload)
        assert body["user_id"] == USER_ID
        assert body["message"] == {"type": "ping"}

    async def test_deliver_local_reaches_every_socket_and_prunes_the_dead(self) -> None:
        manager = WebSocketManager()
        live = MagicMock()
        live.send_json = AsyncMock()
        dead = MagicMock()
        dead.send_json = AsyncMock(side_effect=RuntimeError("gone"))
        manager.add_connection(USER_ID, live)
        manager.add_connection(USER_ID, dead)

        delivered = await manager.deliver_local(USER_ID, {"type": "ping"})

        assert delivered == 1
        live.send_json.assert_awaited_once_with({"type": "ping"})
        assert dead not in manager.connections.get(USER_ID, set())

    def test_singleton_is_a_websocket_manager(self) -> None:
        assert isinstance(websocket_manager, WebSocketManager)
