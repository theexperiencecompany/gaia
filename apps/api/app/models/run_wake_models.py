"""What woke a background run, light enough for the pure conversation core to import.

The names keep their todo wording: they are the logged-entry and screen wire shapes,
and chats moved over from tracked todos still carry them.
"""

from enum import StrEnum

from pydantic import BaseModel


class TodoWakeKind(StrEnum):
    """What woke a run: its schedule, a watched event, or an approval it waited on."""

    SCHEDULE = "schedule"
    TRIGGER = "trigger"
    APPROVAL = "approval"


class TodoRunWake(BaseModel):
    """What woke one background run, shown on the user's side of its chat."""

    kind: TodoWakeKind
    #: The watched events that woke a TRIGGER run, deduplicated and sorted; empty otherwise.
    trigger_names: list[str]
    #: The call the user approved, for an APPROVAL run; None otherwise.
    approval_summary: str | None
