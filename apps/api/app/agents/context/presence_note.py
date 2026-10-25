"""The note GAIA writes into a thread when where the user is has changed.

Presence reaches the model only as this one-time note: on the turn the user
switches surface, on the first turn of a conversation, and once per background
run. It is its own HumanMessage in
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
from app.services.delivery.chat_channel import (
    ChatChannel,
    InApp,
    ProactiveTarget,
    resolve_proactive_target,
)
from app.services.delivery.presence import previous_surface, surfaces_by_recency


def _at(epoch: int) -> str:
    """Render an epoch as the note's absolute UTC time."""
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d %H:%M UTC")


def _seen(entries: list[tuple[ConversationSource, int]]) -> str:
    """List surfaces with when the user last wrote on each."""
    return ", ".join(f"{source.display_name} at {_at(at)}" for source, at in entries)


def _active_window() -> str:
    """Name the active window the presence rule uses."""
    return f"the past {PRESENCE_ACTIVE_WINDOW_SECONDS // 3600} hours"


def _destination(target: ProactiveTarget) -> str:
    """Where a background run's message lands and the rule that picked it."""
    match target:
        case ChatChannel(basis="recent_activity"):
            return (
                f"goes to {target.source.display_name}, where they are active "
                f"(they wrote there within {_active_window()})"
            )
        case ChatChannel():
            return (
                f"goes to {target.source.display_name}, first in their chat order "
                f"(not active anywhere in {_active_window()})"
            )
        case InApp(reason="active_in_app"):
            return "stays in the GAIA app, where they are active"
    return "only shows in the GAIA app (no chat app linked)"


def _own_messages(target: ProactiveTarget) -> str:
    """Where each kind of message GAIA sends on its own lands, as reminder_tasks and todo delivery route them."""
    kinds = "Messages you send on your own (reminders, tracked todo updates, workflow results)"
    match target:
        case ChatChannel(basis="recent_activity"):
            return (
                f"{kinds} go to {target.source.display_name}, where they are active "
                f"(they wrote there within {_active_window()})."
            )
        case ChatChannel():
            name = target.source.display_name
            return (
                "They are not active anywhere right now: reminders land back in the chat they "
                f"were set in and on {name} too when that chat is not {name}; tracked todo "
                f"updates and workflow results go to {name}, first in their chat order."
            )
        case InApp(reason="active_in_app"):
            return (
                f"{kinds} stay in the GAIA app, where they are active; nothing goes to a chat app."
            )
    return (
        "Reminders land back in the chat they were set in; tracked todo updates and "
        "workflow results only show in the GAIA app (no chat app linked)."
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
    presence: PresenceSnapshot | None,
    source: str | None,
    execution_mode: ExecutionMode,
    opens_thread: bool,
) -> bool:
    """Whether this run gets a note: a background run, a live surface switch, or a thread's first turn."""
    if not presence or not surfaces_by_recency(presence):
        return False
    if not _is_live_chat(source, execution_mode) or opens_thread:
        return True
    surface = ConversationSource.coerce(source)
    return surface is not None and previous_surface(presence, surface) is not None


def presence_note(
    presence: PresenceSnapshot | None,
    source: str | None,
    execution_mode: ExecutionMode,
    target: ProactiveTarget,
    *,
    opens_thread: bool,
) -> str | None:
    """Return the note for a run, or None when nothing changed for this thread."""
    if presence is None or not _note_is_due(presence, source, execution_mode, opens_thread):
        return None
    ranked = surfaces_by_recency(presence)
    surface = ConversationSource.coerce(source)
    if surface is None or not _is_live_chat(source, execution_mode):
        return (
            f"[User presence: not in a chat with you right now. Last seen: {_seen(ranked)}. "
            f"If this run messages the user, it {_destination(target)}.]"
        )
    previous = previous_surface(presence, surface)
    seen_at = dict(ranked)
    if previous is not None:
        parts = [
            f"[Surface change: the user is now writing from {surface.display_name}.",
            f"Their previous message was on {previous.display_name} at {_at(seen_at[previous])}.",
        ]
    else:
        parts = [f"[User presence: the user is writing from {surface.display_name}."]
    if others := [entry for entry in ranked if entry[0] not in (surface, previous)]:
        parts.append(f"Also last seen: {_seen(others)}.")
    parts.append(f"{_own_messages(target)}]")
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
    if not user_id or not _note_is_due(presence, source, execution_mode, opens_thread):
        return None
    target = await resolve_proactive_target(user_id)
    text = presence_note(presence, source, execution_mode, target, opens_thread=opens_thread)
    return mark(HumanMessage(content=text), PRESENCE_NOTE_MARKER) if text else None
