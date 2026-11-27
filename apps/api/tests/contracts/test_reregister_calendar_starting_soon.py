"""The re-registration script moves stored calendar triggers onto Composio's fire-threshold config."""

from collections.abc import Iterator
from datetime import UTC, datetime
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid

import pytest

from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.scripts.reregister_calendar_starting_soon import TRIGGER_NAME, _run
from tests.factories import make_user_id


class _FakeComposio:
    """Composio's upsert: one instance per (account, config), so an identical config keeps its id."""

    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.deleted: list[str] = []
        self.composio = SimpleNamespace(
            triggers=SimpleNamespace(create=self._create, delete=self._delete)
        )

    def _create(
        self, *, connected_account_id: str, slug: str, trigger_config: dict[str, object]
    ) -> SimpleNamespace:
        self.created.append(trigger_config)
        key = json.dumps([connected_account_id, slug, trigger_config], sort_keys=True)
        return SimpleNamespace(trigger_id=f"ti_{hashlib.sha256(key.encode()).hexdigest()[:8]}")

    def _delete(self, trigger_id: str) -> MagicMock:
        self.deleted.append(trigger_id)
        return MagicMock()


@pytest.fixture
def composio() -> Iterator[_FakeComposio]:
    fake = _FakeComposio()

    async def primary_account(_user_id: str, _slug: str) -> str:
        return "ca_primary"

    with (
        patch("app.services.triggers.base.get_composio_service", return_value=fake),
        patch("app.services.triggers.base.primary_account_for_trigger", primary_account),
    ):
        yield fake


def _workflow(user_id: str, lead: int) -> dict[str, object]:
    return {
        "_id": f"wf_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "title": "Meeting Prep",
        "description": "Brief me before meetings",
        "steps": [{"id": "s1", "title": "Brief", "category": "gaia", "description": "brief"}],
        "trigger_config": {
            "type": "integration",
            "enabled": True,
            "trigger_name": TRIGGER_NAME,
            "trigger_data": {
                "trigger_name": TRIGGER_NAME,
                "calendar_ids": ["primary"],
                "minutes_before_start": lead,
                "include_all_day": False,
            },
            "composio_trigger_ids": ["ti_old_workflow"],
        },
        "activated": True,
        "status": "scheduled",
        "created_at": datetime(2026, 11, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 11, 1, tzinfo=UTC),
    }


def _watched_todo(user_id: str, lead: int) -> TodoDocument:
    watch = TriggerSubscription.model_validate(
        {
            "trigger_name": TRIGGER_NAME,
            "action": SubscriptionAction.EXECUTE,
            "resolution": SubscriptionResolution.TRIGGER_ID,
            "composio_trigger_ids": ["ti_old_todo"],
            "trigger_data": {"calendar_ids": ["primary"], "minutes_before_start": lead},
        }
    )
    return TodoDocument.model_validate(
        {"user_id": user_id, "title": "Prep for the board call", "trigger_subscriptions": [watch]}
    )


async def _seed(raw_collection) -> tuple[str, str, str]:
    user_id = make_user_id()
    workflow = _workflow(user_id, lead=60)
    await raw_collection.insert_one(workflow)
    todo = await todo_repository.create(_watched_todo(user_id, lead=30))
    return user_id, str(workflow["_id"]), todo.id


def _fire_threshold(config: dict[str, object]) -> object:
    return config["minutesBeforeStart"]


async def test_a_dry_run_counts_and_writes_nothing(raw_collection, composio, capsys) -> None:
    user_id, workflow_id, todo_id = await _seed(raw_collection)

    assert await _run(apply=False) == 0

    assert capsys.readouterr().out == (
        "candidates: workflow_users=1 todo_users=1\ndry run: pass --apply to re-register\n"
    )
    assert composio.created == []
    assert composio.deleted == []
    workflow = await workflow_repository.get_for_user(workflow_id, user_id)
    assert workflow is not None
    assert workflow.trigger_config.composio_trigger_ids == ["ti_old_workflow"]
    todo = await todo_repository.get_by_id(todo_id)
    assert todo is not None
    assert todo.trigger_subscriptions[0].composio_trigger_ids == ["ti_old_todo"]


async def test_apply_moves_each_trigger_onto_its_stored_lead_and_releases_the_old_one(
    raw_collection, composio, capsys
) -> None:
    user_id, workflow_id, todo_id = await _seed(raw_collection)
    await todo_repository.create(_watched_todo(make_user_id(), lead=15))

    assert await _run(apply=True) == 0

    assert sorted(_fire_threshold(c) for c in composio.created) == [15, 30, 60]
    assert sorted(composio.deleted) == ["ti_old_todo", "ti_old_workflow"]
    assert capsys.readouterr().out.splitlines()[-1] == "re-registered: workflow_users=1 todos=2"
    workflow = await workflow_repository.get_for_user(workflow_id, user_id)
    assert workflow is not None
    assert workflow.trigger_config.composio_trigger_ids not in ([], ["ti_old_workflow"])
    todo = await todo_repository.get_by_id(todo_id)
    assert todo is not None
    assert todo.trigger_subscriptions[0].composio_trigger_ids not in ([], ["ti_old_todo"])


async def test_a_second_apply_keeps_every_instance(raw_collection, composio) -> None:
    user_id, workflow_id, todo_id = await _seed(raw_collection)
    await _run(apply=True)
    workflow = await workflow_repository.get_for_user(workflow_id, user_id)
    todo = await todo_repository.get_by_id(todo_id)
    assert workflow is not None
    assert todo is not None
    deleted_after_first = list(composio.deleted)

    await _run(apply=True)

    assert composio.deleted == deleted_after_first
    again = await workflow_repository.get_for_user(workflow_id, user_id)
    assert again is not None
    assert again.trigger_config.composio_trigger_ids == workflow.trigger_config.composio_trigger_ids
    todo_again = await todo_repository.get_by_id(todo_id)
    assert todo_again is not None
    assert (
        todo_again.trigger_subscriptions[0].composio_trigger_ids
        == todo.trigger_subscriptions[0].composio_trigger_ids
    )
