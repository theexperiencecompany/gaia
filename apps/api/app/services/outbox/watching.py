"""Whether the user is watching a subject live: they wrote on its surface a moment ago."""

from app.constants.outbox import LIVE_WATCH_WINDOW_SECONDS
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import ConversationSource
from app.models.presence_models import PresenceSnapshot
from app.services.delivery.presence import read_presence
from app.services.outbox.models import OutboxReport


async def is_watched_live(report: OutboxReport) -> bool:
    """Return whether the user wrote, within LIVE_WATCH_WINDOW_SECONDS, on the surface the report's subject lives on.

    A chat in the GAIA app is stored without a source and counts as the web surface.
    """
    owner = report.subject.owner_conversation_id
    source = (
        await conversation_repository.get_source(owner, user_id=report.recipient)
        if owner is not None
        else None
    )
    presence: PresenceSnapshot = await read_presence(report.recipient)
    seen_at = presence["last_seen"].get((source or ConversationSource.WEB).value)
    return seen_at is not None and presence["captured_at"] - seen_at <= LIVE_WATCH_WINDOW_SECONDS
