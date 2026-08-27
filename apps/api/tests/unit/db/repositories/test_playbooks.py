"""Hermetic unit tests for ``PlaybooksRepository``.

The real-Mongo proof lives in ``tests/contracts/test_playbooks_repository.py``;
this tier pins the exact shape of the writes the repository hands the driver —
that a first authoring is ONE atomic upsert rather than a read-then-insert two
concurrent authors can both pass, and that a run outcome lands only on the
playbook that was actually replayed. The driver is mocked at
``app.db.repositories.base.get_async_collection``, the single seam every read and
write in the base repository goes through.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from pymongo.errors import DuplicateKeyError
import pytest

from app.db.repositories.playbooks import PlaybooksRepository
from app.models.playbook_models import PlaybookDocument, PlaybookRunStatus

WORKFLOW_ID = "wf_1"
USER_ID = "user_1"
NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


def _doc(**overrides: Any) -> PlaybookDocument:
    data: dict[str, Any] = {
        "playbook_id": "pb_first",
        "workflow_id": WORKFLOW_ID,
        "user_id": USER_ID,
        "workflow_hash": "hash-1",
        "description": "first",
        "steps": [{"id": "one", "tool": "list_events", "args": {"calendar_id": "primary"}}],
        "synthesize": "s",
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return PlaybookDocument.model_validate(data)


def _raw(**overrides: Any) -> dict[str, Any]:
    raw = _doc(**overrides).model_dump(exclude={"id"})
    raw["_id"] = ObjectId()
    return raw


@pytest.fixture
def collection() -> Iterator[MagicMock]:
    mock = MagicMock()
    mock.find_one = AsyncMock(return_value=None)
    mock.find_one_and_update = AsyncMock(return_value=_raw())
    with patch("app.db.repositories.base.get_async_collection", return_value=mock):
        yield mock


@pytest.fixture
def repo() -> PlaybooksRepository:
    return PlaybooksRepository()


class TestUpsertForWorkflow:
    async def test_a_first_authoring_is_one_atomic_upsert_not_a_read_then_insert(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        stored = await repo.upsert_for_workflow(_doc())

        collection.find_one.assert_not_awaited()
        collection.insert_one.assert_not_called()
        collection.find_one_and_update.assert_awaited_once()
        filter_, update = collection.find_one_and_update.await_args.args
        assert filter_ == {"workflow_id": WORKFLOW_ID, "user_id": USER_ID}
        assert collection.find_one_and_update.await_args.kwargs["upsert"] is True
        assert update["$setOnInsert"] == {"playbook_id": "pb_first", "created_at": NOW}
        assert stored.playbook_id == "pb_first"

    async def test_a_rewrite_replaces_the_body_and_resets_the_outcome(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        await repo.upsert_for_workflow(_doc(description="second", workflow_hash="hash-2"))

        _filter, update = collection.find_one_and_update.await_args.args
        set_fields = update["$set"]
        assert set_fields["description"] == "second"
        assert set_fields["workflow_hash"] == "hash-2"
        assert set_fields["last_run_status"] is PlaybookRunStatus.NOT_RUN
        assert set_fields["last_run_reason"] is None
        assert set_fields["suspect_streak"] == 0
        assert set_fields["steps"][0]["tool"] == "list_events"
        # The identity is never part of the rewrite: a replay in flight keeps its id.
        assert "playbook_id" not in set_fields

    async def test_the_loser_of_a_concurrent_first_authoring_retries_onto_the_winner(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        collection.find_one_and_update = AsyncMock(
            side_effect=[DuplicateKeyError("E11000 duplicate key"), _raw(description="second")]
        )

        stored = await repo.upsert_for_workflow(_doc(description="second"))

        assert collection.find_one_and_update.await_count == 2
        assert stored.description == "second"


class TestRecordRunOutcome:
    async def test_with_the_replayed_id_the_write_is_scoped_to_that_playbook(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        await repo.record_run_outcome(
            WORKFLOW_ID, USER_ID, PlaybookRunStatus.FAILED, playbook_id="pb_first"
        )

        collection.find_one.assert_not_awaited()
        filter_, update = collection.find_one_and_update.await_args.args
        assert filter_ == {
            "playbook_id": "pb_first",
            "workflow_id": WORKFLOW_ID,
            "user_id": USER_ID,
        }
        assert update["$set"]["last_run_status"] is PlaybookRunStatus.FAILED

    async def test_a_replaced_playbook_records_nothing(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        collection.find_one_and_update = AsyncMock(return_value=None)

        outcome = await repo.record_run_outcome(
            WORKFLOW_ID, USER_ID, PlaybookRunStatus.SUCCESS, playbook_id="pb_stale"
        )

        assert outcome is None

    async def test_without_an_id_it_updates_whatever_the_workflow_has_in_one_write(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        await repo.record_run_outcome(WORKFLOW_ID, USER_ID, PlaybookRunStatus.SUCCESS)

        collection.find_one.assert_not_awaited()
        filter_, _update = collection.find_one_and_update.await_args.args
        assert filter_ == {"workflow_id": WORKFLOW_ID, "user_id": USER_ID}

    async def test_a_suspect_run_records_its_reason_and_grows_the_streak(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        await repo.record_run_outcome(
            WORKFLOW_ID, USER_ID, PlaybookRunStatus.SUSPECT, reason="list_events returned no items"
        )

        _filter, update = collection.find_one_and_update.await_args.args
        assert update["$set"]["last_run_status"] is PlaybookRunStatus.SUSPECT
        assert update["$set"]["last_run_reason"] == "list_events returned no items"
        assert update["$inc"] == {"suspect_streak": 1}
        assert "suspect_streak" not in update["$set"]

    async def test_a_success_clears_the_reason_and_resets_the_streak(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        await repo.record_run_outcome(
            WORKFLOW_ID, USER_ID, PlaybookRunStatus.SUCCESS, reason="ignored on success"
        )

        _filter, update = collection.find_one_and_update.await_args.args
        assert update["$set"]["last_run_status"] is PlaybookRunStatus.SUCCESS
        assert update["$set"]["last_run_reason"] is None
        assert update["$set"]["suspect_streak"] == 0
        assert "$inc" not in update

    async def test_a_failure_records_its_reason_and_leaves_the_streak_alone(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        await repo.record_run_outcome(
            WORKFLOW_ID, USER_ID, PlaybookRunStatus.FAILED, reason="stopped at step 2"
        )

        _filter, update = collection.find_one_and_update.await_args.args
        assert update["$set"]["last_run_status"] is PlaybookRunStatus.FAILED
        assert update["$set"]["last_run_reason"] == "stopped at step 2"
        assert "suspect_streak" not in update["$set"]
        assert "$inc" not in update
