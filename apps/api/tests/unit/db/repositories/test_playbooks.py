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

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from pymongo.errors import DuplicateKeyError
import pytest

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories import playbooks as playbooks_module
from app.db.repositories.playbooks import PlaybooksRepository
from app.models.playbook_models import PlaybookDocument, PlaybookRunOutcome, PlaybookRunStatus

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


def _raw_update_spy(*outcomes: Any) -> tuple[Any, list[dict[str, Any]]]:
    """A stand-in for the base repository's raw-update seam, carrying its real
    signature so a dropped argument fails here rather than reaching the driver.

    The seam is where the cache scope and the upsert flag are decided; neither
    reaches ``find_one_and_update``, so they are only observable from this side.
    Each entry of ``outcomes`` is the next call's return value, or an exception
    to raise from it.
    """
    calls: list[dict[str, Any]] = []
    queued = list(outcomes)

    async def _apply_raw_update(
        _self: PlaybooksRepository,
        filter_: Mapping[str, object],
        update: Mapping[str, Mapping[str, object]],
        *,
        scope: str,
        upsert: bool = False,
        **rest: object,
    ) -> PlaybookDocument | None:
        calls.append(
            {
                "filter": dict(filter_),
                "update": update,
                "scope": scope,
                "upsert": upsert,
            }
        )
        outcome = queued.pop(0) if queued else _doc()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return _apply_raw_update, calls


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
        assert update["$setOnInsert"] == {
            "playbook_id": "pb_first",
            "created_at": NOW,
            "suspect_streak": 0,
        }
        assert update["$inc"] == {"revision": 1}
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
        # A rewrite is how a heal run answers a suspect replay, so the streak
        # survives it: a playbook that keeps coming back suspect is flapping,
        # and the limit must still be reachable.
        assert "suspect_streak" not in set_fields
        assert update["$setOnInsert"]["suspect_streak"] == 0
        assert set_fields["steps"][0]["tool"] == "list_events"
        # The identity is never part of the rewrite: a replay in flight keeps its id.
        assert "playbook_id" not in set_fields
        # The heal attempts counted runs spent on the body just replaced.
        assert set_fields["heal_attempts"] == 0
        # The id survives, so the revision is what tells a replay in flight
        # that the body it ran is no longer the body stored.
        assert update["$inc"] == {"revision": 1}
        assert "revision" not in set_fields

    async def test_the_written_body_is_the_whole_playbook_and_nothing_else(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        """A rewrite replaces the workflow's one record in place, so the ``$set``
        IS the new playbook. A field that goes missing here is silently kept from
        the body just thrown away; one that arrives as null erases it."""
        await repo.upsert_for_workflow(_doc())

        _filter, update = collection.find_one_and_update.await_args.args
        set_fields = dict(update["$set"])
        # Stamped by the base repository on every write, not by this method.
        assert isinstance(set_fields.pop("updated_at"), datetime)
        # The step bodies round-trip through the model; their own shape is the
        # playbook model's contract, not this repository's.
        assert [step["tool"] for step in set_fields.pop("steps")] == ["list_events"]
        assert set_fields == {
            "description": "first",
            "ask": {},
            "synthesize": "s",
            "workflow_hash": "hash-1",
            "last_run_status": PlaybookRunStatus.NOT_RUN,
            "last_run_reason": None,
            "heal_attempts": 0,
        }

    async def test_the_loser_of_a_concurrent_first_authoring_retries_onto_the_winner(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        collection.find_one_and_update = AsyncMock(
            side_effect=[DuplicateKeyError("E11000 duplicate key"), _raw(description="second")]
        )

        stored = await repo.upsert_for_workflow(_doc(description="second"))

        assert collection.find_one_and_update.await_count == 2
        assert stored.description == "second"
        # The retry is the SAME write, not a plain update: the loser of the race
        # must still insert when the winner has since been deleted.
        assert [
            call.kwargs["upsert"] for call in collection.find_one_and_update.await_args_list
        ] == [True, True]

    async def test_both_attempts_are_written_in_the_global_scope(
        self, repo: PlaybooksRepository
    ) -> None:
        """``playbooks`` is a global collection, so both the first attempt and the
        duplicate-key retry name the global cache scope."""
        spy, calls = _raw_update_spy(DuplicateKeyError("E11000 duplicate key"), _doc())

        with patch.object(PlaybooksRepository, "_apply_raw_update", spy):
            await repo.upsert_for_workflow(_doc())

        assert [call["scope"] for call in calls] == [REPO_GLOBAL_SCOPE, REPO_GLOBAL_SCOPE]
        assert [call["upsert"] for call in calls] == [True, True]

    async def test_a_playbook_that_vanished_mid_upsert_names_its_workflow(
        self, repo: PlaybooksRepository
    ) -> None:
        """An upsert that matches nothing and inserts nothing cannot be reported as
        a generic failure: the message is the only pointer to which workflow lost
        its write."""
        spy, _calls = _raw_update_spy(None)

        with (
            patch.object(PlaybooksRepository, "_apply_raw_update", spy),
            pytest.raises(RuntimeError) as raised,
        ):
            await repo.upsert_for_workflow(_doc())

        assert str(raised.value) == f"playbook for workflow {WORKFLOW_ID} vanished mid-upsert"


class TestRecordRunOutcome:
    async def test_with_the_replayed_id_the_write_is_scoped_to_that_playbook(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.FAILED),
            playbook_id="pb_first",
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
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.SUCCESS),
            playbook_id="pb_stale",
        )

        assert outcome is None

    async def test_without_an_id_it_updates_whatever_the_workflow_has_in_one_write(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        await repo.record_run_outcome(
            WORKFLOW_ID, USER_ID, PlaybookRunOutcome(PlaybookRunStatus.SUCCESS)
        )

        collection.find_one.assert_not_awaited()
        filter_, _update = collection.find_one_and_update.await_args.args
        assert filter_ == {"workflow_id": WORKFLOW_ID, "user_id": USER_ID}

    async def test_a_suspect_run_records_its_reason_and_grows_the_streak(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="list_events returned no items"),
        )

        collection.find_one_and_update.assert_awaited_once()
        filter_, update = collection.find_one_and_update.await_args.args
        assert update["$set"]["last_run_status"] is PlaybookRunStatus.SUSPECT
        assert update["$set"]["last_run_reason"] == "list_events returned no items"
        assert update["$inc"] == {"suspect_streak": 1}
        assert "suspect_streak" not in update["$set"]
        # Grown only on a document not already suspect: two replays of one body
        # racing to the same verdict are one suspect, not two.
        assert filter_["last_run_status"] == {"$ne": "suspect"}

    async def test_a_suspect_that_does_not_count_records_the_reason_without_growing(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        """The narration's verdict is an opinion: it sends the fire to the agent
        but must not be able to delete a playbook on its own. Two such verdicts
        in a row on a correct playbook were seen live."""
        collection.find_one_and_update = AsyncMock(return_value=_raw(suspect_streak=0))

        await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(
                PlaybookRunStatus.SUSPECT, reason="the model's own take", counts_toward_streak=False
            ),
        )

        collection.find_one_and_update.assert_awaited_once()
        filter_, update = collection.find_one_and_update.await_args.args
        assert "last_run_status" not in filter_
        assert "$inc" not in update
        assert update["$set"]["last_run_status"] is PlaybookRunStatus.SUSPECT
        assert update["$set"]["last_run_reason"] == "the model's own take"

    async def test_a_suspect_on_an_already_suspect_playbook_does_not_grow_the_streak(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        collection.find_one_and_update = AsyncMock(
            side_effect=[None, _raw(last_run_status=PlaybookRunStatus.SUSPECT, suspect_streak=1)]
        )

        outcome = await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="empty again"),
        )

        assert collection.find_one_and_update.await_count == 2
        filter_, update = collection.find_one_and_update.await_args_list[1].args
        assert "last_run_status" not in filter_
        assert "$inc" not in update
        assert update["$set"]["last_run_status"] is PlaybookRunStatus.SUSPECT
        assert update["$set"]["last_run_reason"] == "empty again"
        assert outcome is not None
        assert outcome.suspect_streak == 1

    async def test_with_a_revision_the_write_lands_only_on_that_body(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        """``playbook_id`` survives a rewrite, so on its own it guarded nothing."""
        await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.SUCCESS),
            playbook_id="pb_first",
            revision=3,
        )

        filter_, _update = collection.find_one_and_update.await_args.args
        assert filter_ == {
            "playbook_id": "pb_first",
            "workflow_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "revision": 3,
        }

    async def test_a_rewritten_body_records_nothing(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        collection.find_one_and_update = AsyncMock(return_value=None)

        outcome = await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.FAILED),
            playbook_id="pb_first",
            revision=2,
        )

        assert outcome is None


