"""Dev-only seeding of past Air Mail briefs, so the Postmarks page has stamps to show.

Writes through the real briefings repository, one delivered postal brief per day
ending on a fixed date, each carrying a distinct catalogued city stamp. Fixed dates
key the (user, date, kind) upsert, so a re-run on any day rewrites the same rows.
"""

from datetime import date, timedelta

from app.constants.briefing import BRIEFING_KIND_DAILY, POSTAL_FAMILY
from app.constants.notifications import NotificationChannel
from app.db.repositories.briefings import briefing_repository
from app.models.briefing_models import (
    BriefingItem,
    BriefingPayload,
    BriefingSection,
)
from app.models.user_models import UserDocument
from app.services.briefing.editions.stamps import hosted_stamp_weights, stamp_catalogue
from app.utils.errors import create_error

_SEEDED_CHANNELS: list[str] = [NotificationChannel.INAPP.value, NotificationChannel.EMAIL.value]
# Anchored, not today-relative: a today-relative range would add a brief on every new day.
_LAST_SEEDED_DATE = date(2026, 10, 1)


async def seed_dev_postmarks(user: UserDocument, count: int) -> None:
    """Upsert count delivered postal briefs on consecutive days, one city stamp each."""
    cities = sorted(hosted_stamp_weights())
    if count > len(cities):
        raise create_error(
            message=f"Cannot seed {count} postmarks",
            why=f"only {len(cities)} city stamps have hosted art",
            fix=f"ask for at most {len(cities)}",
            status_code=400,
        )
    catalogue = stamp_catalogue()
    for days_before, slug in enumerate(cities[:count]):
        day = (_LAST_SEEDED_DATE - timedelta(days=days_before)).isoformat()
        city = catalogue[slug]
        payload = BriefingPayload(
            kicker="AIR MAIL",
            date=day,
            headline=f"A letter from {city.name}",
            lede=f"Sample brief seeded for the Postmarks page, stamped {city.name}, {city.country}.",
            sections=[
                BriefingSection(
                    numeral="I",
                    title="Sample",
                    items=[BriefingItem(text="Seeded by POST /dev/seed", kind="note")],
                )
            ],
            mood="clear",
            caption="Onward.",
            template_family=POSTAL_FAMILY,
            stamp_city=slug,
            recipient_name=user.name,
        )
        await briefing_repository.upsert_briefing(
            user.id, day, BRIEFING_KIND_DAILY, payload, edition_image_url=None
        )
        await briefing_repository.set_delivered_channels(
            user.id, day, BRIEFING_KIND_DAILY, _SEEDED_CHANNELS
        )
