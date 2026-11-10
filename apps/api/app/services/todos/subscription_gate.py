"""The user's edit to the gate on one of a tracked todo's watches."""

from http import HTTPStatus

from app.constants.trigger_gates import GateOwner
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoResponse
from app.models.trigger_gate_models import GateEdit
from app.models.trigger_subscription_models import SubscriptionAction
from app.services.todos.todo_service import todo_responses
from app.services.triggers.gate_edits import apply_gate_edit, report_gate_edit
from app.utils.errors import AppError


def _watch_not_found(todo_id: str, subscription_id: str) -> AppError:
    return AppError(
        message="Todo watch not found",
        status_code=HTTPStatus.NOT_FOUND,
        code="todo_subscription_not_found",
        meta={"todo_id": todo_id, "subscription_id": subscription_id},
    )


async def edit_subscription_gate(
    todo_id: str, subscription_id: str, user_id: str, edit: GateEdit
) -> TodoResponse:
    """Store the user's edit to one run watch's gate and return the todo as the API shows it."""
    todo = await todo_repository.get(todo_id, user_id=user_id)
    watch = (
        next((w for w in todo.trigger_subscriptions if w.id == subscription_id), None)
        if todo
        else None
    )
    if watch is None:
        raise _watch_not_found(todo_id, subscription_id)
    if watch.action is not SubscriptionAction.EXECUTE:
        raise AppError(
            message="Only a watch that runs the todo can have a gate",
            why=f"a {watch.action.value} watch starts no run, so a gate has nothing to skip",
            fix="edit the gate on the todo's run watch",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            code="gate_needs_a_run",
            meta={"todo_id": todo_id, "subscription_id": subscription_id},
        )
    gate = apply_gate_edit(watch.gate, edit)
    written = await todo_repository.set_subscription_gate(
        todo_id, user_id=user_id, subscription_id=subscription_id, gate=gate
    )
    if written is None:
        raise _watch_not_found(todo_id, subscription_id)
    report_gate_edit(user_id, GateOwner.TODO, watch.gate, gate)
    (response,) = await todo_responses(user_id, [written])
    return response
