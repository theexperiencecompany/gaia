"""The note GAIA writes into a thread when where the user is has changed.

Presence reaches the model only as this one-time note: on the turn the user
switches surface, on the first turn of a conversation, and once per background
run. It is its own HumanMessage in
the CONVERSATION slot, so it is checkpointed inline and later turns still see
it, and it carries PRESENCE_NOTE_MARKER so readers of the user's words skip it.
Times are absolute UTC; the model already gets the current time every turn.
"""

from langchain_core.messages import HumanMessage

from app.agents.context.section_context import ExecutionMode
from app.agents.context.slots import PRESENCE_NOTE_MARKER, mark
from app.models.chat_models import ConversationSource
from app.models.presence_models import PresenceSnapshot
from app.services.delivery.chat_channel import ProactiveTarget, resolve_proactive_target
from app.services.delivery.presence import previous_surface, surfaces_by_recency
from app.utils.presence_utils import (
    describe_last_seen,
    destination_phrase,
    format_utc,
    is_live_chat,
    note_is_due,
    own_messages_phrase,
)


def presence_note(
    presence: PresenceSnapshot,
    source: str | None,
    execution_mode: ExecutionMode,
    target: ProactiveTarget,
) -> str:
    """Return the note text for a run whose gate (note_is_due) has already passed."""
    ranked = surfaces_by_recency(presence)
    surface = ConversationSource.coerce(source)
    if surface is None or not is_live_chat(source, execution_mode):
        return (
            "[User presence: not in a chat with you right now. "
            f"Last seen: {describe_last_seen(ranked)}. "
            f"If this run messages the user, it {destination_phrase(target)}.]"
        )
    previous = previous_surface(presence, surface)
    seen_at = dict(ranked)
    if previous is not None:
        parts = [
            f"[Surface change: the user is now writing from {surface.display_name}.",
            f"Their previous message was on {previous.display_name} "
            f"at {format_utc(seen_at[previous])}.",
        ]
    else:
        parts = [f"[User presence: the user is writing from {surface.display_name}."]
    if others := [entry for entry in ranked if entry[0] not in (surface, previous)]:
        parts.append(f"Also last seen: {describe_last_seen(others)}.")
    parts.append(f"{own_messages_phrase(target)}]")
    return " ".join(parts)


async def presence_note_message(
    user_id: str | None,
    presence: PresenceSnapshot | None,
    source: str | None,
    execution_mode: ExecutionMode,
    *,
    opens_thread: bool,
) -> HumanMessage | None:
    """Return the marked note message a run's thread gets, or None when nothing changed."""
    # The target lookup is a user read; only a run that gets a note pays for it.
    if (
        not user_id
        or presence is None
        or not note_is_due(presence, source, execution_mode, opens_thread)
    ):
        return None
    target = await resolve_proactive_target(user_id)
    text = presence_note(presence, source, execution_mode, target)
    return mark(HumanMessage(content=text), PRESENCE_NOTE_MARKER)
