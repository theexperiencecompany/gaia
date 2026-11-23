"""The post-deploy step against real Mongo: each migration once, in order, a failure retried."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
import uuid

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest
from redis.asyncio import Redis
from scripts.migrate_workflow_delivery import migrate as migrate_workflow_delivery
from scripts.retire_legacy_triggers import migrate as retire_legacy_triggers

from app.config.settings import settings
from app.constants.workflows import EXECUTE_WORKFLOW_TASK, WorkflowDelivery
from app.db.repositories.workflows import workflow_repository
from app.models.scheduler_models import DeactivationReason
from app.models.trigger_configs import GmailNewMessageConfig
from app.models.workflow_models import TriggerType
from app.services.workflow.scheduler import workflow_scheduler
from scripts import post_deploy
from tests.factories import make_user_id
from tests.helpers import worker_redis_url


def _steps(*names: str) -> dict[str, AsyncMock]:
    return {name: AsyncMock() for name in names}


@pytest.fixture
def steps(raw_collection, monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    fakes = _steps("first", "second")
    monkeypatch.setattr(post_deploy, "deploy_steps", raw_collection)
    monkeypatch.setattr(post_deploy, "POST_DEPLOY_STEPS", tuple(fakes.items()))
    return fakes


async def test_a_dry_run_runs_each_step_as_a_dry_run_and_marks_nothing(
    steps: dict[str, AsyncMock], raw_collection
) -> None:
    assert await post_deploy.run_post_deploy(apply=False) == []

    for step in steps.values():
        step.assert_awaited_once_with(apply=False)
    assert await raw_collection.count_documents({}) == 0


async def test_each_step_applies_once_in_order_and_never_again(
    steps: dict[str, AsyncMock],
) -> None:
    assert await post_deploy.run_post_deploy(apply=True) == ["first", "second"]
    assert await post_deploy.run_post_deploy(apply=True) == []

    for step in steps.values():
        step.assert_awaited_once_with(apply=True)


async def test_a_failed_step_stops_the_run_and_is_retried_next_time(
    steps: dict[str, AsyncMock],
) -> None:
    steps["first"].side_effect = [RuntimeError("mongo blip"), None]

    with pytest.raises(RuntimeError, match="mongo blip"):
        await post_deploy.run_post_deploy(apply=True)
    steps["second"].assert_not_awaited()

    assert await post_deploy.run_post_deploy(apply=True) == ["first", "second"]


async def test_a_step_a_live_runner_holds_is_waited_for_before_the_next_runs(
    steps: dict[str, AsyncMock], raw_collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(post_deploy, "_CLAIM_POLL", timedelta(milliseconds=10))
    await raw_collection.insert_one(
        {"_id": "first", "claimed_at": datetime.now(UTC), "applied_at": None}
    )
    second_saw_first_applied: list[bool] = []

    async def second(apply: bool) -> None:
        marker = await raw_collection.find_one({"_id": "first"})
        second_saw_first_applied.append(marker["applied_at"] is not None)

    steps["second"].side_effect = second
    run = asyncio.create_task(post_deploy.run_post_deploy(apply=True))
    await asyncio.sleep(0.05)
    assert not run.done()

    await raw_collection.update_one({"_id": "first"}, {"$set": {"applied_at": datetime.now(UTC)}})

    assert await asyncio.wait_for(run, timeout=5) == ["second"]
    steps["first"].assert_not_awaited()
    assert second_saw_first_applied == [True]


@pytest.mark.regression
async def test_a_claim_left_by_a_release_job_killed_at_its_cap_is_taken_over(
    steps: dict[str, AsyncMock], raw_collection
) -> None:
    """Regression: a 2h window blocked the re-run after deploy.sh's 1800s cap killed a step."""
    killed_at_cap = datetime.now(UTC) - timedelta(minutes=36)
    await raw_collection.insert_one(
        {"_id": "first", "claimed_at": killed_at_cap, "applied_at": None}
    )

    run = post_deploy.run_post_deploy(apply=True)
    assert await asyncio.wait_for(run, timeout=5) == ["first", "second"]


