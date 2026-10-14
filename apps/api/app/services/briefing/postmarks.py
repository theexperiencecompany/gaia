"""Postmarks: the Air Mail city stamps a user has collected from their briefs.

Each Air Mail brief records the city stamp it carried (payload.stamp_city). A
city counts once, on the day its stamp first arrived; that brief is the one the
Postmarks page opens.
"""

from app.db.repositories.briefings import briefing_repository
from app.models.briefing_models import Postmark, PostmarksResponse
from app.services.briefing.editions.stamps import (
    hosted_stamp_weights,
    stamp_asset_url,
    stamp_catalogue,
)


async def collected_postmarks(user_id: str) -> PostmarksResponse:
    """Return the user's collected stamps, first arrival first, and how many exist."""
    catalogue = stamp_catalogue()
    postmarks: dict[str, Postmark] = {}
    for brief in await briefing_repository.list_stamped(user_id):
        slug = brief.payload.stamp_city
        if slug is None or slug in postmarks:
            continue
        city = catalogue[slug]
        postmarks[slug] = Postmark(
            city_slug=slug,
            city=city.name,
            country=city.country,
            lat=city.lat,
            lng=city.lng,
            stamp_url=stamp_asset_url(slug),
            date=brief.date,
            briefing_id=brief.id,
        )
    return PostmarksResponse(total=len(hosted_stamp_weights()), postmarks=list(postmarks.values()))
