"""Draw a brief's edition family, stamp and painting from the user's shuffle bags, and persist the draws once it went out."""

from collections.abc import Mapping, Set
from dataclasses import dataclass
import random

from app.constants.briefing import (
    POSTAL_FAMILY,
    ArtFamily,
    BriefingBag,
)
from app.db.repositories.users import user_repository
from app.models.briefing_models import (
    BriefingPayload,
)
from app.models.user_models import ShuffleBag, UserDocument
from app.services.briefing.editions.artworks import artwork_weights, artworks_for
from app.services.briefing.editions.stamps import hosted_stamp_weights
from app.services.briefing.shuffle_bag import draw
from shared.py.wide_events import log


@dataclass(frozen=True)
class BagDraw:
    """Today's member of one shuffle bag and the state that continues its pass."""

    bag: BriefingBag
    member: str
    next_state: ShuffleBag


def draw_from_bag(
    user: UserDocument,
    bag: BriefingBag,
    weights: Mapping[str, int],
    *,
    eligible: Set[str] | None = None,
) -> BagDraw:
    """Draw today's member from one of the user's shuffle bags, off the loaded user.

    Nothing is persisted here: publish_brief saves the draw only once the brief went out,
    so a failed run does not burn a member of the pass.
    """
    state = (user.briefing_shuffle_bags or {}).get(bag)
    member, next_state = draw(state, weights, random.SystemRandom(), eligible=eligible)
    return BagDraw(bag=bag, member=member, next_state=next_state)


async def persist_draws(user_id: str, draws: list[BagDraw]) -> None:
    for bag_draw in draws:
        await user_repository.set_briefing_bag(user_id, bag_draw.bag, bag_draw.next_state)
        log.info(
            "briefing.bag_drawn", user_id=user_id, bag=bag_draw.bag.value, member=bag_draw.member
        )


def draw_stamp_or_artwork(user: UserDocument, payload: BriefingPayload) -> list[BagDraw]:
    """Record an Air Mail brief's stamp city, or a framed family's painting, on its payload.

    Returns the stamp or painting draw, persisted once the brief is delivered.
    """
    family = payload.template_family
    if family == POSTAL_FAMILY:
        stamp = draw_from_bag(user, BriefingBag.STAMP_CITY, hosted_stamp_weights())
        payload.stamp_city = stamp.member
        return [stamp]
    if family in ArtFamily:
        artwork = draw_from_bag(
            user, BriefingBag.ARTWORK, artwork_weights(), eligible=artworks_for(ArtFamily(family))
        )
        payload.artwork_id = artwork.member
        return [artwork]
    return []
