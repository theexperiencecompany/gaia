"""Search events."""

from typing import ClassVar, Literal

from shared.py.analytics.catalog.base import ServerEvent, WebEvent
from shared.py.analytics.catalog.properties import Identifier

__all__ = [
    "SearchGlobalOpened",
    "SearchPerformed",
    "SearchResultClicked",
]


class SearchPerformed(ServerEvent):
    """A keyword search over messages, conversations and notes returned results."""

    event: ClassVar[str] = "search:performed"

    mode: Literal["keyword"]
    query_length: int
    result_count: int


class SearchGlobalOpened(WebEvent):
    """A user opened the global command menu."""

    event: ClassVar[str] = "search:global_opened"


class SearchResultClicked(WebEvent):
    """A user picked a conversation or message result in the command menu."""

    event: ClassVar[str] = "search:result_clicked"

    result_type: Literal["conversation", "message"]
    conversation_id: Identifier
    message_id: Identifier | None = None
