"""Pure rules and phrasing for telling an agent where the user is and where its messages land."""

from datetime import UTC, datetime

from app.constants.notifications import PRESENCE_ACTIVE_WINDOW_SECONDS
from app.models.agent_config import ExecutionMode
from app.models.chat_models import ConversationSource, SourceCategory
from app.models.presence_models import PresenceSnapshot
from app.services.delivery.chat_channel import ChatChannel, InApp, ProactiveTarget, is_active_place
from app.services.delivery.presence import previous_surface, surfaces_by_recency
from shared.py.analytics.catalog.attribution import EntrySurface


def format_utc(epoch: int) -> str:
    """Render an epoch as an absolute UTC time."""
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d %H:%M UTC")


def describe_last_seen(entries: list[tuple[ConversationSource, int]]) -> str:
    """List surfaces with when the user last wrote on each."""
    return ", ".join(f"{source.display_name} at {format_utc(at)}" for source, at in entries)


def active_window_phrase() -> str:
    """Name the active window the presence rule uses."""
    return f"the past {PRESENCE_ACTIVE_WINDOW_SECONDS // 3600} hours"


def landing_place(target: ProactiveTarget) -> str:
    """Name the one place a target sends to: a chat app, or only the GAIA app."""
    if isinstance(target, ChatChannel):
        return target.source.display_name
    return "the GAIA app only"


def destination_phrase(target: ProactiveTarget) -> str:
    """Where a background run's message lands and the rule that picked it."""
    if target.unreachable_active is not None:
        return (
            f"goes to {landing_place(target)}: they are on {target.unreachable_active.display_name} "
            "right now, which you cannot message on your own"
        )
    match target:
        case ChatChannel(basis="recent_activity"):
            return (
                f"goes to {target.source.display_name}, where they are active "
                f"(they wrote there within {active_window_phrase()})"
            )
        case ChatChannel():
            return (
                f"goes to {target.source.display_name}, first in their chat order "
                f"(not active anywhere in {active_window_phrase()})"
            )
        case InApp(reason="active_in_app"):
            return "stays in the GAIA app, where they are active"
    return "only shows in the GAIA app (no chat app linked)"


#: The messages GAIA sends with nobody asking, as one subject.
_OWN_MESSAGES = "Messages you send on your own (reminders, tracked todo updates, workflow results)"


def own_messages_phrase(target: ProactiveTarget) -> str:
    """Where each kind of message GAIA sends on its own lands, forked as reminder delivery forks on is_active_place."""
    if is_active_place(target):
        if isinstance(target, ChatChannel):
            return (
                f"{_OWN_MESSAGES} go to {target.source.display_name}, where they are active "
                f"(they wrote there within {active_window_phrase()})."
            )
        return f"{_OWN_MESSAGES} stay in the GAIA app, where they are active; nothing goes to a chat app."
    # Nobody reachable is active: reminders return to the chat they were set in.
    unreachable = (
        f"They are on {target.unreachable_active.display_name} right now, which you cannot "
        "message on your own. "
        if target.unreachable_active is not None
        else None
    )
    if isinstance(target, ChatChannel):
        name = target.source.display_name
        return (
            f"{unreachable or 'They are not active anywhere right now. '}Reminders land back in "
            f"the chat they were set in and on {name} too when that chat is not {name}; tracked "
            f"todo updates and workflow results go to {name}, first in their chat order."
        )
    linked = "" if unreachable else " (no chat app linked)"
    return (
        f"{unreachable or ''}Reminders land back in the chat they were set in; tracked todo "
        f"updates and workflow results only show in the GAIA app{linked}."
    )


def is_live_chat(source: str | None, execution_mode: ExecutionMode) -> bool:
    """Whether the run is a turn the user is sending right now from a real surface."""
    surface = ConversationSource.coerce(source)
    return (
        execution_mode != "background"
        and surface is not None
        and SourceCategory.from_source(surface) is not SourceCategory.BG
    )


def is_presence_surface(entry_surface: EntrySurface) -> bool:
    """Whether a turn entering here counts as presence; a call cannot be messaged, so it never does."""
    return entry_surface is not EntrySurface.VOICE


def note_is_due(
    presence: PresenceSnapshot | None,
    source: str | None,
    execution_mode: ExecutionMode,
    opens_thread: bool,
    *,
    entry_surface: EntrySurface,
) -> bool:
    """Whether a run gets a presence note: a background run, a live surface switch, or a thread's first turn."""
    if not presence or not surfaces_by_recency(presence):
        return False
    # A voice call reaches comms as a web turn; it is not one, so it switched nowhere.
    if execution_mode != "background" and not is_presence_surface(entry_surface):
        return False
    if not is_live_chat(source, execution_mode) or opens_thread:
        return True
    surface = ConversationSource.coerce(source)
    return surface is not None and previous_surface(presence, surface) is not None
