"""Pure rules and phrasing for telling an agent where the user is and where its messages land."""

from datetime import UTC, datetime

from app.constants.notifications import PRESENCE_ACTIVE_WINDOW_SECONDS
from app.models.agent_config import ExecutionMode
from app.models.chat_models import ConversationSource, SourceCategory
from app.models.presence_models import PresenceSnapshot
from app.services.delivery.chat_channel import ChatChannel, InApp, ProactiveTarget
from app.services.delivery.presence import previous_surface, surfaces_by_recency


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


def own_messages_phrase(target: ProactiveTarget) -> str:
    """Where each kind of message GAIA sends on its own lands, as reminder_tasks and todo delivery route them."""
    kinds = "Messages you send on your own (reminders, tracked todo updates, workflow results)"
    # The user is on a chat app that cannot be messaged: say so, then route as for nobody active.
    idle = (
        f"They are on {target.unreachable_active.display_name} right now, which you cannot "
        "message on your own: "
        if target.unreachable_active is not None
        else "They are not active anywhere right now: "
    )
    match target:
        case ChatChannel(basis="recent_activity"):
            return (
                f"{kinds} go to {target.source.display_name}, where they are active "
                f"(they wrote there within {active_window_phrase()})."
            )
        case ChatChannel():
            name = target.source.display_name
            return (
                f"{idle}reminders land back in the chat they were set in and on {name} too "
                f"when that chat is not {name}; tracked todo updates and workflow results go "
                f"to {name}, first in their chat order."
            )
        case InApp(reason="active_in_app"):
            return (
                f"{kinds} stay in the GAIA app, where they are active; nothing goes to a chat app."
            )
    linked = "" if target.unreachable_active is not None else " (no chat app linked)"
    lead = idle if target.unreachable_active is not None else ""
    return (
        f"{lead}{'r' if lead else 'R'}eminders land back in the chat they were set in; tracked "
        f"todo updates and workflow results only show in the GAIA app{linked}."
    )


def is_live_chat(source: str | None, execution_mode: ExecutionMode) -> bool:
    """Whether the run is a turn the user is sending right now from a real surface."""
    surface = ConversationSource.coerce(source)
    return (
        execution_mode != "background"
        and surface is not None
        and SourceCategory.from_source(surface) is not SourceCategory.BG
    )


def note_is_due(
    presence: PresenceSnapshot | None,
    source: str | None,
    execution_mode: ExecutionMode,
    opens_thread: bool,
) -> bool:
    """Whether a run gets a presence note: a background run, a live surface switch, or a thread's first turn."""
    if not presence or not surfaces_by_recency(presence):
        return False
    if not is_live_chat(source, execution_mode) or opens_thread:
        return True
    surface = ConversationSource.coerce(source)
    return surface is not None and previous_surface(presence, surface) is not None
