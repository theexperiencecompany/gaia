"""Sandbox run events: fire the owning todo's run subscription with the raw event.

Dumb pipe. The run's token already names the run, so the body is never trusted
for identity and never interpreted: it rides along verbatim as the trigger
payload, and the todo run it wakes reads it and decides what to tell the user.
"""

import json
from typing import Final

from pydantic import BaseModel

from app.constants.execute import LAB_EVENT_MAX_RAW_BYTES
from app.db.repositories.todos import todo_repository
from app.decorators.entitlements import SubscriptionRequiredException
from app.services.agent_lab.lab_runs import SANDBOX_RUN_TRIGGER, LabAccess, find_run, lab_access
from app.services.triggers.subscription_dispatch import fire_subscription
from app.utils.errors import AppError
from shared.py.wide_events import log

#: Kind recorded when a body names neither ``kind`` nor ``hook_event_name``.
UNNAMED_EVENT_KIND: Final[str] = "event"


class LabEventReceipt(BaseModel):
    """Where one accepted event was filed."""

    todo_id: str
    kind: str


def _bounded(body: dict[str, object]) -> dict[str, object]:
    """Return body, or its JSON head with the original size when it is past the cap."""
    encoded = json.dumps(body, default=str).encode()
    if len(encoded) <= LAB_EVENT_MAX_RAW_BYTES:
        return body
    log.warning("lab_event body truncated", original_bytes=len(encoded))
    head = encoded[:LAB_EVENT_MAX_RAW_BYTES].decode(errors="ignore")
    return {"truncated_from_bytes": len(encoded), "head": head}


def lab_event_kind(body: dict[str, object]) -> str:
    """Name the event for logs: the plugin's kind, else Claude's hook event name."""
    for key in ("kind", "hook_event_name"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return UNNAMED_EVENT_KIND


async def record_lab_event(
    run_id: str, *, user_id: str, body: dict[str, object]
) -> LabEventReceipt:
    """Wake the todo subscribed to run_id with body attached; fails loud on misuse."""
    access = await lab_access(user_id)
    if access == LabAccess.NOT_PAID:
        raise SubscriptionRequiredException()
    if access == LabAccess.FLAG_OFF:
        raise AppError(
            message="agent lab is disabled for this user",
            why="the AGENT_LAB flag was revoked after the token was minted",
            fix="re-enable the flag, then start a fresh lab run for a live token",
            status_code=403,
            code="agent_lab_disabled",
        )
    candidates = await todo_repository.find_active_by_user_and_trigger(user_id, SANDBOX_RUN_TRIGGER)
    match = find_run(candidates, run_id)
    if match is None:
        raise AppError(
            message="no open tracked todo is watching this sandbox run",
            why=f"run {run_id} has no active subscription; its todo ended or never subscribed",
            fix="launch the run with bash run_todo_id so its todo subscribes to it",
            status_code=404,
            code="agent_lab_run_unknown",
        )
    todo, subscription = match
    kind = lab_event_kind(body)
    await fire_subscription(todo, subscription, {"kind": kind, "event": _bounded(body)})
    return LabEventReceipt(todo_id=todo.id, kind=kind)
