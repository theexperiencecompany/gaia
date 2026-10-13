"""The per-user device manifest cache and its invalidation contract.

get_device_manifest is the only device read on the per-turn context path; it is
cached for a day and kept correct by clearing on every structural device or
server write. These tests pin both halves: the cache serves repeats, and every
writer clears it, so a revoked device never lingers and a new one is never hidden.
"""

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.constants.cache import ONE_DAY_TTL
from app.constants.device_bridge import MAX_ACTIVE_DEVICES_PER_USER
from app.models.device import DeviceStatus
from app.schemas.device.manifest import DeviceManifestEntry
from app.services.device import device_service
from app.utils.errors import AppError

pytestmark = pytest.mark.unit


class _Result:
    def __init__(self, scalar: object) -> None:
        self._scalar = scalar

    def scalar_one(self) -> object:
        return self._scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalars(self) -> list[object]:
        return []


class _Session:
    """Returns the given scalars in order; records inserts."""

    def __init__(self, *scalars: object) -> None:
        self._scalars = list(scalars)
        self.added: list[object] = []

    async def execute(self, _stmt: object) -> _Result:
        return _Result(self._scalars.pop(0) if self._scalars else None)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def delete(self, _obj: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None


def _session_cm(session: _Session):
    @contextlib.asynccontextmanager
    async def _cm():
        yield session

    return _cm


#: The exact generation-scoped key the reader must use for user "u1" at
#: generation 0 — hard-coded so a mutation of the prefix/method/arg-hash is caught.
_MANIFEST_KEY = "device_manifest:u1:q:0:manifest:v1"


@pytest.fixture
def manifest_cache(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Record every call to the generation-scoped Redis seams.

    Each call is recorded (key, policy, ttl, model), so a test can pin them and a
    mutation of any is caught; a fake that ignored its args would let a mutated
    key or policy pass.
    """
    values: dict[str, object] = {}
    generations: dict[str, object] = {}
    gets: list[tuple[str, object]] = []
    sets: list[tuple[str, int, object]] = []
    reads: list[tuple[object, str]] = []
    bumps: list[tuple[object, str]] = []

    async def _get(key: str, model: object = None) -> object:
        gets.append((key, model))
        return values.get(key)

    async def _set(key: str, value: object, ttl: int = 0, model: object = None) -> None:
        sets.append((key, ttl, model))
        values[key] = value

    async def _read_generation(policy: object, scope: str) -> object:
        reads.append((policy, scope))
        return generations.get(scope, 0)

    async def _bump_generation(policy: object, scope: str) -> None:
        bumps.append((policy, scope))
        generations[scope] = (generations.get(scope) or 0) + 1

    monkeypatch.setattr(device_service, "get_cache", _get)
    monkeypatch.setattr(device_service, "set_cache", _set)
    monkeypatch.setattr(device_service, "read_generation", _read_generation)
    monkeypatch.setattr(device_service, "bump_generation", _bump_generation)
    return SimpleNamespace(
        values=values,
        generations=generations,
        gets=gets,
        sets=sets,
        reads=reads,
        bumps=bumps,
        set=_set,
    )


@pytest.fixture
def invalidate(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    spy = AsyncMock()
    monkeypatch.setattr(device_service, "_invalidate_device_manifest", spy)
    return spy


def _device(device_id: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(id=device_id, name=name, platform="macOS")


class TestGetDeviceManifest:
    async def test_lists_devices_and_their_server_names(
        self, monkeypatch: pytest.MonkeyPatch, manifest_cache: SimpleNamespace
    ) -> None:
        monkeypatch.setattr(
            device_service, "list_devices", AsyncMock(return_value=[_device("d1", "MacBook")])
        )
        monkeypatch.setattr(
            device_service,
            "list_device_servers",
            AsyncMock(return_value={"d1": [SimpleNamespace(display_name="Local Files")]}),
        )

        entries = await device_service.get_device_manifest("u1")

        assert entries == [
            DeviceManifestEntry(id="d1", name="MacBook", platform="macOS", servers=["Local Files"])
        ]

    async def test_the_cache_key_policy_and_ttl_are_exact(
        self, monkeypatch: pytest.MonkeyPatch, manifest_cache: SimpleNamespace
    ) -> None:
        """Pin every argument the cache seams receive so a mutated key or policy fails."""
        list_devices = AsyncMock(return_value=[_device("d1", "MacBook")])
        list_servers = AsyncMock(return_value={"d1": [SimpleNamespace(display_name="Local Files")]})
        monkeypatch.setattr(device_service, "list_devices", list_devices)
        monkeypatch.setattr(device_service, "list_device_servers", list_servers)

        manifest = await device_service.get_device_manifest("u1")

        assert manifest == [
            DeviceManifestEntry(id="d1", name="MacBook", platform="macOS", servers=["Local Files"])
        ]
        list_devices.assert_awaited_once_with("u1")
        list_servers.assert_awaited_once_with(["d1"])
        assert manifest_cache.reads == [(device_service._DEVICE_MANIFEST_POLICY, "u1")]
        assert manifest_cache.gets == [(_MANIFEST_KEY, list[DeviceManifestEntry])]
        assert manifest_cache.sets == [(_MANIFEST_KEY, ONE_DAY_TTL, list[DeviceManifestEntry])]

    async def test_redis_down_skips_the_cache(
        self, monkeypatch: pytest.MonkeyPatch, manifest_cache: SimpleNamespace
    ) -> None:
        """A None generation means no cache at all, not a cache keyed on a sentinel."""
        manifest_cache.generations["u1"] = None
        list_devices = AsyncMock(return_value=[_device("d1", "MacBook")])
        monkeypatch.setattr(device_service, "list_devices", list_devices)
        monkeypatch.setattr(device_service, "list_device_servers", AsyncMock(return_value={}))

        await device_service.get_device_manifest("u1")

        assert manifest_cache.gets == []
        assert manifest_cache.sets == []
        list_devices.assert_awaited_once_with("u1")

    async def test_a_second_call_is_served_from_the_cache(
        self, monkeypatch: pytest.MonkeyPatch, manifest_cache: SimpleNamespace
    ) -> None:
        list_devices = AsyncMock(return_value=[_device("d1", "MacBook")])
        list_servers = AsyncMock(return_value={})
        monkeypatch.setattr(device_service, "list_devices", list_devices)
        monkeypatch.setattr(device_service, "list_device_servers", list_servers)

        first = await device_service.get_device_manifest("u1")
        second = await device_service.get_device_manifest("u1")

        assert first == second
        assert list_devices.await_count == 1
        assert list_servers.await_count == 1

    async def test_no_devices_caches_an_empty_manifest(
        self, monkeypatch: pytest.MonkeyPatch, manifest_cache: SimpleNamespace
    ) -> None:
        list_devices = AsyncMock(return_value=[])
        list_servers = AsyncMock(return_value={})
        monkeypatch.setattr(device_service, "list_devices", list_devices)
        monkeypatch.setattr(device_service, "list_device_servers", list_servers)

        assert await device_service.get_device_manifest("u1") == []
        assert await device_service.get_device_manifest("u1") == []
        assert list_devices.await_count == 1
        list_servers.assert_not_awaited()

    async def test_invalidation_clears_the_cache(
        self, monkeypatch: pytest.MonkeyPatch, manifest_cache: SimpleNamespace
    ) -> None:
        """The real invalidator must bump the generation the reader keyed on."""
        list_devices = AsyncMock(return_value=[_device("d1", "MacBook")])
        monkeypatch.setattr(device_service, "list_devices", list_devices)
        monkeypatch.setattr(device_service, "list_device_servers", AsyncMock(return_value={}))

        await device_service.get_device_manifest("u1")
        await device_service.get_device_manifest("u1")
        assert list_devices.await_count == 1

        await device_service._invalidate_device_manifest("u1")

        assert manifest_cache.bumps == [(device_service._DEVICE_MANIFEST_POLICY, "u1")]
        await device_service.get_device_manifest("u1")
        assert list_devices.await_count == 2

    async def test_a_read_that_stores_after_a_write_cannot_poison_the_cache(
        self, monkeypatch: pytest.MonkeyPatch, manifest_cache: SimpleNamespace
    ) -> None:
        """A store under the old generation key is never served after a concurrent write."""
        list_devices = AsyncMock(return_value=[_device("d1", "MacBook")])
        monkeypatch.setattr(device_service, "list_devices", list_devices)
        monkeypatch.setattr(device_service, "list_device_servers", AsyncMock(return_value={}))

        async def _store_after_write(
            key: str, value: object, ttl: int = 0, model: object = None
        ) -> None:
            # The writer commits and bumps between the reader's compute and store.
            manifest_cache.generations["u1"] = manifest_cache.generations.get("u1", 0) + 1
            await manifest_cache.set(key, value, ttl, model)

        monkeypatch.setattr(device_service, "set_cache", _store_after_write)

        await device_service.get_device_manifest("u1")  # stores under generation 0
        await device_service.get_device_manifest("u1")  # generation 1 → recompute

        assert list_devices.await_count == 2


class TestWritersInvalidateTheManifest:
    """One assertion per structural writer: each clears the user's manifest.

    A writer missing here ships a stale device list — a revoked device stays
    callable, or a newly paired one stays invisible — for up to the day TTL.
    """

    async def test_create_device(
        self, monkeypatch: pytest.MonkeyPatch, invalidate: AsyncMock
    ) -> None:
        monkeypatch.setattr(device_service, "get_db_session", _session_cm(_Session(0)))

        await device_service._create_device("u1", "Mac", "macOS", "1.0", "desktop")

        invalidate.assert_awaited_once_with("u1")

    async def test_rejected_create_does_not_invalidate(
        self, monkeypatch: pytest.MonkeyPatch, invalidate: AsyncMock
    ) -> None:
        session = _Session(MAX_ACTIVE_DEVICES_PER_USER)
        monkeypatch.setattr(device_service, "get_db_session", _session_cm(session))

        with pytest.raises(AppError):
            await device_service._create_device("u1", "Mac", "macOS", "1.0", "desktop")

        invalidate.assert_not_awaited()

    async def test_revoke_device(
        self, monkeypatch: pytest.MonkeyPatch, invalidate: AsyncMock
    ) -> None:
        session = _Session(SimpleNamespace(status=DeviceStatus.ACTIVE))
        monkeypatch.setattr(device_service, "get_db_session", _session_cm(session))
        monkeypatch.setattr(
            device_service, "_device_server_integration_ids", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(device_service, "_teardown_revoked_device", AsyncMock())

        assert await device_service.revoke_device("u1", "d1") is True

        invalidate.assert_awaited_once_with("u1")

    async def test_invalidation_survives_a_post_commit_failure(
        self, monkeypatch: pytest.MonkeyPatch, invalidate: AsyncMock
    ) -> None:
        """Invalidation runs before the fallible cleanup; the write is already committed."""
        session = _Session(SimpleNamespace(status=DeviceStatus.ACTIVE))
        monkeypatch.setattr(device_service, "get_db_session", _session_cm(session))
        monkeypatch.setattr(
            device_service, "_device_server_integration_ids", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(
            device_service, "_teardown_revoked_device", AsyncMock(side_effect=RuntimeError("boom"))
        )

        with pytest.raises(RuntimeError):
            await device_service.revoke_device("u1", "d1")

        invalidate.assert_awaited_once_with("u1")

    async def test_refresh_token_reuse_revocation(
        self, monkeypatch: pytest.MonkeyPatch, invalidate: AsyncMock
    ) -> None:
        replayed = SimpleNamespace(id="d1", user_id="u1", status=DeviceStatus.ACTIVE)
        session = _Session(None, replayed)
        monkeypatch.setattr(device_service, "get_db_session", _session_cm(session))
        monkeypatch.setattr(device_service, "get_cache", AsyncMock(return_value=None))
        monkeypatch.setattr(
            device_service, "_device_server_integration_ids", AsyncMock(return_value=[])
        )
        monkeypatch.setattr(device_service, "_teardown_revoked_device", AsyncMock())

        with pytest.raises(device_service.PairingError):
            await device_service.rotate_refresh_token("replayed-token")

        invalidate.assert_awaited_once_with("u1")

    async def test_register_new_server(
        self, monkeypatch: pytest.MonkeyPatch, invalidate: AsyncMock
    ) -> None:
        monkeypatch.setattr(device_service, "get_db_session", _session_cm(_Session(None)))
        monkeypatch.setattr(device_service, "_create_server_integration", AsyncMock())

        await device_service.register_device_server("u1", "d1", "fs", "Files")

        invalidate.assert_awaited_once_with("u1")

    async def test_register_existing_server(
        self, monkeypatch: pytest.MonkeyPatch, invalidate: AsyncMock
    ) -> None:
        existing = SimpleNamespace(
            display_name="old", kind="stdio", status=None, error_message=None, integration_id="i"
        )
        monkeypatch.setattr(device_service, "get_db_session", _session_cm(_Session(existing)))
        monkeypatch.setattr(device_service, "_ensure_server_integration", AsyncMock())

        await device_service.register_device_server("u1", "d1", "fs", "New")

        invalidate.assert_awaited_once_with("u1")

    async def test_deregister_server(
        self, monkeypatch: pytest.MonkeyPatch, invalidate: AsyncMock
    ) -> None:
        session = _Session(SimpleNamespace(integration_id="int-1"))
        monkeypatch.setattr(device_service, "get_db_session", _session_cm(session))
        monkeypatch.setattr(device_service, "_remove_server_cloud_mirror", AsyncMock())
        monkeypatch.setattr(device_service, "_send_server_remove", AsyncMock())

        assert (
            await device_service.deregister_device_server("u1", "d1", "fs", notify_device=True)
            is True
        )

        invalidate.assert_awaited_once_with("u1")

    async def test_missing_server_deregister_does_not_invalidate(
        self, monkeypatch: pytest.MonkeyPatch, invalidate: AsyncMock
    ) -> None:
        monkeypatch.setattr(device_service, "get_db_session", _session_cm(_Session(None)))

        assert (
            await device_service.deregister_device_server("u1", "d1", "fs", notify_device=True)
            is False
        )

        invalidate.assert_not_awaited()

    async def test_deregister_for_integration(
        self, monkeypatch: pytest.MonkeyPatch, invalidate: AsyncMock
    ) -> None:
        server = SimpleNamespace(device_id="d1", server_key="fs", user_id="u1")
        monkeypatch.setattr(device_service, "get_db_session", _session_cm(_Session(server)))
        monkeypatch.setattr(device_service, "_send_server_remove", AsyncMock())

        assert (
            await device_service.deregister_device_server_for_integration(
                "int-1", notify_device=True
            )
            is True
        )

        invalidate.assert_awaited_once_with("u1")

    async def test_reconcile_prunes_through_the_invalidating_deregister(
        self, monkeypatch: pytest.MonkeyPatch, invalidate: AsyncMock
    ) -> None:
        """Reconcile prunes through deregister_device_server, which owns the invalidation."""
        keep = SimpleNamespace(server_key="keep")
        drop = SimpleNamespace(server_key="drop")
        deregister = AsyncMock()
        monkeypatch.setattr(
            device_service,
            "list_device_servers",
            AsyncMock(return_value={"d1": [keep, drop]}),
        )
        monkeypatch.setattr(device_service, "deregister_device_server", deregister)

        await device_service.reconcile_device_servers("u1", "d1", ["keep"])

        deregister.assert_awaited_once_with("u1", "d1", "drop", notify_device=False)
