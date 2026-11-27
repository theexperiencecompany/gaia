"""The re-registration script moves stored calendar triggers onto Composio's fire-threshold config."""

from collections.abc import Iterator
from datetime import UTC, datetime
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid

import pytest

from app.constants.integrations import IntegrationStatus
from app.core.lazy_loader import providers
from app.db.repositories.todos import todo_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.db.repositories.workflows import workflow_repository
from app.models.composio_schemas import GoogleCalendarEventStartingSoonTriggerConfig
from app.models.integration_models import IntegrationAccount
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
def composio(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeComposio]:
    """Fake only the SDK client: the script's own boot must register and resolve the provider."""
    fake = _FakeComposio()
    monkeypatch.setattr(providers, "_providers", {})
    monkeypatch.setattr(providers, "_auto_init_providers", set())
    with (
        patch("app.services.composio.composio_service.ComposioService", return_value=fake),
        patch("app.services.composio.composio_service._composio_api_key", return_value="test-key"),
    ):
        yield fake


async def _connect_calendar(user_id: str) -> None:
    await user_integration_repository.save_accounts(
        user_id,
        "googlecalendar",
        accounts=[IntegrationAccount(id="acct-1", connected_account_id="ca_primary", label="work")],
        primary_account_id="acct-1",
        status=IntegrationStatus.CONNECTED,
    )


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
    await _connect_calendar(user_id)
    workflow = _workflow(user_id, lead=60)
    await raw_collection.insert_one(workflow)
    todo = await todo_repository.create(_watched_todo(user_id, lead=30))
    return user_id, str(workflow["_id"]), todo.id


def _fire_threshold(config: dict[str, object]) -> int:
    return GoogleCalendarEventStartingSoonTriggerConfig.model_validate(config).minutes_before_start


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
    second_owner = make_user_id()
    await _connect_calendar(second_owner)
    await todo_repository.create(_watched_todo(second_owner, lead=15))

    assert await _run(apply=True) == 0

    assert sorted(_fire_threshold(c) for c in composio.created) == [15, 30, 60]
    assert {frozenset(c) for c in composio.created} == {
        frozenset(
            {"calendarId", "minutes_before_start", "countdown_window_minutes", "include_all_day"}
        )
    }
    assert sorted(composio.deleted) == ["ti_old_todo", "ti_old_workflow"]
    assert capsys.readouterr().out.splitlines()[-2:] == [
        "workflows: moved=1 unchanged=0 failed=0",
        "todos: moved=2 unchanged=0 failed=0",
    ]
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

    assert await _run(apply=True) == 0

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


async def test_an_owner_who_cannot_register_is_reported_and_fails_the_run(
    raw_collection, composio, capsys
) -> None:
    user_id, workflow_id, _todo_id = await _seed(raw_collection)
    unconnected = _workflow(make_user_id(), lead=60)
    await raw_collection.insert_one(unconnected)

    assert await _run(apply=True) == 1

    out = capsys.readouterr().out.splitlines()
    assert "workflows: moved=1 unchanged=0 failed=1" in out
    assert f"  failed workflows: {unconnected['_id']}" in out
    moved = await workflow_repository.get_for_user(workflow_id, user_id)
    assert moved is not None
    assert moved.trigger_config.composio_trigger_ids != ["ti_old_workflow"]
