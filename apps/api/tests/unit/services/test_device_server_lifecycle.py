"""Unit tests for the device MCP-server lifecycle in device_service.

Covers registration, integration-mirror create/remove, daemon notify frames,
deregistration (both entry points), HELLO reconcile, warm-connect recording,
warmup enqueue, and revoke teardown. The Postgres session, Redis pool, the
bridge send/revoke calls, and the integration repo/user-integration seams are
the only fakes — every function's real branching and string-building runs.
"""

import contextlib
from datetime import UTC, datetime
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.constants.device_bridge import (
    DEVICE_CATEGORY,
    DEVICE_TRANSPORT,
    FRAME_SERVER_REMOVE,
    MAX_ACTIVE_DEVICES_PER_USER,
)
from app.db.postgresql import Base
from app.models.device import Device, DeviceMCPServer, DeviceServerStatus, DeviceStatus
from app.services.device import device_service
from app.utils.errors import AppError
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

_DB = "app.services.device.device_service.get_db_session"


class _Result:
    def __init__(self, scalar: object) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalar_one(self) -> object:
        return self._scalar


class _FakeSession:
    """Answers one scalar query and records mutations so a test can assert exact writes."""

    def __init__(self, scalar: object = None) -> None:
        self._scalar = scalar
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.executed: list[object] = []
        self.commits = 0
        self.refreshed: list[object] = []

    async def execute(self, stmt: object) -> _Result:
        self.executed.append(stmt)
        return _Result(self._scalar)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def delete(self, obj: object) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, obj: object) -> None:
        self.refreshed.append(obj)


def _session_cm(session: _FakeSession):
    @contextlib.asynccontextmanager
    async def _cm():
        yield session

    return _cm


