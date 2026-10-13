"""Real-Postgres test for the per-user active-device cap in _create_device.

The cap COUNT query is "WHERE user_id == user_id AND status == ACTIVE". A unit
test with a fake session can't see those predicates — the fake returns a fixed
count regardless of the query. Only real Postgres proves that the count includes
*this* user's ACTIVE devices and excludes another user's devices and this user's
REVOKED ones. Seeding noise (a full cap of ACTIVE devices for user B, plus REVOKED
rows for user A) is what makes both predicates load-bearing: drop either one and
the first, should-succeed create already trips the cap.
"""

from __future__ import annotations

import uuid

import pytest

from app.constants.device_bridge import MAX_ACTIVE_DEVICES_PER_USER
from app.db.postgresql import get_db_session
from app.models.device import Device, DeviceStatus
from app.services.device.device_auth import hash_refresh_token
from app.services.device.device_service import _create_device
from app.utils.errors import AppError


async def _seed_devices(user_id: str, count: int, status: DeviceStatus) -> None:
    async with get_db_session() as session:
        for i in range(count):
            session.add(
                Device(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    name=f"{user_id}-{status.value}-{i}",
                    refresh_token_hash=hash_refresh_token(str(uuid.uuid4())),
                    status=status,
                )
            )
        await session.commit()


async def _active_count(user_id: str) -> int:
    from sqlalchemy import func, select

    async with get_db_session() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(Device)
                .where(Device.user_id == user_id, Device.status == DeviceStatus.ACTIVE)
            )
        ).scalar_one()


@pytest.mark.service
class TestDeviceCapRealPostgres:
    async def test_cap_counts_only_this_users_active_devices(
        self, clean_bridge_tables, mongo_db, real_redis
    ) -> None:
        user_a = f"cap-a-{uuid.uuid4()}"
        user_b = f"cap-b-{uuid.uuid4()}"

        # User A is one below the cap in ACTIVE devices, plus noise that must NOT
        # count: A's own REVOKED devices, and a FULL cap of ACTIVE devices for B.
        await _seed_devices(user_a, MAX_ACTIVE_DEVICES_PER_USER - 1, DeviceStatus.ACTIVE)
        await _seed_devices(user_a, 5, DeviceStatus.REVOKED)
        await _seed_devices(user_b, MAX_ACTIVE_DEVICES_PER_USER, DeviceStatus.ACTIVE)

        # At cap-1 the create succeeds — proving REVOKED and other-user rows are
        # excluded (if either predicate were dropped, the count would already be
        # >= cap here and this would raise).
        device_id, refresh_token = await _create_device(
            user_a, "Laptop", "macos", "1.0.0", client="desktop"
        )
        uuid.UUID(device_id)
        assert refresh_token
        assert await _active_count(user_a) == MAX_ACTIVE_DEVICES_PER_USER
        # B's independent full cap is untouched by A's create.
        assert await _active_count(user_b) == MAX_ACTIVE_DEVICES_PER_USER

        # Now A is exactly at the cap: the next create is rejected with 409.
        with pytest.raises(AppError) as exc:
            await _create_device(user_a, "Laptop 2", "macos", "1.0.0", client="desktop")
        assert exc.value.status_code == 409
        assert exc.value.message == "Device limit reached"
        # No extra row was inserted on the rejected create.
        assert await _active_count(user_a) == MAX_ACTIVE_DEVICES_PER_USER
