"""The note GAIA writes into a thread when where the user is has changed.

Presence reaches the model only as this one-time note: on the turn the user
switches surface, and once per background run. It is its own HumanMessage in
the CONVERSATION slot, so it is checkpointed inline and later turns still see
it, and it carries PRESENCE_NOTE_MARKER so readers of the user's words skip it.
Times are absolute UTC; the model already gets the current time every turn.
"""

from datetime import UTC, datetime

from langchain_core.messages import HumanMessage

from app.agents.context.section_context import ExecutionMode
from app.agents.context.slots import PRESENCE_NOTE_MARKER, mark
from app.constants.notifications import PRESENCE_ACTIVE_WINDOW_SECONDS
from app.models.chat_models import ConversationSource, SourceCategory
from app.models.presence_models import PresenceSnapshot
from app.services.delivery.chat_channel import ChatChannel, resolve_chat_channel
from app.services.delivery.presence import previous_surface, surfaces_by_recency

_APP_ONLY = "the GAIA app (no chat app linked)"


def _at(epoch: int) -> str:
    """Render an epoch as the note's absolute UTC time."""
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d %H:%M UTC")


def _seen(entries: list[tuple[ConversationSource, int]]) -> str:
    """List surfaces with when the user last wrote on each."""
    return ", ".join(f"{source.display_name} at {_at(at)}" for source, at in entries)


def _destination(target: ChatChannel) -> str:
    """Name the platform a proactive message lands on and the rule that picked it."""
    hours = PRESENCE_ACTIVE_WINDOW_SECONDS // 3600
    if target.basis == "recent_activity":
        return (
            f"{target.source.display_name}, the chat app they last wrote on "
            f"within the past {hours} hours"
        )
    return (
        f"{target.source.display_name}, first in their chat order "
        f"(they have not written on a chat app in the past {hours} hours)"
    )


def _is_live_chat(source: str | None, execution_mode: ExecutionMode) -> bool:
    """Whether the run is a turn the user is sending right now from a real surface."""
    surface = ConversationSource.coerce(source)
    return (
        execution_mode != "background"
        and surface is not None
        and SourceCategory.from_source(surface) is not SourceCategory.BG
    )


def _note_is_due(
    presence: PresenceSnapshot | None, source: str | None, execution_mode: ExecutionMode
) -> bool:
    """Whether this run gets a note: a background run with history, or a live surface switch."""
    if not presence or not surfaces_by_recency(presence):
        return False
    if not _is_live_chat(source, execution_mode):
        return True
    surface = ConversationSource.coerce(source)
    return surface is not None and previous_surface(presence, surface) is not None


def presence_note(
    presence: PresenceSnapshot | None,
    source: str | None,
    execution_mode: ExecutionMode,
    target: ChatChannel | None,
) -> str | None:
    """Return the note for a run, or None when the user's surface did not change."""
    if presence is None or not _note_is_due(presence, source, execution_mode):
        return None
    ranked = surfaces_by_recency(presence)
    surface = ConversationSource.coerce(source)
    if surface is None or not _is_live_chat(source, execution_mode):
        lands = f"goes to {_destination(target)}" if target else f"only shows in {_APP_ONLY}"
        return (
            f"[User presence: not in a chat with you right now. Last seen: {_seen(ranked)}. "
            f"If this run messages the user, it {lands}.]"
        )
    previous = previous_surface(presence, surface)
    if previous is None:
        return None
    seen_at = dict(ranked)
    parts = [
        f"[Surface change: the user is now writing from {surface.display_name}.",
        f"Their previous message was on {previous.display_name} at {_at(seen_at[previous])}.",
    ]
    if others := [entry for entry in ranked if entry[0] not in (surface, previous)]:
        parts.append(f"Also last seen: {_seen(others)}.")
    lands = f"go to {_destination(target)}" if target else f"only show in {_APP_ONLY}"
    parts.append(f"Messages you send on your own (reminders, workflow results, updates) {lands}.]")
    return " ".join(parts)


async def presence_note_message(
    user_id: str | None,
    presence: PresenceSnapshot | None,
    source: str | None,
    execution_mode: ExecutionMode,
) -> HumanMessage | None:
    """Return the marked note message a run's thread gets, or None when nothing changed."""
    # The target lookup is a user read; only a run that gets a note pays for it.
    if not user_id or not _note_is_due(presence, source, execution_mode):
        return None
    text = presence_note(presence, source, execution_mode, await resolve_chat_channel(user_id))
    return mark(HumanMessage(content=text), PRESENCE_NOTE_MARKER) if text else None
