"""Swap the link placeholders a screen's text carries for the user's live links, on the way to a client.

A reply entry keeps the gaia-link: placeholder its model wrote, so a link's URL never enters model
context or a trace; every screen, patch and delta a client or bot renders passes through here.
"""

from collections.abc import Sequence
from typing import TypeVar

from app.models.conversation_screen_models import (
    NoticeItem,
    ScreenFrame,
    ScreenInsertFrame,
    ScreenStreamFrame,
    ScreenUpdateFrame,
)
from app.services.links.placeholders import resolve_link_placeholders
from shared.py.conversation_wire import (
    BubbleTextDelta,
    ReplyDeltaFrame,
    ReplyItem,
    ScreenItemBase,
)

_Item = TypeVar("_Item", bound=ScreenItemBase)


async def shown_item(user_id: str, item: _Item) -> _Item:
    """Return item with every placeholder in its bubbles resolved to the user's live link."""
    bubbles = item.bubbles if isinstance(item, ReplyItem | NoticeItem) else ()
    if not bubbles:
        return item
    resolved = [await resolve_link_placeholders(user_id, bubble) for bubble in bubbles]
    return item.model_copy(update={"bubbles": tuple(resolved)})


async def shown_items(user_id: str, items: Sequence[_Item]) -> list[_Item]:
    """Return items as a client is sent them: placeholders resolved."""
    return [await shown_item(user_id, item) for item in items]


async def shown_frame(user_id: str, frame: ScreenStreamFrame) -> ScreenStreamFrame:
    """Return frame as a client is sent it: the text of its items or reply delta with placeholders resolved."""
    match frame:
        case ScreenFrame(items=items):
            return frame.model_copy(update={"items": tuple(await shown_items(user_id, items))})
        case ScreenInsertFrame(item=item) | ScreenUpdateFrame(item=item):
            return frame.model_copy(update={"item": await shown_item(user_id, item)})
        case ReplyDeltaFrame(payload=BubbleTextDelta(text=text) as delta):
            resolved = await resolve_link_placeholders(user_id, text)
            return frame.model_copy(update={"payload": delta.model_copy(update={"text": resolved})})
        case _:
            return frame
