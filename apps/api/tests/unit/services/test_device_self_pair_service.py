"""Unit tests for the shared device-creation path (device_service._create_device).

Proves the per-user active-device cap fires identically from BOTH entry points
(self_pair_device and approve_pairing), and that the browser-approval path leaves
client NULL while self-pair stamps it. The Postgres session and Redis are the
only fakes — the real service logic runs.
"""

import contextlib
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from app.constants.device_bridge import MAX_ACTIVE_DEVICES_PER_USER
from app.models.device import DeviceStatus
from app.services.device import device_service
from app.services.device.device_auth import hash_refresh_token
from app.utils.errors import AppError
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

_DB_SESSION = "app.services.device.device_service.get_db_session"
_USER = "507f1f77bcf86cd799439011"


class _FakeResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _FakeSession:
    def __init__(self, active_count: int) -> None:
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


class TestSelfPairDevice:
    async def test_stamps_client_and_mints_matching_token(self) -> None:
        session = _FakeSession(active_count=0)
        with patch(_DB_SESSION, _fake_session_factory(session)):
            device_id, refresh_token = await device_service.self_pair_device(
                _USER, "My Mac", "macos", "desktop", "1.2.3"
            )

        assert len(session.added) == 1
        device = session.added[0]
        # The row is stamped from the exact call arguments, and its id is the
        # value returned to the caller — a real uuid, not str(None).
        assert device.id == device_id
        uuid.UUID(device_id)  # raises if _create_device returned str(None) or garbage
        assert device.user_id == _USER
        assert device.name == "My Mac"
        assert device.client == "desktop"
        assert device.platform == "macos"
        assert device.daemon_version == "1.2.3"
        assert device.status == DeviceStatus.ACTIVE
        # The returned plaintext token is exactly the credential stored (hashed).
        assert hash_refresh_token(refresh_token) == device.refresh_token_hash

    async def test_emits_self_pair_wide_event(self) -> None:
        session = _FakeSession(active_count=0)
        with patch(_DB_SESSION, _fake_session_factory(session)):
            async with captured_wide_event() as event:
                device_id, _ = await device_service.self_pair_device(
                    _USER, "My Mac", "macos", "desktop", "1.2.3"
                )
        # The operation, the device id, and the owning user are all pinned on the
        # wide event — mutating device_code=None, the operation string, or the
        # user id must break this.
        assert event["device"] == {"operation": "self_pair", "device_id": device_id}
        assert event["user"] == {"id": _USER}

    async def test_cap_rejects_self_pair(self) -> None:
        session = _FakeSession(active_count=MAX_ACTIVE_DEVICES_PER_USER)
        with patch(_DB_SESSION, _fake_session_factory(session)):
            with pytest.raises(AppError) as exc:
                await device_service.self_pair_device(_USER, "My Mac", "macos", "desktop", None)
        assert exc.value.status_code == 409
        assert session.added == []

    async def test_cap_error_carries_exact_user_facing_strings(self) -> None:
        # The 409 payload is user-facing copy; a blanked/case-swapped/XX-wrapped
        # string is a shipped bug, so assert every field verbatim.
        session = _FakeSession(active_count=MAX_ACTIVE_DEVICES_PER_USER)
        with patch(_DB_SESSION, _fake_session_factory(session)):
            with pytest.raises(AppError) as exc:
                await device_service.self_pair_device(_USER, "My Mac", "macos", "desktop", None)
        err = exc.value
        assert err.message == "Device limit reached"
        assert err.why == f"You already have {MAX_ACTIVE_DEVICES_PER_USER} active devices."
        assert err.fix == "Revoke a device you no longer use, then pair this one again."


class TestApprovePairingSharedCap:
    async def test_stamps_null_client(self) -> None:
        session = _FakeSession(active_count=0)
        pending = {
            "device_code": "dc",
            "name": "CLI box",
            "platform": "linux",
            "daemon_version": "0.1",
        }
        mock_set_cache = AsyncMock(return_value=True)
        mock_delete = AsyncMock(return_value=None)
        with (
            patch(_DB_SESSION, _fake_session_factory(session)),
            patch.object(
                device_service, "lookup_pending_by_user_code", AsyncMock(return_value=pending)
            ),
            patch.object(device_service, "set_cache", mock_set_cache),
            patch.object(device_service, "get_and_delete_cache", mock_delete),
        ):
            device_id, name = await device_service.approve_pairing(_USER, "gaia-7f3k")

        assert device_id
        assert name == "CLI box"
        assert len(session.added) == 1
        device = session.added[0]
        # The device carries the pending record's fields (pending.get key mutants)
        # and belongs to the approving user, not client-stamped (CLI keeps NULL).
        assert device.user_id == _USER
        assert device.name == "CLI box"
        assert device.platform == "linux"
        assert device.daemon_version == "0.1"
        assert device.client is None

        # The approved record is written back under the pending's OWN device_code
        # key (not None), so the daemon's poll finds it.
        assert mock_set_cache.call_count == 1
        key_arg, record_arg = mock_set_cache.call_args.args[0], mock_set_cache.call_args.args[1]
        assert key_arg == device_service._pairing_key("dc")
        assert record_arg["status"] == "approved"
        assert record_arg["device_id"] == device_id
        assert record_arg["refresh_token"]
        assert "device_code" not in record_arg
        # The spent user_code's reverse lookup is dropped so it can't be reused,
        # and the lookup is normalized to upper-case first.
        mock_delete.assert_awaited_once_with(device_service._user_code_key("GAIA-7F3K"))

    async def test_same_cap_rejects_approve_pairing(self) -> None:
        session = _FakeSession(active_count=MAX_ACTIVE_DEVICES_PER_USER)
        pending = {"device_code": "dc", "name": "CLI box", "platform": "linux"}
        with (
            patch(_DB_SESSION, _fake_session_factory(session)),
            patch.object(
                device_service, "lookup_pending_by_user_code", AsyncMock(return_value=pending)
            ),
            patch.object(device_service, "set_cache", AsyncMock(return_value=True)),
            patch.object(device_service, "get_and_delete_cache", AsyncMock(return_value=None)),
        ):
            with pytest.raises(AppError) as exc:
                await device_service.approve_pairing(_USER, "GAIA-7F3K")

        assert exc.value.status_code == 409
        assert session.added == []
