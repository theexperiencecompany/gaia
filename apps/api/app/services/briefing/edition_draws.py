"""Draw a brief's edition family and stamp from the user's shuffle bags, and persist the draws once it went out."""

from collections.abc import Mapping
from dataclasses import dataclass
import random

from app.constants.briefing import (
    POSTAL_FAMILY,
    BriefingBag,
)
from app.db.repositories.users import user_repository
from app.models.briefing_models import (
    BriefingPayload,
)
from app.models.user_models import ShuffleBag, UserDocument
from app.services.briefing.editions.stamps import hosted_stamp_weights
from app.services.briefing.shuffle_bag import draw
from shared.py.wide_events import log


@dataclass(frozen=True)
class BagDraw:
    """Today's member of one shuffle bag and the state that continues its pass."""

    bag: BriefingBag
    member: str
    next_state: ShuffleBag


def draw_from_bag(user: UserDocument, bag: BriefingBag, weights: Mapping[str, int]) -> BagDraw:
    """Draw today's member from one of the user's shuffle bags, off the loaded user.

    Nothing is persisted here: publish_brief saves the draw only once the brief went out,
    so a failed run does not burn a member of the pass.
    """
    state = (user.briefing_shuffle_bags or {}).get(bag)
    member, next_state = draw(state, weights, random.SystemRandom())
    return BagDraw(bag=bag, member=member, next_state=next_state)


async def persist_draws(user_id: str, draws: list[BagDraw]) -> None:
    for bag_draw in draws:
        await user_repository.set_briefing_bag(user_id, bag_draw.bag, bag_draw.next_state)
        log.info(
            "briefing.bag_drawn", user_id=user_id, bag=bag_draw.bag.value, member=bag_draw.member
        )


def draw_stamp(user: UserDocument, payload: BriefingPayload) -> list[BagDraw]:
    """Record an Air Mail brief's stamp city on its payload.

    Returns the stamp draw, persisted once the brief is delivered.
    """
    if payload.template_family != POSTAL_FAMILY:
        return []
    stamp = draw_from_bag(user, BriefingBag.STAMP_CITY, hosted_stamp_weights())
    payload.stamp_city = stamp.member
    return [stamp]
