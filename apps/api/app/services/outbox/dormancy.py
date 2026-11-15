"""Whether the user has gone away: no sign of presence anywhere for DORMANT_AFTER, whatever GAIA sent them meanwhile."""

from datetime import UTC, datetime, timedelta

from app.constants.outbox_attention import DORMANT_AFTER_SECONDS
from app.db.repositories.conversations import conversation_repository
from app.services.delivery.presence import account_created_since


async def is_dormant(
    user_id: str, last_active_epoch: int | None, account_created_at: datetime | None, now: datetime
) -> bool:
    """Whether the user, last seen at last_active_epoch, has shown no presence and written no message for DORMANT_AFTER.

    An account younger than DORMANT_AFTER is never dormant: it has not existed long enough to go away.

    Presence expires with its stamps, so a user it no longer remembers is checked against the
    messages they wrote too: a lost Redis must not make every user look away.
    """
    cutoff = now - timedelta(seconds=DORMANT_AFTER_SECONDS)
    if account_created_since(account_created_at, cutoff):
        return False
    if last_active_epoch is not None and datetime.fromtimestamp(last_active_epoch, UTC) >= cutoff:
        return False
    return not await conversation_repository.has_user_message_since(user_id, cutoff)
