"""Cross-replica sandbox acquisition, against real Redis + real Mongo.

The multi-instance invariant the sandbox pool exists for: N replicas acquiring a
sandbox for the SAME user must end up with ONE E2B sandbox, not N. A replica's
in-process pool cache — and its in-process ``asyncio.Lock`` — are private to its
process, so a second replica arrives cold and has only two shared things to
coordinate through: the Redis lease and the Mongo record. If either fails to do
its job, both replicas run ``_create_fresh_sandbox`` and the user gets a second
sandbox: wasted spend, an orphaned box no one pauses, and a split workspace.

Two replicas are simulated faithfully by giving each acquire its OWN
``SandboxPool`` (via a per-task contextvar), so the only coordination they share
is Redis — exactly as two separate processes would. Using the module singleton
instead would let its in-process ``asyncio.Lock`` serialize them, masking a
broken Redis lease.

The cold private cache is simulated by stubbing ``_reuse_cached_entry`` to None
(a replica never sees another replica's warm entry). Everything E2B (create /
resume), the JuiceFS host writes (subtree seed, artifact watcher), the creation
rate-limit and the idle-pause scheduler are the external boundary and are
stubbed. What stays real is the whole coordination under test: the distributed
lock in ``acquire_sandbox`` and the get_for_user → create-or-resume →
record_acquisition decision in ``_acquire_or_create``.
"""

from __future__ import annotations

import asyncio
import contextvars
from unittest.mock import AsyncMock, patch

import pytest

from app.db.repositories.e2b_sandboxes import e2b_sandbox_repository
from app.services.sandbox.lifecycle import acquire_sandbox
from app.services.sandbox.pool import SandboxPool, get_sandbox_pool

USER = "acquire-user-one-sandbox"

# Each replica task binds its own pool here; lifecycle.get_sandbox_pool is
# redirected to read it, so two concurrent acquires do not share an in-process
# lock or cache — only Redis and Mongo.
_replica_pool: contextvars.ContextVar[SandboxPool | None] = contextvars.ContextVar(
    "replica_pool", default=None
)


def _pool_for_replica() -> SandboxPool:
    return _replica_pool.get() or get_sandbox_pool()


class FakeSandbox:
    """Stands in for an E2B AsyncSandbox; only its id is read downstream."""

    def __init__(self, sandbox_id: str) -> None:
        self.sandbox_id = sandbox_id


@pytest.fixture
async def clean_doc(mongo_db):
    """No pre-existing sandbox row for this user, and none left behind."""
    await mongo_db["e2b_sandboxes"].delete_many({"user_id": USER})
    yield
    await mongo_db["e2b_sandboxes"].delete_many({"user_id": USER})


@pytest.fixture
def boundary(monkeypatch):
    """Stub every external edge; return the create/resume call counters.

    The create stub sleeps briefly so the first replica is still inside the
    critical section when the second contends — that overlap is exactly the
    window a broken lock would let both through.
    """
    counters = {"create": 0, "resume": 0}

    async def fake_create(user_id: str, shard_id: int) -> FakeSandbox:
        counters["create"] += 1
        await asyncio.sleep(0.3)  # a cold E2B create is not instant
        return FakeSandbox(f"sbx-created-{counters['create']}")

    async def fake_resume(doc, mount_env) -> FakeSandbox:
        counters["resume"] += 1
        return FakeSandbox(doc.sandbox_id)

    p = "app.services.sandbox.lifecycle."
    monkeypatch.setattr(f"{p}get_sandbox_pool", _pool_for_replica)
    monkeypatch.setattr(f"{p}_reuse_cached_entry", AsyncMock(return_value=None))
    monkeypatch.setattr(f"{p}_create_fresh_sandbox", fake_create)
    monkeypatch.setattr(f"{p}_resume_existing_sandbox", fake_resume)
    monkeypatch.setattr(f"{p}_write_canary", AsyncMock(return_value="canary-ts"))
    monkeypatch.setattr(f"{p}_seed_user_subtrees", AsyncMock())
    monkeypatch.setattr(f"{p}_enforce_creation_limit", AsyncMock())
    monkeypatch.setattr(f"{p}_ensure_watcher", AsyncMock())
    monkeypatch.setattr(f"{p}_schedule_pause", lambda user_id, entry: None)
    return counters


async def _acquire_as_own_replica(collected: list[str | None]) -> None:
    """Run one acquire as a distinct replica: its own pool, shared Redis/Mongo."""
    _replica_pool.set(SandboxPool())
    async with acquire_sandbox(USER) as sbx:
        collected.append(sbx.sandbox_id)


@pytest.mark.asyncio
async def test_two_replicas_create_one_sandbox(real_redis, mongo_db, clean_doc, boundary) -> None:
    """Concurrent acquire from two replicas → one create, one resume, same id."""
    ids: list[str | None] = []

    await asyncio.gather(_acquire_as_own_replica(ids), _acquire_as_own_replica(ids))

    assert boundary["create"] == 1, (
        "each replica created its own sandbox — the Redis lock did not serialize them"
    )
    assert boundary["resume"] == 1, (
        "the second replica did not reuse the first's sandbox from Mongo"
    )
    assert ids[0] == ids[1], "the two replicas ended up on different sandboxes"

    doc = await e2b_sandbox_repository.get_for_user(USER)
    assert doc is not None and doc.sandbox_id == ids[0]


@pytest.mark.asyncio
async def test_a_later_replica_resumes_rather_than_recreates(
    real_redis, mongo_db, clean_doc, boundary
) -> None:
    """A replica arriving after the sandbox exists must resume, never create again.

    The sequential half — a fresh replica with a cold cache, long after the
    create — isolating the Mongo handoff from any lock-timing luck.
    """
    first: list[str | None] = []
    await _acquire_as_own_replica(first)
    assert boundary["create"] == 1

    second: list[str | None] = []
    await _acquire_as_own_replica(second)

    assert boundary["create"] == 1, "the later replica created a new sandbox instead of resuming"
    assert boundary["resume"] == 1
    assert second[0] == first[0]


@pytest.mark.asyncio
async def test_the_lock_is_released_after_a_failed_acquire(
    real_redis, mongo_db, clean_doc, boundary
) -> None:
    """A crashing acquire must not wedge the user's lock for the next replica.

    If the lease leaked on the failure path, the retry below would block until
    the max-hold cap rather than proceeding immediately.
    """
    seed: list[str | None] = []
    await _acquire_as_own_replica(seed)  # records the doc

    async def failing_resume(doc, mount_env):
        raise RuntimeError("boom mid-acquire")

    with patch(
        "app.services.sandbox.lifecycle._resume_existing_sandbox", side_effect=failing_resume
    ):
        with pytest.raises(RuntimeError, match="boom mid-acquire"):
            await _acquire_as_own_replica([])

    retry: list[str | None] = []
    await asyncio.wait_for(_acquire_as_own_replica(retry), timeout=5)
    assert retry[0] is not None
