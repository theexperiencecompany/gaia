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
from shared.py.wide_events import log


async def resolve_user_timezone(user_id: str) -> Timezone:
    """The user's home timezone from their profile; UTC when missing or invalid.

    Timezone resolution is enrichment: a repository failure (malformed id, an
    infra hiccup) degrades to UTC instead of failing the retain that asked —
    the same trade ``consolidation._get_user_name`` makes for the same lookup.
    """
    try:
        user = await user_repository.get(user_id)
    except Exception as e:
        log.warning(
            "memory_user_timezone_lookup_failed",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return Timezone.utc()
    return Timezone.parse(user.timezone if user else None)


async def local_today(user_id: str) -> date:
    """Today's date on the user's wall clock — the journal-day key."""
    return (await resolve_user_timezone(user_id)).localize(datetime.now(UTC)).date()