class TestIncrementHealAttempts:
    async def test_counts_one_attempt_on_the_named_playbook(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        collection.find_one_and_update = AsyncMock(return_value=_raw(heal_attempts=1))

        counted = await repo.increment_heal_attempts(WORKFLOW_ID, USER_ID, playbook_id="pb_first")

        filter_, update = collection.find_one_and_update.await_args.args
        assert filter_ == {
            "workflow_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "playbook_id": "pb_first",
        }
        assert update["$inc"] == {"heal_attempts": 1}
        assert counted is not None
        assert counted.heal_attempts == 1

    async def test_a_revision_scopes_the_count_to_the_body_that_was_healed(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        collection.find_one_and_update = AsyncMock(return_value=None)

        counted = await repo.increment_heal_attempts(
            WORKFLOW_ID, USER_ID, playbook_id="pb_first", revision=3
        )

        filter_, _ = collection.find_one_and_update.await_args.args
        assert filter_["revision"] == 3
        assert counted is None

    async def test_a_replaced_playbook_counts_nothing(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        collection.find_one_and_update = AsyncMock(return_value=None)

        assert (
            await repo.increment_heal_attempts(WORKFLOW_ID, USER_ID, playbook_id="pb_gone") is None
        )

    async def test_a_success_clears_the_reason_and_resets_the_streak(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.SUCCESS, reason="ignored on success"),
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
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.FAILED, reason="stopped at step 2"),
        )

        _filter, update = collection.find_one_and_update.await_args.args
        assert update["$set"]["last_run_status"] is PlaybookRunStatus.FAILED
        assert update["$set"]["last_run_reason"] == "stopped at step 2"
        assert "suspect_streak" not in update["$set"]
        assert "$inc" not in update


class TestTheScopeAndShapeOfEveryRawWrite:
    """The raw-update seam carries two things ``find_one_and_update`` never sees:
    the cache scope the write invalidates, and how the outcome update was asked
    for. ``playbooks`` is a global collection, so every write names the global
    scope; a per-user scope would bump a generation nobody reads and leave the
    global one stale."""

    async def test_a_plain_outcome_is_recorded_in_the_global_scope(
        self, repo: PlaybooksRepository
    ) -> None:
        spy, calls = _raw_update_spy()

        with patch.object(PlaybooksRepository, "_apply_raw_update", spy):
            await repo.record_run_outcome(
                WORKFLOW_ID, USER_ID, PlaybookRunOutcome(PlaybookRunStatus.FAILED)
            )

        assert [call["scope"] for call in calls] == [REPO_GLOBAL_SCOPE]

    async def test_both_writes_of_a_suspect_landing_are_global(
        self, repo: PlaybooksRepository
    ) -> None:
        """The growing write is tried first and matches nothing on an already
        suspect playbook; the plain fallback then runs. Both are the same
        collection and must invalidate the same scope."""
        spy, calls = _raw_update_spy(None, _doc())

        with patch.object(PlaybooksRepository, "_apply_raw_update", spy):
            await repo.record_run_outcome(
                WORKFLOW_ID, USER_ID, PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="empty")
            )

        assert [call["scope"] for call in calls] == [REPO_GLOBAL_SCOPE, REPO_GLOBAL_SCOPE]
        assert calls[0]["filter"]["last_run_status"] == {"$ne": "suspect"}
        assert "last_run_status" not in calls[1]["filter"]

    async def test_counting_a_heal_attempt_is_written_in_the_global_scope(
        self, repo: PlaybooksRepository
    ) -> None:
        spy, calls = _raw_update_spy()

        with patch.object(PlaybooksRepository, "_apply_raw_update", spy):
            await repo.increment_heal_attempts(WORKFLOW_ID, USER_ID, playbook_id="pb_first")

        assert [call["scope"] for call in calls] == [REPO_GLOBAL_SCOPE]
        assert calls[0]["update"] == {"$inc": {"heal_attempts": 1}}

    async def test_each_outcome_write_states_its_own_streak_intent(
        self, repo: PlaybooksRepository, collection: MagicMock
    ) -> None:
        """The two suspect writes differ ONLY in whether they grow the streak, and
        the fallback is the one that lands on a playbook already marked suspect.
        It says so explicitly rather than leaning on a default, because the two
        calls sit three lines apart and a reader has to be able to tell them
        apart at the call site."""
        seen: list[tuple[Any, Any, dict[str, Any]]] = []

        def _outcome_update(
            status: PlaybookRunStatus, reason: str | None, **kwargs: Any
        ) -> dict[str, dict[str, object]]:
            seen.append((status, reason, kwargs))
            return {"$set": {"last_run_status": status, "last_run_reason": reason}}

        collection.find_one_and_update = AsyncMock(side_effect=[None, _raw()])

        with patch.object(playbooks_module, "_outcome_update", _outcome_update):
            await repo.record_run_outcome(
                WORKFLOW_ID,
                USER_ID,
                PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="empty again"),
            )

        assert seen == [
            (PlaybookRunStatus.SUSPECT, "empty again", {"grow_streak": True}),
            (PlaybookRunStatus.SUSPECT, "empty again", {"grow_streak": False}),
        ]
