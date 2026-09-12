"""``make_scheduler`` must serialize a user's syncs and coalesce bursts.

Two writes to one todo inside a single agent turn (edit canvas.md, then write
activity.md, each also appending log.md) schedule several fire-and-forget
syncs ~100 ms apart. Each sync fetched its own Mongo snapshot; with nothing
serializing them, the sync holding the older snapshot could finish last and
leave the disk projection stale, marker and all, until the next unrelated
write. Seen live on the dockered stack: activity.md empty on JuiceFS while
Mongo held the entry.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.services._vfs_scheduler import make_scheduler

_MOD = "app.services._vfs_scheduler"


@pytest.fixture
def mounted():
    with patch(f"{_MOD}._is_mounted", return_value=True):
        yield


@pytest.mark.unit
async def test_a_slower_older_sync_cannot_overwrite_a_newer_one(mounted) -> None:
    """Snapshot order must match completion order: the last sync to touch disk
    must be the one that saw the newest data."""
    snapshots = iter(["v1", "v2"])
    delays = iter([0.05, 0.0])  # v1 is slow, v2 is fast
    disk: list[str] = []

    async def sync(user_id: str) -> int:
        seen = next(snapshots)
        await asyncio.sleep(next(delays))
        disk.append(seen)
        return 1

    schedule = make_scheduler(sync, log_name="test")
    schedule("u1")
    await asyncio.sleep(0.01)  # v1 has taken its snapshot and is mid-flight
    schedule("u1")  # the second write landed after v1's snapshot
    await asyncio.sleep(0.2)

    assert disk == ["v1", "v2"]


@pytest.mark.unit
async def test_a_burst_runs_the_sync_at_most_twice(mounted) -> None:
    """One in flight plus one catch-up run; the rest of the burst coalesces."""
    runs = 0
    gate = asyncio.Event()

    async def sync(user_id: str) -> int:
        nonlocal runs
        runs += 1
        await gate.wait()
        return 0

    schedule = make_scheduler(sync, log_name="test")
    schedule("u1")
    await asyncio.sleep(0.01)  # the first sync is in flight, blocked on the gate
    for _ in range(5):
        schedule("u1")
    assert runs == 1
    gate.set()
    await asyncio.sleep(0.05)

    assert runs == 2


@pytest.mark.unit
async def test_schedules_before_the_first_snapshot_coalesce_into_one_run(mounted) -> None:
    """Writes that land before the sync fetches are already in its snapshot."""
    runs = 0

    async def sync(user_id: str) -> int:
        nonlocal runs
        runs += 1
        return 0

    schedule = make_scheduler(sync, log_name="test")
    for _ in range(4):
        schedule("u1")
    await asyncio.sleep(0.05)

    assert runs == 1


@pytest.mark.unit
async def test_users_do_not_serialize_each_other(mounted) -> None:
    started: list[str] = []
    gate = asyncio.Event()

    async def sync(user_id: str) -> int:
        started.append(user_id)
        await gate.wait()
        return 0

    schedule = make_scheduler(sync, log_name="test")
    schedule("u1")
    schedule("u2")
    await asyncio.sleep(0)

    assert sorted(started) == ["u1", "u2"]
    gate.set()
    await asyncio.sleep(0.01)


@pytest.mark.unit
async def test_a_failing_sync_does_not_wedge_the_user(mounted) -> None:
    calls = 0

    async def sync(user_id: str) -> int:
        nonlocal calls
        calls += 1
        raise RuntimeError("juicefs hiccup")

    schedule = make_scheduler(sync, log_name="test")
    schedule("u1")
    await asyncio.sleep(0.01)
    schedule("u1")
    await asyncio.sleep(0.01)

    assert calls == 2