@pytest.mark.regression
async def test_a_workflow_a_release_step_arms_is_queued_in_arq_at_once(
    steps: dict[str, AsyncMock], redis: Redis, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the release job had no ARQ pool, so every workflow it activated went unqueued."""
    monkeypatch.setattr(settings, "REDIS_URL", worker_redis_url(redis_url))
    workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
    armed: list[bool] = []

    async def first(apply: bool) -> None:
        at = datetime.now(UTC) + timedelta(hours=1)
        armed.append(await workflow_scheduler.schedule_workflow_execution(workflow_id, at))

    steps["first"].side_effect = first

    assert await post_deploy.release(apply=True) == ["first", "second"]

    assert armed == [True]
    assert await redis.keys(f"arq:job:{EXECUTE_WORKFLOW_TASK}:{workflow_id}:*") != []
    assert workflow_scheduler.arq_pool is None


#: The workflow migrations, in the order the real release runs them.
_WORKFLOW_STEPS = ("retire_legacy_triggers", "migrate_workflow_delivery")


def _legacy_email_workflow(*, activated: bool) -> dict[str, object]:
    """Build a workflow as stored before trigger types became integrations and before delivery."""
    return {
        "_id": f"wf_{uuid.uuid4().hex[:12]}",
        "user_id": make_user_id(),
        "title": "Sort my inbox",
        "description": "Label every new email",
        "steps": [{"id": "s1", "title": "Label", "category": "gmail", "description": "label it"}],
        "trigger_config": {"type": "email", "enabled": activated},
        "activated": activated,
        "notify_on_completion": False,
        "status": "scheduled",
        "created_at": datetime(2025, 11, 2, tzinfo=UTC),
        "updated_at": datetime(2025, 11, 2, tzinfo=UTC),
    }


def _release_of(
    raw_collection: AsyncIOMotorCollection,
    monkeypatch: pytest.MonkeyPatch,
    names: tuple[str, ...],
) -> AsyncIOMotorCollection:
    """Run only the named real steps, over raw_collection; return the collection marking them."""
    markers = raw_collection.database[f"{raw_collection.name}_deploy_steps"]
    monkeypatch.setattr(post_deploy, "deploy_steps", markers)
    monkeypatch.setattr(
        post_deploy,
        "POST_DEPLOY_STEPS",
        tuple(step for step in post_deploy.POST_DEPLOY_STEPS if step[0] in names),
    )
    return markers


@pytest.fixture
async def workflow_release(raw_collection, monkeypatch: pytest.MonkeyPatch):
    """Run only the real workflow steps, over raw_collection, marking them in a collection apart."""
    markers = _release_of(raw_collection, monkeypatch, _WORKFLOW_STEPS)
    yield
    await markers.drop()


@pytest.mark.usefixtures("workflow_release")
class TestLegacyEmailTrigger:
    """A workflow on the retired "email" trigger once stopped the release with a ValidationError."""

    async def test_the_release_applies_and_the_workflow_reads_as_a_switched_off_gmail_trigger(
        self, raw_collection
    ) -> None:
        legacy = _legacy_email_workflow(activated=True)
        await raw_collection.insert_one(legacy)

        assert await post_deploy.run_post_deploy(apply=True) == list(_WORKFLOW_STEPS)

        workflow = await workflow_repository.get_for_user(
            str(legacy["_id"]), str(legacy["user_id"])
        )
        assert workflow is not None
        assert workflow.trigger_config.type is TriggerType.INTEGRATION
        assert workflow.trigger_config.trigger_name == "gmail_new_message"
        assert workflow.trigger_config.trigger_data == GmailNewMessageConfig()
        assert workflow.trigger_config.enabled is False
        assert workflow.trigger_config.composio_trigger_ids == []
        assert workflow.activated is False
        assert workflow.deactivated_reason is DeactivationReason.TRIGGER_RETIRED
        assert workflow.delivery is WorkflowDelivery.SILENT

    async def test_only_the_legacy_workflow_is_counted_and_a_current_one_is_left_as_stored(
        self, raw_collection
    ) -> None:
        legacy = _legacy_email_workflow(activated=True)
        await raw_collection.insert_one(legacy)
        current = {
            **_legacy_email_workflow(activated=True),
            "trigger_config": {"type": "manual", "enabled": True},
            "delivery": "brief",
        }
        del current["notify_on_completion"]
        await raw_collection.insert_one(current)

        assert await retire_legacy_triggers(apply=False) == 1
        assert await migrate_workflow_delivery(apply=False) == 1
        await post_deploy.run_post_deploy(apply=True)

        assert await raw_collection.find_one({"_id": current["_id"]}) == current
        stored = await raw_collection.find_one({"_id": legacy["_id"]})
        assert stored is not None
        assert (stored["delivery"], "notify_on_completion" in stored) == ("silent", False)
