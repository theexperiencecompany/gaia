"""Journal-day bucketing on the user's wall clock.

Journal rows keep UTC instants, but the DAY an entry files under — and the
clock time shown next to it — follows the user's home timezone, so a 2am
IST chat lands in the user's today rather than UTC's yesterday. A missing
or invalid stored timezone falls back to UTC (``Timezone.parse`` logs a
warning for an unrecognized value instead of raising), so a bad preference
can never crash ingestion.
"""

from datetime import UTC, date, datetime

from app.db.repositories.users import user_repository
from app.utils.timezone import Timezone


async def resolve_user_timezone(user_id: str) -> Timezone:
    """The user's home timezone from their profile; UTC when missing or invalid."""
    user = await user_repository.get(user_id)
    return Timezone.parse(user.timezone if user else None)


async def local_today(user_id: str) -> date:
    """Today's date on the user's wall clock — the journal-day key."""
    return (await resolve_user_timezone(user_id)).localize(datetime.now(UTC)).date()
