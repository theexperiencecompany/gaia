from collections.abc import Iterator, MutableMapping
from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from pydantic import BaseModel, Field


class DictLikeModel(BaseModel, MutableMapping):
    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __delitem__(self, key):
        delattr(self, key)

    def __iter__(self) -> Iterator[str]:  # type: ignore[override]
        return iter(type(self).model_fields)

    def __len__(self):
        return len(type(self).model_fields)


class State(DictLikeModel):
    query: str = ""
    intent: str | None = None
    messages: Annotated[list[AnyMessage], add_messages] = Field(default_factory=list)
    current_datetime: str | None = None
    mem0_user_id: str | None = None
    memories: list[str] = Field(default_factory=list)
    memories_stored: bool = False
    conversation_id: str | None = None
    integration_usernames: dict[str, str] = Field(default_factory=dict)
    # When set, all canvas writes from this turn default to this todo.
    # Set by scheduled-run trigger or by comms when delegating a todo-bound task.
    active_todo_id: str | None = None
    # "background" means no human is reading this turn (scheduled recurrence).
    # Comms-driven turns are "interactive".
    execution_mode: Literal["interactive", "background"] = "interactive"
