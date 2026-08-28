"""Contract tests for PlaybooksRepository against real Mongo.

The invariant the whole design rests on is one active playbook per workflow with
no version history, so the interesting assertions are that an overwrite leaves
exactly one document behind and that a user can never reach another user's.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError
import pytest

from app.db.repositories.playbooks import PlaybooksRepository
from app.models.playbook_models import (
    PlaybookDocument,
    PlaybookRunOutcome,
    PlaybookRunStatus,
    PlaybookUpdate,
)
from app.utils.errors import EmptyUpdateError

WORKFLOW_ID = "wf_contract"
USER_ID = "user_contract"


@pytest.fixture
def repo(raw_collection) -> PlaybooksRepository:
    return PlaybooksRepository()


def make_doc(**overrides) -> PlaybookDocument:
    now = datetime.now(UTC)
    data = {
        "workflow_id": WORKFLOW_ID,
        "user_id": USER_ID,
        "workflow_hash": "hash-1",
        "description": "first",
        "steps": [{"id": "one", "tool": "list_events", "args": {"calendar_id": "primary"}}],
        "synthesize": "s",
        "created_at": now,
        "updated_at": now,
    }
    data.update(overrides)
    return PlaybookDocument.model_validate(data)


class TestPlaybooksRepository:
    async def test_create_then_get_for_workflow_roundtrips_every_field(self, repo) -> None:
        created = await repo.create(make_doc())
        fetched = await repo.get_for_workflow(WORKFLOW_ID, USER_ID)
        assert fetched == created

    async def test_get_for_workflow_missing_returns_none(self, repo) -> None:
        assert await repo.get_for_workflow("wf_nothing", USER_ID) is None

    async def test_another_users_playbook_is_invisible(self, repo) -> None:
        await repo.create(make_doc())
        assert await repo.get_for_workflow(WORKFLOW_ID, "attacker") is None

    async def test_upsert_creates_when_absent(self, repo, raw_collection) -> None:
        stored = await repo.upsert_for_workflow(make_doc())
        assert stored.description == "first"
        assert await raw_collection.count_documents({"workflow_id": WORKFLOW_ID}) == 1

    async def test_upsert_overwrites_in_place_keeping_one_document(
        self, repo, raw_collection
    ) -> None:
        first = await repo.upsert_for_workflow(make_doc())
        second = await repo.upsert_for_workflow(
            make_doc(
                description="second",
                workflow_hash="hash-2",
            )
        )
        assert second.playbook_id == first.playbook_id
        assert second.description == "second"
        assert second.workflow_hash == "hash-2"
        assert await raw_collection.count_documents({"workflow_id": WORKFLOW_ID}) == 1

    async def test_upsert_resets_the_outcome_but_keeps_the_suspect_streak(self, repo) -> None:
        await repo.upsert_for_workflow(make_doc())
        await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="empty where it had items"),
        )
        replaced = await repo.upsert_for_workflow(make_doc(description="second"))
        assert replaced.last_run_status is PlaybookRunStatus.NOT_RUN
        assert replaced.last_run_reason is None
        # The rewrite is the heal run's answer; only a trusted replay clears the streak.
        assert replaced.suspect_streak == 1

    async def test_suspect_runs_grow_the_streak_until_a_success_resets_it(self, repo) -> None:
        """A suspect grows the streak once per verdict on a body: a second
        suspect with no heal between (two replays of one body racing) counts
        once, the rewrite a heal makes puts the body back to NOT_RUN, and the
        next suspect grows it again."""
        await repo.create(make_doc())

        first = await repo.record_run_outcome(
            WORKFLOW_ID, USER_ID, PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="empty once")
        )
        repeated = await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="empty again, same body"),
        )
        await repo.upsert_for_workflow(make_doc(description="healed"))
        second = await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="empty twice"),
        )
        cleared = await repo.record_run_outcome(
            WORKFLOW_ID, USER_ID, PlaybookRunOutcome(PlaybookRunStatus.SUCCESS)
        )

        assert (first.suspect_streak, first.last_run_reason) == (1, "empty once")
        assert (repeated.suspect_streak, repeated.last_run_reason) == (1, "empty again, same body")
        assert (second.suspect_streak, second.last_run_reason) == (2, "empty twice")
        assert cleared.last_run_status is PlaybookRunStatus.SUCCESS
        assert cleared.suspect_streak == 0
        assert cleared.last_run_reason is None
        reread = await repo.get_for_workflow(WORKFLOW_ID, USER_ID)
        assert reread == cleared

    async def test_every_write_bumps_the_revision_and_resets_the_heal_attempts(self, repo) -> None:
        first = await repo.upsert_for_workflow(make_doc())
        counted = await repo.increment_heal_attempts(
            WORKFLOW_ID, USER_ID, playbook_id=first.playbook_id
        )
        second = await repo.upsert_for_workflow(make_doc(description="second"))

        assert first.revision == 1
        assert counted.heal_attempts == 1
        assert second.revision == 2
        assert second.heal_attempts == 0
        assert second.playbook_id == first.playbook_id

    async def test_a_heal_count_for_a_rewritten_body_lands_nowhere(self, repo) -> None:
        first = await repo.upsert_for_workflow(make_doc())
        second = await repo.upsert_for_workflow(make_doc(description="rewritten"))

        stale = await repo.increment_heal_attempts(
            WORKFLOW_ID, USER_ID, playbook_id=first.playbook_id, revision=first.revision
        )
        current = await repo.get_for_workflow(WORKFLOW_ID, USER_ID)

        assert stale is None
        assert current is not None
        assert current.revision == second.revision
        assert current.heal_attempts == 0

    async def test_increment_heal_attempts_ignores_a_replaced_playbook(self, repo) -> None:
        await repo.create(make_doc())
        assert (
            await repo.increment_heal_attempts(WORKFLOW_ID, USER_ID, playbook_id="pb_not_this")
            is None
        )

    async def test_record_run_outcome_scoped_to_the_replayed_revision(self, repo) -> None:
        """A rewrite keeps the id, so a replay that finishes after the agent
        rewrote the body must not stamp its verdict on the new body."""
        replayed = await repo.upsert_for_workflow(make_doc())
        rewritten = await repo.upsert_for_workflow(make_doc(description="second"))
        assert rewritten.playbook_id == replayed.playbook_id

        stale = await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="empty"),
            playbook_id=replayed.playbook_id,
            revision=replayed.revision,
        )

        assert stale is None
        reread = await repo.get_for_workflow(WORKFLOW_ID, USER_ID)
        assert reread is not None
        assert reread.last_run_status is PlaybookRunStatus.NOT_RUN
        assert reread.suspect_streak == 0

        current = await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.SUCCESS),
            playbook_id=rewritten.playbook_id,
            revision=rewritten.revision,
        )
        assert current is not None
        assert current.last_run_status is PlaybookRunStatus.SUCCESS

    async def test_a_failure_keeps_the_streak_and_records_its_reason(self, repo) -> None:
        await repo.create(make_doc())
        await repo.record_run_outcome(
            WORKFLOW_ID, USER_ID, PlaybookRunOutcome(PlaybookRunStatus.SUSPECT, reason="e")
        )

        failed = await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.FAILED, reason="stopped at step 2"),
        )

        assert failed.last_run_status is PlaybookRunStatus.FAILED
        assert failed.last_run_reason == "stopped at step 2"
        assert failed.suspect_streak == 1

    async def test_record_run_outcome_persists(self, repo) -> None:
        await repo.create(make_doc())
        updated = await repo.record_run_outcome(
            WORKFLOW_ID, USER_ID, PlaybookRunOutcome(PlaybookRunStatus.SUCCESS)
        )
        assert updated is not None
        reread = await repo.get_for_workflow(WORKFLOW_ID, USER_ID)
        assert reread is not None
        assert reread.last_run_status is PlaybookRunStatus.SUCCESS

    async def test_record_run_outcome_without_a_playbook_is_none(self, repo) -> None:
        assert (
            await repo.record_run_outcome(
                "wf_nothing", USER_ID, PlaybookRunOutcome(PlaybookRunStatus.SUCCESS)
            )
            is None
        )

    async def test_record_run_outcome_scoped_to_the_replayed_playbook(self, repo) -> None:
        """A replay that finishes after the agent re-authored the playbook must
        not stamp the old sequence's verdict on the new one."""
        replayed = await repo.create(make_doc())
        assert (
            await repo.record_run_outcome(
                WORKFLOW_ID,
                USER_ID,
                PlaybookRunOutcome(PlaybookRunStatus.FAILED),
                playbook_id=replayed.playbook_id,
            )
            is not None
        )
        await repo.delete_for_workflow(WORKFLOW_ID, USER_ID)
        rewritten = await repo.create(make_doc(description="second"))

        stale = await repo.record_run_outcome(
            WORKFLOW_ID,
            USER_ID,
            PlaybookRunOutcome(PlaybookRunStatus.FAILED),
            playbook_id=replayed.playbook_id,
        )

        assert stale is None
        reread = await repo.get_for_workflow(WORKFLOW_ID, USER_ID)
        assert reread is not None
        assert reread.playbook_id == rewritten.playbook_id
        assert reread.last_run_status is PlaybookRunStatus.NOT_RUN

    async def test_record_run_outcome_by_id_cannot_reach_another_users_playbook(self, repo) -> None:
        created = await repo.create(make_doc())
        assert (
            await repo.record_run_outcome(
                WORKFLOW_ID,
                "attacker",
                PlaybookRunOutcome(PlaybookRunStatus.SUCCESS),
                playbook_id=created.playbook_id,
            )
            is None
        )
        assert await repo.get_for_workflow(WORKFLOW_ID, USER_ID) == created

    async def test_delete_for_workflow_removes_it_then_reports_false(self, repo) -> None:
        await repo.create(make_doc())
        assert await repo.delete_for_workflow(WORKFLOW_ID, USER_ID) is True
        assert await repo.get_for_workflow(WORKFLOW_ID, USER_ID) is None
        assert await repo.delete_for_workflow(WORKFLOW_ID, USER_ID) is False

    async def test_delete_for_workflow_cannot_reach_another_user(self, repo) -> None:
        created = await repo.create(make_doc())
        assert await repo.delete_for_workflow(WORKFLOW_ID, "attacker") is False
        assert await repo.get_for_workflow(WORKFLOW_ID, USER_ID) == created

    async def test_empty_update_raises_empty_update_error(self, repo) -> None:
        created = await repo.create(make_doc())
        with pytest.raises(EmptyUpdateError):
            await repo.update(created.playbook_id, PlaybookUpdate())

    async def test_datetimes_come_back_tz_aware_utc(self, repo) -> None:
        created = await repo.create(make_doc())
        for value in (created.created_at, created.updated_at):
            assert value.tzinfo is not None
            assert value.utcoffset().total_seconds() == 0


class TestPlaybooksUniqueIndexSurface:
    """The one-per-workflow index lives on the real collection, not the ephemeral
    fixture — recreate it here to prove the DuplicateKeyError surface the
    repository's upsert retry depends on, and that the upsert itself never
    trips it."""

    async def _create_indexes(self, raw_collection) -> None:
        # Mirrors app/db/mongodb/indexes.py::create_playbook_indexes.
        await raw_collection.create_index([("workflow_id", 1), ("user_id", 1)], unique=True)

    async def test_a_second_document_for_the_workflow_raises(self, repo, raw_collection) -> None:
        await self._create_indexes(raw_collection)
        await repo.create(make_doc())
        with pytest.raises(DuplicateKeyError):
            await repo.create(make_doc(description="duplicate"))

    async def test_upsert_over_an_existing_playbook_keeps_one_document(
        self, repo, raw_collection
    ) -> None:
        await self._create_indexes(raw_collection)
        first = await repo.upsert_for_workflow(make_doc())
        second = await repo.upsert_for_workflow(make_doc(description="second"))
        assert second.playbook_id == first.playbook_id
        assert await raw_collection.count_documents({"workflow_id": WORKFLOW_ID}) == 1
