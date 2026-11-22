"""Workflows on a trigger type retired in #412 read cleanly once moved to its successor."""

from datetime import UTC, datetime
import uuid

from pydantic import ValidationError
import pytest
from scripts.retire_legacy_triggers import UnknownTriggerTypeError, migrate

from app.db.repositories.workflows import workflow_repository
from app.models.scheduler_models import DeactivationReason
from app.models.trigger_configs import CalendarEventCreatedConfig, GmailNewMessageConfig
from app.models.workflow_models import TriggerType
from tests.factories import make_user_id


def _legacy_workflow(*, trigger_type: str, activated: bool) -> dict[str, object]:
    """Build a workflow as stored before "email" and "calendar" became integration triggers."""
    return {
        "_id": f"wf_{uuid.uuid4().hex[:12]}",
        "user_id": make_user_id(),
        "title": "Sort my inbox",
        "description": "Label every new email",
        "steps": [{"id": "s1", "title": "Label", "category": "gmail", "description": "label it"}],
        "trigger_config": {"type": trigger_type, "enabled": activated},
        "activated": activated,
        "status": "scheduled",
        "created_at": datetime(2025, 11, 2, tzinfo=UTC),
        "updated_at": datetime(2025, 11, 2, tzinfo=UTC),
    }


class TestLegacyEmailTrigger:
    """A workflow on the retired "email" trigger failed validation wherever it was read strictly."""

    async def test_an_unmigrated_one_fails_the_owned_read_and_the_activated_scan(
        self, raw_collection
    ) -> None:
        legacy = _legacy_workflow(trigger_type="email", activated=True)
        await raw_collection.insert_one(legacy)

        with pytest.raises(ValidationError):
            await workflow_repository.get_for_user(str(legacy["_id"]), str(legacy["user_id"]))
        with pytest.raises(ValidationError):
            await workflow_repository.find_activated_for_user(str(legacy["user_id"]))

    async def test_an_activated_one_reads_as_a_switched_off_gmail_trigger(
        self, raw_collection
    ) -> None:
        legacy = _legacy_workflow(trigger_type="email", activated=True)
        await raw_collection.insert_one(legacy)

        assert await migrate(apply=True) == 1

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
        assert await workflow_repository.find_activated_for_user(str(legacy["user_id"])) == []

    async def test_a_calendar_one_moves_to_calendar_event_created(self, raw_collection) -> None:
        legacy = _legacy_workflow(trigger_type="calendar", activated=True)
        await raw_collection.insert_one(legacy)

        await migrate(apply=True)

        workflow = await workflow_repository.get_for_user(
            str(legacy["_id"]), str(legacy["user_id"])
        )
        assert workflow is not None
        assert workflow.trigger_config.trigger_name == "calendar_event_created"
        assert workflow.trigger_config.trigger_data == CalendarEventCreatedConfig()

    async def test_one_its_owner_had_switched_off_moves_without_a_system_reason(
        self, raw_collection
    ) -> None:
        legacy = _legacy_workflow(trigger_type="email", activated=False)
        await raw_collection.insert_one(legacy)

        await migrate(apply=True)

        workflow = await workflow_repository.get_for_user(
            str(legacy["_id"]), str(legacy["user_id"])
        )
        assert workflow is not None
        assert workflow.trigger_config.trigger_name == "gmail_new_message"
        assert workflow.deactivated_reason is None

    async def test_a_dry_run_writes_nothing(self, raw_collection) -> None:
        legacy = _legacy_workflow(trigger_type="email", activated=True)
        await raw_collection.insert_one(legacy)

        assert await migrate(apply=False) == 1

        assert await raw_collection.find_one({"_id": legacy["_id"]}) == legacy

    async def test_a_second_run_finds_nothing_left(self, raw_collection) -> None:
        await raw_collection.insert_one(_legacy_workflow(trigger_type="email", activated=True))

        await migrate(apply=True)

        assert await migrate(apply=True) == 0

    async def test_a_type_neither_current_nor_retired_stops_the_run_by_name(
        self, raw_collection
    ) -> None:
        legacy = _legacy_workflow(trigger_type="email", activated=True)
        await raw_collection.insert_many(
            [legacy, _legacy_workflow(trigger_type="fax", activated=True)]
        )

        with pytest.raises(UnknownTriggerTypeError, match="fax"):
            await migrate(apply=True)
        assert await raw_collection.find_one({"_id": legacy["_id"]}) == legacy


class TestMoveToSuccessorTrigger:
    """The repository write reports whether the record was still on the retired type."""

    async def test_a_record_on_the_retired_type_is_moved_and_reported(self, raw_collection) -> None:
        legacy = _legacy_workflow(trigger_type="email", activated=True)
        await raw_collection.insert_one(legacy)

        moved = await workflow_repository.move_to_successor_trigger(
            str(legacy["_id"]), "email", GmailNewMessageConfig(), reason=None
        )

        assert moved is True
        stored = await raw_collection.find_one({"_id": legacy["_id"]})
        assert stored is not None
        assert stored["trigger_config"]["type"] == TriggerType.INTEGRATION.value

    async def test_a_record_already_on_another_type_is_left_alone_and_reported(
        self, raw_collection
    ) -> None:
        legacy = _legacy_workflow(trigger_type="calendar", activated=True)
        await raw_collection.insert_one(legacy)

        moved = await workflow_repository.move_to_successor_trigger(
            str(legacy["_id"]), "email", GmailNewMessageConfig(), reason=None
        )

        assert moved is False
        assert await raw_collection.find_one({"_id": legacy["_id"]}) == legacy
