"""What woke a tracked todo's run, light enough for the pure conversation core to import."""

from pydantic import BaseModel

from app.constants.todos import TodoWakeKind


class TodoRunWake(BaseModel):
    """What woke one run of a tracked todo, shown on the user's side of its chat."""

    kind: TodoWakeKind
    #: The watched events that woke a TRIGGER run, deduplicated and sorted; empty otherwise.
    trigger_names: list[str]
    #: The call the user approved, for an APPROVAL run; None otherwise.
    approval_summary: str | None
