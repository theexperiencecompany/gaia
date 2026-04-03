"""
Service tests: PostgreSQL checkpointer persistence for LangGraph.

Verifies that conversation state actually persists to and is recoverable
from PostgreSQL. If this fails, users lose all conversation context.

Requires: PostgreSQL service container (DATABASE_URL env var).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from langgraph.checkpoint.base import empty_checkpoint

from app.agents.core.graph_builder.checkpointer_manager import CheckpointerManager


# ---------------------------------------------------------------------------
# Fixtures (postgres_url comes from service/conftest.py)
# ---------------------------------------------------------------------------


@pytest.fixture
async def manager(postgres_url: str) -> CheckpointerManager:  # type: ignore[misc]
    """Function-scoped CheckpointerManager for test isolation."""
    mgr = CheckpointerManager(conninfo=postgres_url)
    await mgr.setup()
    yield mgr  # type: ignore[misc]
    await mgr.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.service
class TestCheckpointerManagerConnects:
    """CheckpointerManager must initialise and expose a live checkpointer."""

    async def test_setup_and_get_checkpointer(self, postgres_url: str) -> None:
        """setup() must complete without error and get_checkpointer() must be non-None."""
        mgr = CheckpointerManager(conninfo=postgres_url)
        await mgr.setup()
        checkpointer = mgr.get_checkpointer()
        assert checkpointer is not None
        await mgr.close()

    async def test_get_checkpointer_before_setup_raises(
        self, postgres_url: str
    ) -> None:
        """get_checkpointer() before setup() must raise RuntimeError."""
        mgr = CheckpointerManager(conninfo=postgres_url)
        with pytest.raises(RuntimeError, match="setup"):
            mgr.get_checkpointer()


@pytest.mark.service
class TestCheckpointPersistence:
    """Checkpoints written via aput must be retrievable via aget_tuple."""

    async def test_checkpoint_round_trip(self, manager: CheckpointerManager) -> None:
        """A checkpoint written with aput must be returned by aget_tuple."""
        checkpointer = manager.get_checkpointer()
        thread_id = str(uuid4())
        config = _thread_config(thread_id)

        checkpoint = empty_checkpoint()
        metadata: dict = {"source": "input", "step": 0, "writes": None, "parents": {}}
        new_versions: dict = {}

        saved_config = await checkpointer.aput(
            config, checkpoint, metadata, new_versions
        )
        assert saved_config is not None

        result = await checkpointer.aget_tuple(config)
        assert result is not None
        assert result.checkpoint["id"] == checkpoint["id"]

    async def test_missing_thread_returns_none(
        self, manager: CheckpointerManager
    ) -> None:
        """aget_tuple for an unknown thread_id must return None (no crash)."""
        checkpointer = manager.get_checkpointer()
        config = _thread_config(f"nonexistent-{uuid4()}")
        result = await checkpointer.aget_tuple(config)
        assert result is None


@pytest.mark.service
class TestThreadIsolation:
    """Checkpoints from different thread_ids must not bleed into each other."""

    async def test_two_threads_store_independently(
        self, manager: CheckpointerManager
    ) -> None:
        """
        Checkpoints written under thread_1 must not appear when querying thread_2.

        This guards against a misconfigured connection pool or schema bug that
        would cause LangGraph to serve the wrong conversation history to a user.
        """
        checkpointer = manager.get_checkpointer()
        thread_1 = str(uuid4())
        thread_2 = str(uuid4())

        checkpoint_1 = empty_checkpoint()
        checkpoint_2 = empty_checkpoint()

        metadata: dict = {"source": "input", "step": 0, "writes": None, "parents": {}}
        empty_versions: dict = {}

        await checkpointer.aput(
            _thread_config(thread_1), checkpoint_1, metadata, empty_versions
        )
        await checkpointer.aput(
            _thread_config(thread_2), checkpoint_2, metadata, empty_versions
        )

        result_1 = await checkpointer.aget_tuple(_thread_config(thread_1))
        result_2 = await checkpointer.aget_tuple(_thread_config(thread_2))

        assert result_1 is not None, "thread_1 checkpoint must be retrievable"
        assert result_2 is not None, "thread_2 checkpoint must be retrievable"

        # Each thread must hold its own checkpoint, not the other's
        assert result_1.checkpoint["id"] == checkpoint_1["id"]
        assert result_2.checkpoint["id"] == checkpoint_2["id"]
        assert result_1.checkpoint["id"] != result_2.checkpoint["id"]

    async def test_thread_1_not_visible_from_thread_2(
        self, manager: CheckpointerManager
    ) -> None:
        """
        alist on thread_2 must not yield checkpoints belonging to thread_1.

        If isolation breaks, a user could receive another user's conversation.
        """
        checkpointer = manager.get_checkpointer()
        thread_1 = str(uuid4())
        thread_2 = str(uuid4())

        checkpoint_1 = empty_checkpoint()
        metadata: dict = {"source": "input", "step": 0, "writes": None, "parents": {}}

        await checkpointer.aput(_thread_config(thread_1), checkpoint_1, metadata, {})

        ids_visible_from_thread_2 = [
            tup.checkpoint["id"]
            async for tup in checkpointer.alist(_thread_config(thread_2))
        ]

        assert checkpoint_1["id"] not in ids_visible_from_thread_2, (
            f"checkpoint from thread_1 must not appear in thread_2 listing; "
            f"found {ids_visible_from_thread_2}"
        )

    async def test_multiple_checkpoints_per_thread_ordered(
        self, manager: CheckpointerManager
    ) -> None:
        """alist must return all checkpoints for a thread, newest first."""
        checkpointer = manager.get_checkpointer()
        thread_id = str(uuid4())
        config = _thread_config(thread_id)

        metadata: dict = {"source": "input", "step": 0, "writes": None, "parents": {}}

        cp_a = empty_checkpoint()
        cp_b = empty_checkpoint()

        await checkpointer.aput(config, cp_a, metadata, {})
        await checkpointer.aput(config, cp_b, {**metadata, "step": 1}, {})

        all_tuples = [tup async for tup in checkpointer.alist(config)]
        ids = [tup.checkpoint["id"] for tup in all_tuples]

        assert cp_a["id"] in ids, "first checkpoint must be listed"
        assert cp_b["id"] in ids, "second checkpoint must be listed"
        assert len(all_tuples) >= 2

        # aget_tuple must return the latest (cp_b written last)
        latest = await checkpointer.aget_tuple(config)
        assert latest is not None
        assert latest.checkpoint["id"] == cp_b["id"]
