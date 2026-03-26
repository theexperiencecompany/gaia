from collections.abc import Iterator, MutableMapping
from typing import List, Optional
from typing import Annotated

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
    messages: Annotated[List[AnyMessage], add_messages] = Field(default_factory=list)
    current_datetime: Optional[str] = None
    mem0_user_id: Optional[str] = None
    memories: List[str] = Field(default_factory=list)
    memories_stored: bool = False
    conversation_id: Optional[str] = None
