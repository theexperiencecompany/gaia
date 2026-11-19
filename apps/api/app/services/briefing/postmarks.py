"""Postmarks: the Air Mail city stamps a user has collected from their briefs.

Each Air Mail brief records the city stamp it carried (payload.stamp_city). A
city counts once, on the day its stamp first arrived; that brief's card is the one
the Postmarks page opens.
"""

from app.config.settings import settings
from app.constants.http import API_V1_PREFIX
from app.db.repositories.briefings import briefing_repository
from app.models.brief_payload_models import NewStamp
from app.models.brief_view_models import Postmark, PostmarksResponse
from app.services.briefing.editions.stamps import stamp_catalogue, stamp_weights
from app.services.briefing.view import briefing_card
from shared.py.wide_events import log


def stamp_art_url(slug: str) -> str:
    """Return where a browser loads a city's stamp art: this deployment's own API."""
    return f"{settings.HOST}{API_V1_PREFIX}/briefings/stamps/{slug}.webp"


async def collected_postmarks(user_id: str) -> PostmarksResponse:
    """Return the user's collected stamps, first arrival first, and how many exist."""
    catalogue = stamp_catalogue()
    postmarks: list[Postmark] = []
    for brief in await briefing_repository.list_stamped(user_id):
        slug = brief.payload.stamp_city
        city = catalogue.get(slug) if slug is not None else None
        if slug is None or city is None:
            # a city since dropped from cities.json has no name or place left to show
            log.warning("briefing.postmark_city_unknown", city_slug=slug, briefing_id=brief.id)
            continue
        postmarks.append(
            Postmark(
                city_slug=slug,
                city=city.name,
                country=city.country,
                lat=city.lat,
                lng=city.lng,
                stamp_url=stamp_art_url(slug),
                card=await briefing_card(brief),
            )
        )
    return PostmarksResponse(total=len(stamp_weights()), postmarks=postmarks)


async def new_stamp(user_id: str, slug: str) -> NewStamp | None:
    """Return the stamp as a first arrival, or None when the user already holds this city."""
    collected = {
        brief.payload.stamp_city for brief in await briefing_repository.list_stamped(user_id)
    }
    if slug in collected:
        return None
    city = stamp_catalogue()[slug]
    return NewStamp(
        city=city.name,
        country=city.country,
        collected=len(collected - {None}) + 1,
        total=len(stamp_weights()),
    )
