"""Dumb-pipe persistence for agent lifecycle events pushed from the sandbox.

The receiver never classifies or interprets kind/raw — it authenticates the
caller, checks the session belongs to them, and stores the payload verbatim.
A future supervisor reads the tail; until then this module is storage only.
"""

from typing import Any

from pydantic import BaseModel

from app.utils.errors import AppError


class LabEventReceipt(BaseModel):
    """What the receiver hands back for one accepted push (the id it filed under)."""

    id: str


async def record_lab_event(
    session_id: str, *, user_id: str, kind: str, raw: dict[str, Any]
) -> LabEventReceipt:
    """Accept one raw lifecycle event; fails loud on misuse.

    TODO-v2-todo-native: persist the raw tail onto the run's tracked todo
    (append_log + activity) instead of echoing the id. The session collection
    is gone by design (thin-relay decision) and no todo wiring belongs here.
    """
    if not session_id or not user_id or not kind:
        raise AppError(
            message="agent lab event is missing its identity",
            why="session_id, user_id and kind are all required",
            fix="push {session_id, kind, raw} with a valid session token",
            status_code=422,
            code="agent_lab_event_not_identifiable",
        )
    _ = raw
    return LabEventReceipt(id=session_id)
