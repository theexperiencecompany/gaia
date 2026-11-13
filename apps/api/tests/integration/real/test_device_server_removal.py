"""Service tests: device MCP server removal keeps Postgres + Mongo in sync.

A device server lives in three places — the Postgres bridge_device_mcp_servers
row (authoritative), the Mongo integrations doc, and the user_integrations
link. The bug these cover: removal used to touch only Mongo, leaving the Postgres
row behind (so the server kept showing in the Devices tab, and
_ensure_server_integration resurrected the Mongo doc from the surviving row).

These call the real device_service functions against real Postgres/Mongo/Redis
(no gaia bridge subprocess), seeding via the production register_device_server
so the writer under a delete is the real one, not a fixture's assumptions.
"""

from __future__ import annotations

from contextlib import suppress
import json

import pytest

from app.db.postgresql import get_db_session
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.models.device import Device, DeviceStatus
from app.services.device.bridge import down_channel
from app.services.device.device_service import (
    deregister_device_server,
    list_device_servers,
    reconcile_device_servers,
    register_device_server,
    revoke_device,
)
from app.services.integrations.custom_crud import delete_custom_integration


async def _seed_device(user_id: str, device_id: str) -> None:
    """Insert an active device row so registered servers satisfy the FK."""
    async with get_db_session() as session:
        session.add(
            Device(
                id=device_id,
                user_id=user_id,
                name="Test device",
                refresh_token_hash="0" * 64,
                status=DeviceStatus.ACTIVE,
            )
        )
        await session.commit()


async def _server_keys(device_id: str) -> set[str]:
    servers = (await list_device_servers([device_id])).get(device_id, [])
    return {s.server_key for s in servers}


@pytest.mark.service
class TestDeviceServerRemoval:
    async def test_deregister_removes_postgres_and_mongo(
        self, clean_bridge_tables, mongo_db, real_redis
    ):
        user_id, device_id = "u-dereg", "dev-dereg"
        await _seed_device(user_id, device_id)
        server = await register_device_server(user_id, device_id, "alpha", "Alpha")
        iid = server.integration_id

        # Registration wrote all three stores.
        assert await _server_keys(device_id) == {"alpha"}
        assert await integration_repository.get(iid) is not None
        assert await user_integration_repository.get_for_user(user_id, iid) is not None

        removed = await deregister_device_server(user_id, device_id, "alpha", notify_device=False)

        assert removed is True
        assert await _server_keys(device_id) == set()
        assert await integration_repository.get(iid) is None
        assert await user_integration_repository.get_for_user(user_id, iid) is None

    async def test_deregister_missing_server_is_a_noop(
        self, clean_bridge_tables, mongo_db, real_redis
    ):
        removed = await deregister_device_server("u-none", "dev-none", "ghost", notify_device=False)
        assert removed is False

    async def test_deregister_notifies_device_when_requested(
        self, clean_bridge_tables, mongo_db, real_redis
    ):
        user_id, device_id = "u-notify", "dev-notify"
        await _seed_device(user_id, device_id)
        await register_device_server(user_id, device_id, "beta", "Beta")

        pubsub = real_redis.pubsub()
        await pubsub.subscribe(down_channel(device_id))
        try:
            await deregister_device_server(user_id, device_id, "beta", notify_device=True)
            frame = None
            for _ in range(20):
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                if message is not None:
                    frame = json.loads(message["data"])
                    break
            assert frame == {"t": "server.remove", "key": "beta"}
        finally:
            with suppress(Exception):
                await pubsub.unsubscribe(down_channel(device_id))
                await pubsub.aclose()

    async def test_reconcile_prunes_only_dropped_servers(
        self, clean_bridge_tables, mongo_db, real_redis
    ):
        user_id, device_id = "u-recon", "dev-recon"
        await _seed_device(user_id, device_id)
        keep = await register_device_server(user_id, device_id, "keep", "Keep")
        drop = await register_device_server(user_id, device_id, "drop", "Drop")

        # The daemon reports only "keep" on connect.
        await reconcile_device_servers(user_id, device_id, ["keep"])

        assert await _server_keys(device_id) == {"keep"}
        assert await integration_repository.get(keep.integration_id) is not None
        assert await integration_repository.get(drop.integration_id) is None

    async def test_reconcile_empty_list_prunes_everything(
        self, clean_bridge_tables, mongo_db, real_redis
    ):
        user_id, device_id = "u-recon-empty", "dev-recon-empty"
        await _seed_device(user_id, device_id)
        await register_device_server(user_id, device_id, "one", "One")
        await register_device_server(user_id, device_id, "two", "Two")

        await reconcile_device_servers(user_id, device_id, [])

        assert await _server_keys(device_id) == set()

    async def test_delete_custom_integration_removes_the_postgres_row(
        self, clean_bridge_tables, mongo_db, real_redis
    ):
        # The reported bug: deleting a device integration from the integrations
        # page left the Postgres row, so the server kept showing in Devices.
        user_id, device_id = "u-delcustom", "dev-delcustom"
        await _seed_device(user_id, device_id)
        server = await register_device_server(user_id, device_id, "gamma", "Gamma")

        deleted = await delete_custom_integration(user_id, server.integration_id)

        assert deleted is True
        assert await _server_keys(device_id) == set()
        assert await integration_repository.get(server.integration_id) is None

    async def test_revoke_device_clears_its_server_rows(
        self, clean_bridge_tables, mongo_db, real_redis
    ):
        user_id, device_id = "u-revoke", "dev-revoke"
        await _seed_device(user_id, device_id)
        server = await register_device_server(user_id, device_id, "delta", "Delta")

        revoked = await revoke_device(user_id, device_id)

        assert revoked is True
        assert await _server_keys(device_id) == set()
        assert await integration_repository.get(server.integration_id) is None
