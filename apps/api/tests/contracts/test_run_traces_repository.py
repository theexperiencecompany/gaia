"""Contract tests for the run-trace repositories, on real Mongo.

Runs, calls and payloads are three collections; the fixture routes each repository to its
own throwaway collection on the contract database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest

from app.db.repositories.run_traces import (
    CallPayloadsRepository,
    RunCallsRepository,
    RunsRepository,
)
from app.models.run_trace_models import (
    CallEffect,
    CallPayloadDocument,
    CallStatus,
    RunCallDocument,
    RunDocument,
    RunState,
    RunUpdate,
)

USER = "6812f0b3c9a14e2b7d5a91cc"
OTHER = "6812f0b3c9a14e2b7d5a91cd"
T0 = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
async def routed(
    raw_collection: AsyncIOMotorCollection, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[None]:
    database = raw_collection.database
    suffix = raw_collection.name
    created: list[AsyncIOMotorCollection] = []

    def accessor(name: str) -> AsyncIOMotorCollection:
        collection = database[f"{name}_{suffix}"]
        created.append(collection)
        return collection

    monkeypatch.setattr("app.db.repositories.base.get_async_collection", accessor)
    yield
    for collection in created:
        await collection.drop()


def _run(run_id: str = "r1", **overrides: object) -> RunDocument:
    fields: dict[str, object] = {
        "user_id": USER,
        "run_id": run_id,
        "conversation_id": "conv-1",
        "state": RunState.RUNNING,
        "started_at": T0,
        "last_activity_at": T0,
    }
    fields.update(overrides)
    return RunDocument.model_validate(fields)


def _call(
    call_id: str = "c1", run_id: str = "r1", at: datetime = T0, **overrides: object
) -> RunCallDocument:
    fields: dict[str, object] = {
        "user_id": USER,
        "run_id": run_id,
        "call_id": call_id,
        "tool_name": "gmail_search",
        "effect": CallEffect.READ,
        "status": CallStatus.OK,
        "started_at": at,
        "finished_at": at + timedelta(seconds=1),
        "summary": "query=lease",
        "payload_ref": "p1",
    }
    fields.update(overrides)
    return RunCallDocument.model_validate(fields)


@pytest.mark.usefixtures("routed")
class TestRunsRepository:
    async def test_opening_a_new_run_stores_it_running_with_a_ttl_anchor(self) -> None:
        repo = RunsRepository()
        before = datetime.now(UTC)

        await repo.open_run(_run(todo_id="todo-1"))

        stored = await repo.get("r1", user_id=USER)
        assert stored is not None
        assert (stored.state, stored.todo_id, stored.conversation_id) == (
            RunState.RUNNING,
            "todo-1",
            "conv-1",
        )
        assert stored.created_at is not None
        assert stored.created_at >= before.replace(microsecond=0)

    async def test_a_heartbeat_keeps_the_state_and_moves_only_the_activity_time(self) -> None:
        repo = RunsRepository()
        await repo.open_run(_run())
        await repo.update("r1", user_id=USER, update=RunUpdate(state=RunState.PAUSED))

        await repo.open_run(_run(last_activity_at=T0 + timedelta(minutes=5)))

        stored = await repo.get("r1", user_id=USER)
        assert stored is not None
        assert (stored.state, stored.last_activity_at) == (
            RunState.PAUSED,
            T0 + timedelta(minutes=5),
        )

    async def test_reopening_with_a_state_runs_the_run_again_and_clears_its_finish(self) -> None:
        repo = RunsRepository()
        await repo.open_run(_run())
        await repo.update(
            "r1", user_id=USER, update=RunUpdate(state=RunState.FAILED, finished_at=T0)
        )

        await repo.open_run(_run(), state=RunState.RUNNING)

        stored = await repo.get("r1", user_id=USER)
        assert stored is not None
        assert (stored.state, stored.finished_at) == (RunState.RUNNING, None)

    async def test_a_run_is_invisible_to_another_user(self) -> None:
        repo = RunsRepository()
        await repo.open_run(_run())

        assert await repo.get("r1", user_id=OTHER) is None
        assert await repo.list_for_user(OTHER) == []

    async def test_only_a_run_still_running_and_stale_is_abandoned_and_only_once(self) -> None:
        repo = RunsRepository()
        cutoff = T0 + timedelta(hours=1)
        await repo.open_run(_run("stale", last_activity_at=T0))
        await repo.open_run(_run("fresh", last_activity_at=T0 + timedelta(hours=2)))
        await repo.open_run(_run("paused", last_activity_at=T0))
        await repo.update("paused", user_id=USER, update=RunUpdate(state=RunState.PAUSED))

        stale = await repo.list_stale_running(cutoff, limit=10)
        first = await repo.abandon_if_stale("stale", USER, cutoff, at=cutoff)
        again = await repo.abandon_if_stale("stale", USER, cutoff, at=cutoff)

        assert [r.run_id for r in stale] == ["stale"]
        assert first is not None and (first.state, first.finished_at) == (
            RunState.ABANDONED,
            cutoff,
        )
        assert again is None
        assert await repo.abandon_if_stale("fresh", USER, cutoff, at=cutoff) is None


@pytest.mark.usefixtures("routed")
class TestRunCallsRepository:
    async def test_calls_finished_after_a_cutoff_are_the_ones_not_yet_logged(self) -> None:
        repo = RunCallsRepository()
        await repo.create(_call("a", at=T0))
        await repo.create(_call("b", at=T0 + timedelta(minutes=1)))

        everything = await repo.list_finished_after(USER, "r1", None)
        after_a = await repo.list_finished_after(USER, "r1", T0 + timedelta(seconds=1))

        assert [c.call_id for c in everything] == ["a", "b"]
        assert [c.call_id for c in after_a] == ["b"]


@pytest.mark.usefixtures("routed")
class TestCallPayloadsRepository:
    async def test_a_payload_round_trips_and_is_scoped_to_its_user(self) -> None:
        repo = CallPayloadsRepository()
        created = await repo.create(
            CallPayloadDocument(user_id=USER, input_json='{"q": 1}', output_text="out")
        )

        mine = await repo.get(created.id, user_id=USER)
        theirs = await repo.get(created.id, user_id=OTHER)

        assert mine is not None and (mine.input_json, mine.output_text, mine.truncated) == (
            '{"q": 1}',
            "out",
            False,
        )
        assert theirs is None
