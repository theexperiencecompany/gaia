"""The post-deploy step against real Mongo: each migration once, in order, a failure retried."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
import uuid

from motor.motor_asyncio import AsyncIOMotorCollection
import pytest
from scripts.migrate_workflow_delivery import migrate as migrate_workflow_delivery
from scripts.retire_legacy_triggers import (
    UnknownTriggerTypeError,
    migrate as retire_legacy_triggers,
)

from app.constants.workflows import WorkflowDelivery
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.workflows import workflow_repository
from app.models.scheduler_models import DeactivationReason
from app.models.trigger_configs import GmailNewMessageConfig
from app.models.workflow_models import TriggerType
from scripts import migrate_brief_link, post_deploy
from tests.factories import make_briefing_payload, make_user_id


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


async def test_a_stale_claim_is_taken_over(steps: dict[str, AsyncMock], raw_collection) -> None:
    await raw_collection.insert_one(
        {"_id": "first", "claimed_at": datetime.now(UTC) - timedelta(days=1), "applied_at": None}
    )

    assert await post_deploy.run_post_deploy(apply=True) == ["first", "second"]


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

    async def test_one_its_owner_had_switched_off_moves_without_a_system_reason(
        self, raw_collection
    ) -> None:
        legacy = _legacy_email_workflow(activated=False)
        await raw_collection.insert_one(legacy)

        await post_deploy.run_post_deploy(apply=True)

        workflow = await workflow_repository.get_for_user(
            str(legacy["_id"]), str(legacy["user_id"])
        )
        assert workflow is not None
        assert workflow.trigger_config.trigger_name == "gmail_new_message"
        assert workflow.deactivated_reason is None

    async def test_a_dry_run_writes_nothing(self, raw_collection) -> None:
        legacy = _legacy_email_workflow(activated=True)
        await raw_collection.insert_one(legacy)

        await post_deploy.run_post_deploy(apply=False)

        assert await raw_collection.find_one({"_id": legacy["_id"]}) == legacy

    async def test_a_type_neither_current_nor_retired_stops_the_release_by_name(
        self, raw_collection
    ) -> None:
        await raw_collection.insert_one(
            {**_legacy_email_workflow(activated=True), "trigger_config": {"type": "fax"}}
        )

        with pytest.raises(UnknownTriggerTypeError, match="fax"):
            await post_deploy.run_post_deploy(apply=True)


_BRIEF_LINK = "https://heygaia.link/abcdefghijk"


def _brief_as_stored_with_its_link_on_the_payload(link: str | None) -> dict[str, object]:
    """Build a brief as the previous release stored it: its link set on its payload."""
    return {
        "_id": f"brief_{uuid.uuid4().hex[:12]}",
        "user_id": make_user_id(),
        "date": "2026-11-17",
        "kind": "daily",
        "payload": {**make_briefing_payload(date="2026-11-17").model_dump(), "link": link},
        "delivered_channels": ["inapp"],
        "created_at": datetime(2026, 11, 17, tzinfo=UTC),
    }


@pytest.fixture
async def brief_link_release(raw_collection, monkeypatch: pytest.MonkeyPatch):
    """Run only the brief link step, over raw_collection, marking it in a collection apart."""
    markers = _release_of(raw_collection, monkeypatch, ("migrate_brief_link",))
    monkeypatch.setattr(migrate_brief_link, "briefings_collection", raw_collection)
    yield
    await markers.drop()


@pytest.mark.usefixtures("brief_link_release")
class TestBriefLinkMovesOffThePayload:
    async def test_the_release_gives_each_brief_the_link_its_payload_carried(
        self, raw_collection
    ) -> None:
        edition = _brief_as_stored_with_its_link_on_the_payload(_BRIEF_LINK)
        note = _brief_as_stored_with_its_link_on_the_payload(None)
        await raw_collection.insert_many([edition, note])

        assert await post_deploy.run_post_deploy(apply=True) == ["migrate_brief_link"]

        moved = await briefing_repository.get(str(edition["_id"]), user_id=str(edition["user_id"]))
        quiet = await briefing_repository.get(str(note["_id"]), user_id=str(note["user_id"]))
        assert moved is not None and quiet is not None
        assert (moved.link, quiet.link) == (_BRIEF_LINK, None)
        # The previous release still serves while the release runs, so its payload keeps the link.
        raw = await raw_collection.find_one({"_id": edition["_id"]})
        assert raw is not None and raw["payload"]["link"] == _BRIEF_LINK

    async def test_a_dry_run_writes_nothing(self, raw_collection) -> None:
        stored = _brief_as_stored_with_its_link_on_the_payload(_BRIEF_LINK)
        await raw_collection.insert_one(stored)

        await post_deploy.run_post_deploy(apply=False)

        assert await raw_collection.find_one({"_id": stored["_id"]}) == stored

    async def test_a_brief_already_carrying_its_link_keeps_it(self, raw_collection) -> None:
        stored = {
            **_brief_as_stored_with_its_link_on_the_payload("https://heygaia.link/stale"),
            "link": _BRIEF_LINK,
        }
        await raw_collection.insert_one(stored)

        assert await migrate_brief_link.migrate(apply=True) == 0

        assert await raw_collection.find_one({"_id": stored["_id"]}) == stored

    async def test_contract_moves_what_the_previous_release_stored_since_then_drops_the_payload_link(
        self, raw_collection
    ) -> None:
        await raw_collection.insert_one(_brief_as_stored_with_its_link_on_the_payload(_BRIEF_LINK))
        await migrate_brief_link.migrate(apply=True)
        late = _brief_as_stored_with_its_link_on_the_payload(_BRIEF_LINK)
        await raw_collection.insert_one(late)
        carrying = {"payload.link": {"$exists": True}}

        assert await migrate_brief_link.contract(apply=False) == 2
        assert await raw_collection.count_documents(carrying) == 2

        assert await migrate_brief_link.contract(apply=True) == 2

        assert await raw_collection.count_documents(carrying) == 0
        moved = await briefing_repository.get(str(late["_id"]), user_id=str(late["user_id"]))
        assert moved is not None and moved.link == _BRIEF_LINK
