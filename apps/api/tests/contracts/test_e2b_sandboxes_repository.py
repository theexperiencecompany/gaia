"""Contract tests for E2bSandboxesRepository (global, one record per user)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

import pytest

from app.db.repositories.e2b_sandboxes import E2bSandboxesRepository


@pytest.fixture
def repo(raw_collection) -> E2bSandboxesRepository:
    return E2bSandboxesRepository()


def _now() -> datetime:
    return datetime.now(UTC)


async def _acquire(repo: E2bSandboxesRepository, user_id: str, *, when: datetime) -> None:
    await repo.record_acquisition(
        user_id=user_id,
        sandbox_id=f"sbx-{uuid.uuid4().hex}",
        template_id="tmpl-1",
        shard_id=0,
        workspace_version=1,
        last_canary_ts=when.isoformat(),
        timestamp=when,
    )


class TestE2bSandboxesRepository:
    async def test_record_acquisition_creates_active_record(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await _acquire(repo, user, when=_now())

        doc = await repo.get_for_user(user)
        assert doc is not None
        assert doc.state == "active"
        assert doc.total_invocations == 1
        assert doc.sandbox_id is not None
        assert doc.created_at is not None
        assert isinstance(doc.last_canary_ts, str)  # ISO string, not a BSON date

    async def test_second_acquisition_increments_and_preserves_created_at(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        first_time = _now()
        await _acquire(repo, user, when=first_time)
        created = (await repo.get_for_user(user)).created_at

        await _acquire(repo, user, when=_now())
        doc = await repo.get_for_user(user)
        assert doc.total_invocations == 2  # $inc bumped, not reset
        assert doc.created_at == created  # $setOnInsert did not overwrite it

    async def test_mark_paused_and_dead_and_touch(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await _acquire(repo, user, when=_now())

        await repo.mark_paused(user, timestamp=_now())
        paused = await repo.get_for_user(user)
        assert paused.state == "paused" and paused.paused_at is not None

        touched_at = _now()
        await repo.touch_last_used(user, timestamp=touched_at)
        assert (await repo.get_for_user(user)).state == "paused"  # touch leaves state

        await repo.mark_dead(user, timestamp=_now())
        assert (await repo.get_for_user(user)).state == "dead"

    async def test_find_idle_user_ids_filters_by_cutoff_and_state(self, repo):
        cutoff = _now() - timedelta(days=7)
        idle_user = f"u-{uuid.uuid4().hex}"
        fresh_user = f"u-{uuid.uuid4().hex}"
        dead_user = f"u-{uuid.uuid4().hex}"

        await _acquire(repo, idle_user, when=cutoff - timedelta(days=1))  # older than cutoff
        await _acquire(repo, fresh_user, when=_now())  # recent
        await _acquire(repo, dead_user, when=cutoff - timedelta(days=1))
        await repo.mark_dead(dead_user, timestamp=_now())  # already dead → excluded

        idle = set(await repo.find_idle_user_ids(cutoff=cutoff))
        assert idle_user in idle
        assert fresh_user not in idle  # too recent
        assert dead_user not in idle  # already dead
