"""Contract tests for TasksRepository against real Mongo: the finders the engine depends on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pymongo.errors import DuplicateKeyError
import pytest

from app.constants.tasks import Assignee, TaskRunState
from app.db.mongodb.indexes import TASK_OPEN_EXTERNAL_REF_KEYS, TASK_OPEN_EXTERNAL_REF_OPTIONS
from app.db.repositories.tasks import TasksRepository
from app.models.scheduler_models import DeactivationReason
from app.models.task_models import (
    EventWhen,
    ExternalRef,
    ExternalRefSource,
    NoWhen,
    RepeatWhen,
    TaskDocument,
    TaskQuery,
)
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)

USER = "user_contract"
NOW = datetime(2026, 11, 22, 8, 0, tzinfo=UTC)


@pytest.fixture
def repo(raw_collection) -> TasksRepository:
    return TasksRepository()


def _gaia(**fields: object) -> TaskDocument:
    return TaskDocument.model_validate(
        {"user_id": USER, "title": "t", "assignee": Assignee.GAIA, **fields}
    )


def _watch(trigger_id: str) -> TriggerSubscription:
    return TriggerSubscription(
        trigger_name="github_commit_event",
        action=SubscriptionAction.EXECUTE,
        resolution=SubscriptionResolution.TRIGGER_ID,
        composio_trigger_ids=[trigger_id],
    )


class TestDueRuns:
    async def test_a_due_schedule_or_check_is_found_and_a_paused_or_future_one_is_not(
        self, repo: TasksRepository
    ) -> None:
        due_repeat = await repo.create(
            _gaia(when=RepeatWhen(rule="0 8 * * *", next_run=NOW - timedelta(minutes=1)))
        )
        due_check = await repo.create(_gaia(next_check_at=NOW))
        await repo.create(_gaia(next_check_at=NOW + timedelta(hours=1)))
        await repo.create(_gaia(next_check_at=NOW, active=False))
        await repo.create(_gaia(next_check_at=NOW, retry_count=3))

        due = await repo.find_due_all_users(now=NOW, max_retries=3, limit=10)

        assert {t.id for t in due} == {due_repeat.id, due_check.id}


class TestClaimingARun:
    async def test_only_the_armed_occurrence_claims_it_and_only_once(
        self, repo: TasksRepository
    ) -> None:
        task = await repo.create(_gaia(next_check_at=NOW))

        assert await repo.claim_run(task.id, armed_for=NOW - timedelta(hours=1)) is None
        claimed = await repo.claim_run(task.id, armed_for=NOW)
        assert claimed is not None and claimed.run_state is TaskRunState.RUNNING
        assert await repo.claim_run(task.id, armed_for=NOW) is None


class TestAppEventDispatch:
    async def test_a_trigger_instance_finds_its_open_task_unless_the_user_stopped_it(
        self, repo: TasksRepository
    ) -> None:
        listening = await repo.create(_gaia(when=EventWhen(), subscriptions=[_watch("ti_1")]))
        paused = await repo.create(
            _gaia(
                when=EventWhen(),
                subscriptions=[_watch("ti_1")],
                active=False,
                pause_reason=DeactivationReason.SUBSCRIPTION_LAPSED,
            )
        )
        await repo.create(_gaia(when=EventWhen(), subscriptions=[_watch("ti_1")], active=False))
        await repo.create(_gaia(when=EventWhen(), subscriptions=[_watch("ti_2")]))

        found = await repo.find_listening_by_composio_trigger_all_users("ti_1")

        assert sorted(t.id for t in found) == sorted([listening.id, paused.id])
        assert await repo.count_trigger_references("ti_1") == 3

    async def test_adding_the_same_subscription_twice_keeps_one(
        self, repo: TasksRepository
    ) -> None:
        task = await repo.create(_gaia())
        await repo.add_subscription(task.id, user_id=USER, subscription=_watch("ti_1"))

        again = await repo.add_subscription(task.id, user_id=USER, subscription=_watch("ti_1"))

        assert again is not None and len(again.subscriptions) == 1


class TestListAndRefs:
    async def test_the_list_reads_a_subtask_page_and_the_open_ref_owner(
        self, repo: TasksRepository, raw_collection
    ) -> None:
        await raw_collection.create_index(
            TASK_OPEN_EXTERNAL_REF_KEYS, **TASK_OPEN_EXTERNAL_REF_OPTIONS
        )
        ref = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="thread-1")
        parent = await repo.create(_gaia(when=NoWhen()))
        child = await repo.create(_gaia(parent_id=parent.id, external_ref=ref))

        page = await repo.list_page(user_id=USER, query=TaskQuery(parent_id=parent.id))
        owner = await repo.find_open_by_external_ref(USER, ref)

        assert ([t.id for t in page.items], page.total) == ([child.id], 1)
        assert owner is not None and owner.id == child.id
        with pytest.raises(DuplicateKeyError):
            await repo.create(_gaia(external_ref=ref))