@pytest.fixture
async def sqlite_session():
    """Bind a real in-memory SQLite session for device_service.get_db_session.

    A fake session returns a fixed row regardless of the query, so it can't prove a WHERE
    predicate is right; this runs the real SELECT/DELETE so seeding a target + decoy row
    makes where(None) and == vs != mutants observably fail. StaticPool keeps one connection
    so seeded rows persist across the fixture's and the function's separate sessions.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[Device.__table__, DeviceMCPServer.__table__]
            )
        )
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @contextlib.asynccontextmanager
    async def _cm():
        async with maker() as session:
            yield session

    with patch(_DB, _cm):
        yield maker
    await engine.dispose()


def _server(device_id: str, server_key: str, integration_id: str, **kw: object) -> DeviceMCPServer:
    """Build a DeviceMCPServer row with sane defaults for seeding."""
    return DeviceMCPServer(
        device_id=device_id,
        user_id=kw.pop("user_id", "u1"),
        integration_id=integration_id,
        server_key=server_key,
        display_name=kw.pop("display_name", server_key),
        kind=kw.pop("kind", "stdio"),
        status=kw.pop("status", DeviceServerStatus.CONNECTED),
        **kw,
    )


class TestBuildDeviceApproveUrl:
    def test_normalizes_and_builds_the_signed_in_url(self) -> None:
        # Trailing slash trimmed once; code stripped, upper-cased, url-encoded.
        with patch.object(device_service, "get_frontend_url", return_value="https://gaia.test/"):
            url = device_service.build_device_approve_url("  gaia 7f3k  ")
        assert url == "https://gaia.test/settings/devices/approve?code=GAIA%207F3K"

    def test_rstrip_strips_only_slashes(self) -> None:
        # rstrip takes a char set: rstrip("/") must not eat a trailing "X" the
        # way a widened set would — the host keeps its name verbatim.
        with patch.object(device_service, "get_frontend_url", return_value="https://gaia.test/X"):
            url = device_service.build_device_approve_url("AB12")
        assert url == "https://gaia.test/X/settings/devices/approve?code=AB12"


class TestRegisterDeviceServer:
    async def test_creates_row_and_integration_when_new(self) -> None:
        session = _FakeSession(scalar=None)
        create_mock = AsyncMock()
        with (
            patch(_DB, _session_cm(session)),
            patch.object(device_service, "_create_server_integration", create_mock),
        ):
            server = await device_service.register_device_server(
                "u1", "dev1", "fs", "Filesystem", kind="url"
            )

        assert len(session.added) == 1
        assert session.added[0] is server
        assert server.device_id == "dev1"
        assert server.user_id == "u1"
        assert server.server_key == "fs"
        assert server.display_name == "Filesystem"
        assert server.kind == "url"
        assert server.status == DeviceServerStatus.CONNECTED
        # The integration is created under the SAME id minted for the row, with
        # the row's fields in order — a swapped/dropped arg breaks this.
        create_mock.assert_awaited_once_with(
            "u1", "dev1", "fs", "Filesystem", server.integration_id
        )
        assert session.commits == 1
        assert session.refreshed == [server]

    async def test_updates_existing_row_and_reensures_integration(self) -> None:
        existing = SimpleNamespace(
            display_name="old",
            kind="stdio",
            status=DeviceServerStatus.ERROR,
            error_message="prev failure",
            integration_id="int-x",
            device_id="dev1",
            server_key="fs",
        )
        session = _FakeSession(scalar=existing)
        ensure_mock = AsyncMock()
        create_mock = AsyncMock()
        with (
            patch(_DB, _session_cm(session)),
            patch.object(device_service, "_ensure_server_integration", ensure_mock),
            patch.object(device_service, "_create_server_integration", create_mock),
        ):
            result = await device_service.register_device_server(
                "u1", "dev1", "fs", "New Name", kind="filesystem"
            )

        assert result is existing
        assert existing.display_name == "New Name"
        assert existing.kind == "filesystem"
        assert existing.status == DeviceServerStatus.CONNECTED
        assert existing.error_message is None
        # Re-registration reuses the doc via _ensure; it never inserts a rival row.
        ensure_mock.assert_awaited_once_with("u1", existing)
        create_mock.assert_not_awaited()
        assert session.added == []

    async def test_kind_defaults_to_stdio(self) -> None:
        # The `kind` parameter defaults to "stdio"; a mutated default would stamp
        # the wrong transport on every server added without an explicit kind.
        session = _FakeSession(scalar=None)
        with (
            patch(_DB, _session_cm(session)),
            patch.object(device_service, "_create_server_integration", AsyncMock()),
        ):
            server = await device_service.register_device_server("u1", "dev1", "fs", "Filesystem")
        assert server.kind == "stdio"


class TestDeviceDisplayName:
    async def test_returns_the_device_name(self, sqlite_session) -> None:
        # Two devices: the query must pick THIS one by id. A dropped/None/!= or
        # select-all predicate returns the wrong name or raises MultipleResultsFound.
        async with sqlite_session() as s:
            s.add(Device(id="dev1", user_id="u1", name="Dhruv's MacBook", refresh_token_hash="h1"))
            s.add(Device(id="dev2", user_id="u1", name="Decoy", refresh_token_hash="h2"))
            await s.commit()
        assert await device_service._device_display_name("dev1") == "Dhruv's MacBook"

    async def test_falls_back_when_row_is_gone(self, sqlite_session) -> None:
        assert await device_service._device_display_name("missing") == "this device"


class TestCreateServerIntegration:
    async def test_builds_integration_and_links_user(self) -> None:
        create_mock = AsyncMock()
        add_mock = AsyncMock()
        invalidate_mock = AsyncMock()
        display_name_mock = AsyncMock(return_value="My Laptop")
        with (
            patch.object(device_service, "_device_display_name", display_name_mock),
            patch.object(device_service.integration_repository, "create", create_mock),
            patch.object(device_service, "add_user_integration", add_mock),
            patch.object(device_service, "invalidate_user_integration_caches", invalidate_mock),
        ):
            await device_service._create_server_integration(
                "u1", "dev1", "fs", "Filesystem", "int-1"
            )

        # The device name is looked up for THIS device (kills the (None) arg mutant).
        display_name_mock.assert_awaited_once_with("dev1")
        create_mock.assert_awaited_once()
        integration = create_mock.call_args.args[0]
        assert integration.integration_id == "int-1"
        assert integration.name == "Filesystem"
        # The description names the device and states the tools run locally — the
        # subagent's discovery text inherits it verbatim.
        assert integration.description == (
            'MCP server hosted on your device "My Laptop". Its tools run '
            "locally on that machine, not the cloud sandbox."
        )
        assert integration.mcp_config.server_url == "device://dev1/fs"
        # The dedup key is the normalized device URL — a None key would opt the
        # mirror out of the per-creator unique index.
        assert integration.mcp_config.server_url_normalized == "device://dev1/fs"
        assert integration.category == DEVICE_CATEGORY
        assert integration.managed_by == "mcp"
        assert integration.source == "custom"
        assert integration.is_public is False
        assert integration.created_by == "u1"
        assert integration.mcp_config.server_url == device_service._device_server_url("dev1", "fs")
        assert integration.mcp_config.transport == DEVICE_TRANSPORT
        assert integration.mcp_config.requires_auth is False
        assert integration.mcp_config.auth_type == "none"
        add_mock.assert_awaited_once_with("u1", "int-1", initial_status="connected")
        invalidate_mock.assert_awaited_once_with("u1")


class TestRemoveServerCloudMirror:
    async def test_drops_doc_link_and_caches(self) -> None:
        delete_mock = AsyncMock()
        remove_mock = AsyncMock()
        invalidate_mock = AsyncMock()
        with (
            patch.object(device_service.integration_repository, "delete", delete_mock),
            patch.object(device_service, "remove_user_integration", remove_mock),
            patch.object(device_service, "invalidate_user_integration_caches", invalidate_mock),
        ):
            await device_service._remove_server_cloud_mirror("u1", "int-1")
        delete_mock.assert_awaited_once_with("int-1")
        remove_mock.assert_awaited_once_with("u1", "int-1")
        invalidate_mock.assert_awaited_once_with("u1")


class TestSendServerRemove:
    async def test_sends_the_remove_frame(self) -> None:
        send_mock = AsyncMock()
        with patch.object(device_service, "send_down", send_mock):
            await device_service._send_server_remove("dev1", "fs")
        send_mock.assert_awaited_once_with("dev1", {"t": FRAME_SERVER_REMOVE, "key": "fs"})

    async def test_swallows_and_warns_on_send_failure(self) -> None:
        send_mock = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(device_service, "send_down", send_mock):
            async with captured_wide_event() as event:
                # Best-effort delivery: a send failure must not propagate.
                await device_service._send_server_remove("dev1", "fs")
        (warning,) = event["warnings"]
        assert "Failed to send server-remove" in warning["msg"]
        assert warning["device_id"] == "dev1"
        assert warning["server_key"] == "fs"
        assert warning["error"] == "boom"
        assert warning["error_type"] == "RuntimeError"


class TestDeregisterDeviceServer:
    async def test_returns_false_when_missing(self) -> None:
        session = _FakeSession(scalar=None)
        mirror_mock = AsyncMock()
        with (
            patch(_DB, _session_cm(session)),
            patch.object(device_service, "_remove_server_cloud_mirror", mirror_mock),
        ):
            result = await device_service.deregister_device_server(
                "u1", "dev1", "fs", notify_device=True
            )
        assert result is False
        mirror_mock.assert_not_awaited()
        assert session.deleted == []

    async def test_removes_row_and_mirror_and_notifies(self, sqlite_session) -> None:
        # Target + decoy on the SAME device: a dropped/None/!= or select-all
        # predicate deletes the wrong row (mirror gets int-2) or raises.
        async with sqlite_session() as s:
            s.add(_server("dev1", "fs", "int-1"))
            s.add(_server("dev1", "other", "int-2"))
            await s.commit()
        mirror_mock = AsyncMock()
        send_mock = AsyncMock()
        with (
            patch.object(device_service, "_remove_server_cloud_mirror", mirror_mock),
            patch.object(device_service, "_send_server_remove", send_mock),
        ):
            result = await device_service.deregister_device_server(
                "u1", "dev1", "fs", notify_device=True
            )
        assert result is True
        mirror_mock.assert_awaited_once_with("u1", "int-1")
        send_mock.assert_awaited_once_with("dev1", "fs")
        async with sqlite_session() as s:
            remaining = (await s.execute(select(DeviceMCPServer.server_key))).scalars().all()
        assert remaining == ["other"]

    async def test_skips_notify_when_not_requested(self) -> None:
        server = SimpleNamespace(integration_id="int-1")
        session = _FakeSession(scalar=server)
        send_mock = AsyncMock()
        with (
            patch(_DB, _session_cm(session)),
            patch.object(device_service, "_remove_server_cloud_mirror", AsyncMock()),
            patch.object(device_service, "_send_server_remove", send_mock),
        ):
            await device_service.deregister_device_server("u1", "dev1", "fs", notify_device=False)
        send_mock.assert_not_awaited()


class TestDeregisterForIntegration:
    async def test_returns_false_when_not_a_device_server(self) -> None:
        session = _FakeSession(scalar=None)
        send_mock = AsyncMock()
        with (
            patch(_DB, _session_cm(session)),
            patch.object(device_service, "_send_server_remove", send_mock),
        ):
            result = await device_service.deregister_device_server_for_integration(
                "int-x", notify_device=True
            )
        assert result is False
        send_mock.assert_not_awaited()
        assert session.deleted == []

    async def test_deletes_row_and_notifies_device(self, sqlite_session) -> None:
        # Two servers, different integration_id: the query must match int-1 by id.
        async with sqlite_session() as s:
            s.add(_server("dev1", "fs", "int-1"))
            s.add(_server("dev1", "other", "int-2"))
            await s.commit()
        send_mock = AsyncMock()
        with patch.object(device_service, "_send_server_remove", send_mock):
            result = await device_service.deregister_device_server_for_integration(
                "int-1", notify_device=True
            )
        assert result is True
        # Notifies the daemon by the row's own device_id/server_key, not the id it
        # was looked up by; a wrong predicate would pick int-2 (-> "other") or raise.
        send_mock.assert_awaited_once_with("dev1", "fs")
        async with sqlite_session() as s:
            remaining = (await s.execute(select(DeviceMCPServer.integration_id))).scalars().all()
        assert remaining == ["int-2"]


class TestReconcileDeviceServers:
    async def test_prunes_only_dropped_servers(self) -> None:
        keep = SimpleNamespace(server_key="keep")
        drop = SimpleNamespace(server_key="drop")
        list_mock = AsyncMock(return_value={"dev1": [keep, drop]})
        dereg_mock = AsyncMock()
        with (
            patch.object(device_service, "list_device_servers", list_mock),
            patch.object(device_service, "deregister_device_server", dereg_mock),
        ):
            async with captured_wide_event() as event:
                await device_service.reconcile_device_servers("u1", "dev1", ["keep"])
        # Servers are looked up for THIS device (kills the (None) arg mutant).
        list_mock.assert_awaited_once_with(["dev1"])
        # Only the server the daemon no longer reports is pruned, without notifying
        # the device (it already dropped it).
        dereg_mock.assert_awaited_once_with("u1", "dev1", "drop", notify_device=False)
        assert event["device"] == {"operation": "reconcile_servers", "device_id": "dev1"}
        assert event["pruned"] == 1

    async def test_no_op_when_device_absent_from_lookup(self) -> None:
        # The device isn't in the returned map; the `.get(device_id, [])` default
        # must be an empty list — dropping it or defaulting to None would iterate
        # None and raise.
        dereg_mock = AsyncMock()
        with (
            patch.object(device_service, "list_device_servers", AsyncMock(return_value={})),
            patch.object(device_service, "deregister_device_server", dereg_mock),
        ):
            await device_service.reconcile_device_servers("u1", "dev1", ["keep"])
        dereg_mock.assert_not_awaited()

    async def test_no_op_when_nothing_dropped(self) -> None:
        keep = SimpleNamespace(server_key="keep")
        dereg_mock = AsyncMock()
        with (
            patch.object(
                device_service, "list_device_servers", AsyncMock(return_value={"dev1": [keep]})
            ),
            patch.object(device_service, "deregister_device_server", dereg_mock),
        ):
            async with captured_wide_event() as event:
                await device_service.reconcile_device_servers("u1", "dev1", ["keep"])
        dereg_mock.assert_not_awaited()
        # Nothing stale -> no reconcile event fields emitted.
        assert "pruned" not in event
        assert "device" not in event


class TestRecordDeviceServerSync:
    async def test_noop_when_server_missing(self) -> None:
        session = _FakeSession(scalar=None)
        with patch(_DB, _session_cm(session)):
            await device_service.record_device_server_sync("int-x")
        assert session.commits == 0

    async def test_records_success(self, sqlite_session) -> None:
        # Decoy (int-2) must stay ERROR: the query stamps only the int-1 row.
        async with sqlite_session() as s:
            s.add(
                _server("dev1", "fs", "int-1", status=DeviceServerStatus.ERROR, error_message="old")
            )
            s.add(_server("dev1", "o", "int-2", status=DeviceServerStatus.ERROR))
            await s.commit()
        await device_service.record_device_server_sync("int-1")
        async with sqlite_session() as s:
            rows = {
                r.integration_id: r for r in (await s.execute(select(DeviceMCPServer))).scalars()
            }
        assert rows["int-1"].status == DeviceServerStatus.CONNECTED
        assert rows["int-1"].error_message is None
        assert isinstance(rows["int-1"].tools_synced_at, datetime)
        assert rows["int-2"].status == DeviceServerStatus.ERROR  # untouched by the predicate

    async def test_success_stamp_is_timezone_aware_utc(self, sqlite_session) -> None:
        # SQLite doesn't round-trip tzinfo, so spy on the clock instead: now() must be
        # called with UTC, since Postgres stores what it's given and a naive stamp breaks
        # every timezone-aware comparison downstream.
        seen: list[object] = []
        real_datetime = datetime

        class SpyDateTime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                seen.append(tz)
                return real_datetime.now(tz)

        async with sqlite_session() as s:
            s.add(_server("dev1", "fs", "int-1", status=DeviceServerStatus.ERROR))
            await s.commit()
        with patch.object(device_service, "datetime", SpyDateTime):
            await device_service.record_device_server_sync("int-1")
        assert seen == [UTC]

    async def test_records_error_and_truncates_to_2000(self, sqlite_session) -> None:
        async with sqlite_session() as s:
            s.add(_server("dev1", "fs", "int-1", status=DeviceServerStatus.CONNECTED))
            await s.commit()
        await device_service.record_device_server_sync("int-1", error="x" * 3000)
        async with sqlite_session() as s:
            row = (
                await s.execute(
                    select(DeviceMCPServer).where(DeviceMCPServer.integration_id == "int-1")
                )
            ).scalar_one()
        assert row.status == DeviceServerStatus.ERROR
        assert row.error_message == "x" * 2000
        assert len(row.error_message) == 2000
        # The success-only stamp is untouched on the error path.
        assert row.tools_synced_at is None


class TestCreateDeviceCapQueries:
    async def _seed(self, s, rows: list[Device]) -> None:
        for row in rows:
            s.add(row)
        await s.commit()

    def _device(
        self, device_id: str, user_id: str, status: DeviceStatus = DeviceStatus.ACTIVE
    ) -> Device:
        return Device(
            id=device_id,
            user_id=user_id,
            name=device_id,
            refresh_token_hash=f"hash-{device_id}",
            status=status,
        )

    async def test_cap_counts_only_this_users_active_devices(self, sqlite_session) -> None:
        # 20 ACTIVE for someone else + a full cap's worth of REVOKED decoys for self: the
        # cap must see neither. A dropped user_id predicate counts strangers; a dropped
        # ACTIVE predicate counts the revoked rows — both wrongly reject this user.
        async with sqlite_session() as s:
            await self._seed(
                s,
                [self._device(f"other-{n}", "user-b") for n in range(MAX_ACTIVE_DEVICES_PER_USER)]
                + [
                    self._device(f"mine-off-{n}", "user-a", DeviceStatus.REVOKED)
                    for n in range(MAX_ACTIVE_DEVICES_PER_USER)
                ],
            )
        device_id, refresh_token = await device_service.self_pair_device(
            "user-a", "Mine", "macos", "desktop", None
        )
        assert device_id
        # And the minted credential is the stored hash (same-row write check).
        from app.services.device.device_auth import hash_refresh_token

        async with sqlite_session() as s:
            row = (await s.execute(select(Device).where(Device.id == device_id))).scalar_one()
        assert hash_refresh_token(refresh_token) == row.refresh_token_hash
        assert row.status == DeviceStatus.ACTIVE

    async def test_cap_fires_at_exactly_max_active(self, sqlite_session) -> None:
        # Inverted predicates (!=) count the complement (zero here) and would
        # let a 21st device through — the boundary must reject.
        from app.constants.device_bridge import MAX_ACTIVE_DEVICES_PER_USER

        async with sqlite_session() as s:
            await self._seed(
                s, [self._device(f"mine-{n}", "user-a") for n in range(MAX_ACTIVE_DEVICES_PER_USER)]
            )
        with pytest.raises(AppError) as exc:
            await device_service.self_pair_device("user-a", "Extra", "macos", "desktop", None)
        assert exc.value.status_code == 409


class TestDeregisterScopesToDevice:
    async def test_drops_only_this_devices_row(self, sqlite_session) -> None:
        # Same server_key on two devices: dropping the device_id predicate
        # would delete the stranger's row too.
        delete_mock = AsyncMock()
        remove_mock = AsyncMock()
        invalidate_mock = AsyncMock()
        async with sqlite_session() as s:
            s.add(_server("dev1", "fs", "int-1"))
            s.add(_server("dev2", "fs", "int-2"))
            await s.commit()
        with (
            patch.object(device_service.integration_repository, "delete", delete_mock),
            patch.object(device_service, "remove_user_integration", remove_mock),
            patch.object(device_service, "invalidate_user_integration_caches", invalidate_mock),
        ):
            assert (
                await device_service.deregister_device_server(
                    "u1", "dev1", "fs", notify_device=False
                )
                is True
            )
        async with sqlite_session() as s:
            remaining = (await s.execute(select(DeviceMCPServer.integration_id))).scalars().all()
        assert remaining == ["int-2"]
        delete_mock.assert_awaited_once_with("int-1")

    def _redis(self, claimed: bool = True):
        cache = Mock()
        cache.client.set = AsyncMock(return_value=claimed)
        return cache

    async def test_enqueues_warm_job_with_args(self) -> None:
        pool = object()
        enqueue_mock = AsyncMock()
        rpm = Mock()
        rpm.get_pool = AsyncMock(return_value=pool)
        cache = self._redis()
        with (
            patch.object(device_service, "RedisPoolManager", rpm),
            patch.object(device_service, "enqueue_worker_job", enqueue_mock),
            patch.object(device_service, "redis_cache", cache),
        ):
            await device_service.enqueue_device_server_warmup("dev1", ["fs"])
        work = hashlib.sha256(b"fs").hexdigest()
        enqueue_mock.assert_awaited_once_with(
            pool,
            "warm_device_servers",
            "dev1",
            ["fs"],
            _job_id=f"device-warmup:dev1:{work}",
        )
        # The coalesce marker carries the identical work key with the exact
        # SETNX shape — a dropped nx/ex, a blanked arg, or a reformatted key
        # all silently disable burst collapsing.
        cache.client.set.assert_awaited_once_with(f"device:warmup:dev1:{work}", "1", nx=True, ex=60)

    async def test_defaults_server_keys_to_none(self) -> None:
        pool = object()
        enqueue_mock = AsyncMock()
        rpm = Mock()
        rpm.get_pool = AsyncMock(return_value=pool)
        with (
            patch.object(device_service, "RedisPoolManager", rpm),
            patch.object(device_service, "enqueue_worker_job", enqueue_mock),
            patch.object(device_service, "redis_cache", self._redis()),
        ):
            await device_service.enqueue_device_server_warmup("dev1")
        work = hashlib.sha256(b"all").hexdigest()
        enqueue_mock.assert_awaited_once_with(
            pool, "warm_device_servers", "dev1", None, _job_id=f"device-warmup:dev1:{work}"
        )

    async def test_burst_shares_one_job_id_regardless_of_key_order(self) -> None:
        # Registration storms enqueue the same set repeatedly — one deterministic id lets
        # ARQ collapse the burst instead of running overlapping jobs. The id pins the exact
        # scope hash: a changed joiner/sort would fork identical bursts into distinct jobs.
        pool = object()
        enqueue_mock = AsyncMock()
        rpm = Mock()
        rpm.get_pool = AsyncMock(return_value=pool)
        with (
            patch.object(device_service, "RedisPoolManager", rpm),
            patch.object(device_service, "enqueue_worker_job", enqueue_mock),
            patch.object(device_service, "redis_cache", self._redis()),
        ):
            await device_service.enqueue_device_server_warmup("dev1", ["b", "a"])
            await device_service.enqueue_device_server_warmup("dev1", ["a", "b"])
        ids = {c.kwargs["_job_id"] for c in enqueue_mock.await_args_list}
        assert ids == {f"device-warmup:dev1:{hashlib.sha256(b'a,b').hexdigest()}"}

    async def test_repeat_within_window_skips_enqueue(self) -> None:
        # The job record is freed on completion (keep_result=0), so spaced
        # repeats are coalesced by the SETNX marker, not the job id.
        enqueue_mock = AsyncMock()
        rpm = Mock()
        with (
            patch.object(device_service, "RedisPoolManager", rpm),
            patch.object(device_service, "enqueue_worker_job", enqueue_mock),
            patch.object(device_service, "redis_cache", self._redis(claimed=False)),
        ):
            await device_service.enqueue_device_server_warmup("dev1", ["fs"])
        enqueue_mock.assert_not_awaited()
        rpm.get_pool.assert_not_called()

    async def test_scoped_and_full_warmups_do_not_coalesce(self) -> None:
        # Different work sets are different markers: a registration's scoped
        # warmup must not be swallowed by a recent full-device warmup.
        enqueue_mock = AsyncMock()
        rpm = Mock()
        rpm.get_pool = AsyncMock(return_value=object())
        with (
            patch.object(device_service, "RedisPoolManager", rpm),
            patch.object(device_service, "enqueue_worker_job", enqueue_mock),
            patch.object(device_service, "redis_cache", self._redis()),
        ):
            await device_service.enqueue_device_server_warmup("dev1", ["fs"])
            await device_service.enqueue_device_server_warmup("dev1")
        assert enqueue_mock.await_count == 2

    async def test_empty_scope_is_not_the_full_warmup(self) -> None:
        # [] warms nothing; None warms everything. Sharing one marker would let
        # a no-op suppress a real full warmup (or vice versa).
        enqueue_mock = AsyncMock()
        rpm = Mock()
        rpm.get_pool = AsyncMock(return_value=object())
        with (
            patch.object(device_service, "RedisPoolManager", rpm),
            patch.object(device_service, "enqueue_worker_job", enqueue_mock),
            patch.object(device_service, "redis_cache", self._redis()),
        ):
            await device_service.enqueue_device_server_warmup("dev1", [])
            await device_service.enqueue_device_server_warmup("dev1")
        assert enqueue_mock.await_count == 2

    async def test_redis_outage_propagates_to_best_effort_caller(self) -> None:
        # Callers treat enqueue as best-effort (endpoint try/except) — an
        # outage must raise here, never silently skip the warmup.
        cache = Mock()
        cache.client.set = AsyncMock(side_effect=ConnectionError("redis down"))
        with (
            patch.object(device_service, "redis_cache", cache),
            pytest.raises(ConnectionError, match="redis down"),
        ):
            await device_service.enqueue_device_server_warmup("dev1", ["fs"])


class TestTeardownRevokedDevice:
    async def test_drops_integrations_clears_rows_and_revokes(self, sqlite_session) -> None:
        # Servers on two devices: the DELETE must clear ONLY the revoked device's
        # rows. where(None) deletes all; != deletes the other device's — both leave
        # the wrong survivor.
        async with sqlite_session() as s:
            s.add(_server("dev1", "a", "int-a"))
            s.add(_server("dev2", "b", "int-b"))
            await s.commit()
        delete_mock = AsyncMock()
        remove_mock = AsyncMock()
        revoke_mock = AsyncMock()
        with (
            patch.object(device_service.integration_repository, "delete", delete_mock),
            patch.object(device_service, "remove_user_integration", remove_mock),
            patch.object(device_service, "request_revoke", revoke_mock),
        ):
            await device_service._teardown_revoked_device("u1", "dev1", ["int-a"])
        # Every integration passed is dropped (doc + user link), in order.
        assert [c.args[0] for c in delete_mock.await_args_list] == ["int-a"]
        assert [c.args for c in remove_mock.await_args_list] == [("u1", "int-a")]
        # Only dev1's server rows are cleared; dev2's remain. Revoke is fanned out.
        async with sqlite_session() as s:
            remaining = (await s.execute(select(DeviceMCPServer.device_id))).scalars().all()
        assert remaining == ["dev2"]
        revoke_mock.assert_awaited_once_with("dev1")
