"""Draw a brief's edition (its family, stamp and painting) from the user's shuffle bags, and persist the draws once it went out."""

from collections.abc import Mapping, Set
from dataclasses import dataclass, field
import random

from app.constants.briefing import (
    FAVOURITE_WEIGHT_FACTOR,
    ArtFamily,
    BriefingBag,
    EditionChoice,
    EditionFamily,
)
from app.db.repositories.briefing_state import briefing_state_repository
from app.models.brief_composition_models import BriefBlock
from app.models.briefing_state_models import BriefingStateDocument, ShuffleBag
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.artworks import artwork_weights, artworks_for
from app.services.briefing.editions.capabilities import families_drawing, split_drawable
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
    state: BriefingStateDocument,
    bag: BriefingBag,
    weights: Mapping[str, int],
    *,
    eligible: Set[str] | None = None,
) -> BagDraw:
    """Draw today's member from one of the user's shuffle bags, off their loaded state.

    Nothing is persisted here: publish saves the draw only once a pushed brief went out,
    so a failed run does not burn a member of the pass.
    """
    member, next_state = draw(
        state.shuffle_bags.get(bag), weights, random.SystemRandom(), eligible=eligible
    )
    return BagDraw(bag=bag, member=member, next_state=next_state)


def daily_family_weights(choices: Mapping[str, EditionChoice]) -> dict[EditionFamily, int]:
    """Return the user's daily bag: families turned off left out, each favourite at twice its weight.

    Settings keep one family on, so the bag is empty only when every family left on was
    since retired; the brief then draws from every daily family.
    """
    weights = {
        family: weight
        * (FAVOURITE_WEIGHT_FACTOR if choices.get(family) == EditionChoice.FAVOURITE else 1)
        for family, weight in DAILY_FAMILY_WEIGHTS.items()
        if choices.get(family) != EditionChoice.OFF
    }
    if weights:
        return weights
    log.warning("briefing.editions_all_retired", kept=sorted(choices))
    return dict(DAILY_FAMILY_WEIGHTS)


@dataclass(frozen=True)
class EditionDraw:
    """Today's edition: its family, the blocks it draws and leaves to the brief's page, its stamp or painting.

    draws are the bag draws the edition spent, persisted once a pushed brief went out.
    """

    family: EditionFamily
    drawn: list[BriefBlock]
    undrawn: list[BriefBlock]
    stamp_city: str | None = None
    artwork_id: str | None = None
    draws: list[BagDraw] = field(default_factory=list)


def _drawn_family(state: BriefingStateDocument, blocks: list[BriefBlock]) -> BagDraw:
    """Draw today's family from the user's bag, among its families that can draw every block.

    When no family in the user's rotation can draw the whole composition, the bag's next
    family draws and the blocks it cannot draw go to the brief's page; a family the user
    turned off is never drawn.
    """
    weights = daily_family_weights(state.editions)
    fits = families_drawing(weights, blocks)
    # A bag holds its members as the strings briefing_state stores.
    return draw_from_bag(
        state,
        BriefingBag.EDITION_FAMILY,
        {family.value: weight for family, weight in weights.items()},
        eligible={family.value for family in fits} or None,
    )


def draw_edition(
    state: BriefingStateDocument, blocks: list[BriefBlock], fixed_family: EditionFamily | None
) -> EditionDraw:
    """Draw the edition the blocks print in: its family, then its stamp city or its painting.

    The family is fixed for the kind or drawn from the user's bag; an Air Mail edition carries
    a stamp, a framed family a painting.
    """
    family_draws = [] if fixed_family is not None else [_drawn_family(state, blocks)]
    family = fixed_family if fixed_family is not None else EditionFamily(family_draws[0].member)
    drawn, undrawn = split_drawable(family, blocks)
    if undrawn:
        log.info("briefing.blocks_undrawn", family=family, kinds=[b.kind for b in undrawn])
    if family == EditionFamily.POSTAL:
        stamp = draw_from_bag(state, BriefingBag.STAMP_CITY, hosted_stamp_weights())
        return EditionDraw(
            family=family,
            drawn=drawn,
            undrawn=undrawn,
            stamp_city=stamp.member,
            draws=[*family_draws, stamp],
        )
    if family in ArtFamily:
        artwork = draw_from_bag(
            state, BriefingBag.ARTWORK, artwork_weights(), eligible=artworks_for(ArtFamily(family))
        )
        return EditionDraw(
            family=family,
            drawn=drawn,
            undrawn=undrawn,
            artwork_id=artwork.member,
            draws=[*family_draws, artwork],
        )
    return EditionDraw(family=family, drawn=drawn, undrawn=undrawn, draws=family_draws)


async def persist_draws(user_id: str, draws: list[BagDraw]) -> None:
    for bag_draw in draws:
        await briefing_state_repository.set_bag(user_id, bag_draw.bag, bag_draw.next_state)
        log.info(
            "briefing.bag_drawn", user_id=user_id, bag=bag_draw.bag.value, member=bag_draw.member
        )
