from collections.abc import MutableMapping
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

    def __len__(self):
        return len(self.__dict__)


class State(DictLikeModel):
    query: str = ""
    messages: Annotated[List[AnyMessage], add_messages] = Field(default_factory=list)
    current_datetime: Optional[str] = None
    mem0_user_id: Optional[str] = None
    memories: List[str] = Field(default_factory=list)
    memories_stored: bool = False
    conversation_id: Optional[str] = None
