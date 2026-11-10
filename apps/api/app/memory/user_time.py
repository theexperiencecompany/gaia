"""Journal-day bucketing on the user's wall clock.

Journal rows keep UTC instants, but the DAY an entry files under — and the
clock time shown next to it — follows the user's home timezone, so a 2am
IST chat lands in the user's today rather than UTC's yesterday.
"""

from datetime import date

from app.services.user_service import get_profile_timezone
from app.utils import clock


async def local_today(user_id: str) -> date:
    """Today's date on the user's wall clock — the journal-day key."""
    return (await get_profile_timezone(user_id)).localize(clock.now()).date()
