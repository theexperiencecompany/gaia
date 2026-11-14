"""The user's edit to a run watch's gate, as edit_subscription_gate stores or refuses it."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.trigger_gates import GateAuthor
from app.models.todo_models import TodoDocument
from app.models.trigger_gate_models import AuthoredGate, GateEdit
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services.todos.subscription_gate import edit_subscription_gate
from app.utils.errors import AppError

pytestmark = pytest.mark.unit

MODULE = "app.services.todos.subscription_gate"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
TODO_ID = "todo-1"
GAIA_GATE = AuthoredGate(condition="the email is from a customer", author=GateAuthor.GAIA)
TURN_OFF = GateEdit(enabled=False)


def _watch(**overrides: object) -> TriggerSubscription:
    return TriggerSubscription.model_validate(
        {
            "id": "watch-1",
            "trigger_name": "gmail_new_message",
            "action": SubscriptionAction.EXECUTE,
            "resolution": SubscriptionResolution.ACCOUNT,
            "gate": GAIA_GATE,
            **overrides,
        }
    )


def _todo(*watches: TriggerSubscription) -> TodoDocument:
    return TodoDocument(
        id=TODO_ID,
        user_id=USER_ID,
        title="Billing replies",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
        trigger_subscriptions=list(watches),
    )


def _not_found(subscription_id: str) -> AppError:
    return AppError(
        message="Todo watch not found",
        status_code=HTTPStatus.NOT_FOUND,
        code="todo_subscription_not_found",
        meta={"todo_id": TODO_ID, "subscription_id": subscription_id},
    )


@contextmanager
def _stored(
    todo: TodoDocument | None, written: TodoDocument | None = None, open_sub_todos: int = 0
) -> Iterator[AsyncMock]:
    """Serve todo, answer the gate write with written, and count open sub-todos for the owner only."""

    async def count(user_id: str, parent_ids: list[str]) -> dict[str, int]:
        return {TODO_ID: open_sub_todos} if user_id == USER_ID else {}

    with (
        patch(f"{MODULE}.todo_repository.get", new=AsyncMock(return_value=todo)),
        patch(
            f"{MODULE}.todo_repository.set_subscription_gate",
            new=AsyncMock(return_value=written),
        ) as write,
        patch(
            "app.services.todos.todo_service.todo_repository.count_open_sub_todos",
            new=AsyncMock(side_effect=count),
        ),
        patch(
            "app.services.todos.todo_service.pending_approvals_by_owner",
            new=AsyncMock(return_value={}),
        ),
        patch("app.services.triggers.gate_edits.capture"),
    ):
        yield write


class TestRefusals:
    async def test_an_unknown_watch_is_not_found(self) -> None:
        with _stored(_todo(_watch())) as write, pytest.raises(AppError) as refused:
            await edit_subscription_gate(TODO_ID, "watch-2", USER_ID, TURN_OFF)

        assert refused.value == _not_found("watch-2")
        write.assert_not_awaited()

    async def test_a_todo_the_user_does_not_have_is_not_found(self) -> None:
        with _stored(None) as write, pytest.raises(AppError) as refused:
            await edit_subscription_gate(TODO_ID, "watch-1", USER_ID, TURN_OFF)

        assert refused.value == _not_found("watch-1")
        write.assert_not_awaited()

    async def test_a_watch_that_starts_no_run_takes_no_gate(self) -> None:
        notify = _watch(action=SubscriptionAction.NOTIFY, gate=None)

        with _stored(_todo(notify)) as write, pytest.raises(AppError) as refused:
            await edit_subscription_gate(TODO_ID, "watch-1", USER_ID, TURN_OFF)

        assert refused.value == AppError(
            message="Only a watch that runs the todo can have a gate",
            why="a notify watch starts no run, so a gate has nothing to skip",
            fix="edit the gate on the todo's run watch",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            code="gate_needs_a_run",
            meta={"todo_id": TODO_ID, "subscription_id": "watch-1"},
        )
        write.assert_not_awaited()

    async def test_a_watch_gone_before_the_write_is_not_found(self) -> None:
        with _stored(_todo(_watch()), written=None) as write, pytest.raises(AppError) as refused:
            await edit_subscription_gate(TODO_ID, "watch-1", USER_ID, TURN_OFF)

        assert refused.value == _not_found("watch-1")
        write.assert_awaited_once()


class TestTheStoredEdit:
    async def test_the_response_is_the_owners_view_of_the_written_todo(self) -> None:
        off = GAIA_GATE.model_copy(update={"enabled": False})

        with _stored(_todo(_watch()), written=_todo(_watch(gate=off)), open_sub_todos=2):
            response = await edit_subscription_gate(TODO_ID, "watch-1", USER_ID, TURN_OFF)

        assert response.sub_todo_count == 2
        assert response.trigger_subscriptions[0].gate is not None
        assert response.trigger_subscriptions[0].gate.enabled is False
