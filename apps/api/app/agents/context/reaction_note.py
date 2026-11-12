"""The note telling comms it already reacted to the user's message.

The instant reaction runs beside context assembly. The note is written only when
that reaction had already landed when comms' input was built, so building never
waits for it; a reaction still deciding simply goes unmentioned.
"""

import asyncio

from langchain_core.messages import HumanMessage

from app.agents.context.slots import REACTION_NOTE_MARKER, mark
from app.constants.reactions import REACTION_NOTE_TEMPLATE


def reaction_note_message(instant_reaction: asyncio.Task[str | None] | None) -> HumanMessage | None:
    """Return the marked note for an instant reaction already placed, or None."""
    if instant_reaction is None or not instant_reaction.done() or instant_reaction.cancelled():
        return None
    # react_instantly records its own failures; a failed one is simply no reaction here.
    if instant_reaction.exception() is not None:
        return None
    emoji = instant_reaction.result()
    if emoji is None:
        return None
    return mark(
        HumanMessage(content=REACTION_NOTE_TEMPLATE.format(emoji=emoji)), REACTION_NOTE_MARKER
    )
