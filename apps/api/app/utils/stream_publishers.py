"""The todo_progress snapshot a tool streams, as the turn accumulates it per source."""

from pydantic import BaseModel, ConfigDict, Field


class TodoProgressSnapshot(BaseModel):
    """A tool's todo list as of one ``todo_progress`` event, keyed by its ``source``.

    Accumulated per source for the turn and persisted as the ``todo_progress``
    tool_data entry; ``integration_name`` is present only when the emitting
    tool had a label, so it dumps with ``exclude_none``.
    """

    # ``extra="allow"``: the snapshot is persisted exactly as the tool emitted it;
    # only ``source`` is read here, so the rest must survive untouched.
    model_config = ConfigDict(extra="allow")

    todos: list[object] = Field(default_factory=list)
    source: str = "executor"
    integration_name: str | None = None
