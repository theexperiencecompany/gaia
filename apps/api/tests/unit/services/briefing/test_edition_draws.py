"""The painting drawn for a framed edition is one its frame can hang."""

import pytest

from app.constants.briefing import ArtFamily, BriefingBag
from app.models.briefing_models import BriefingPayload
from app.models.user_models import ShuffleBag, UserDocument
from app.services.briefing.edition_draws import draw_from_bag, draw_stamp_or_artwork
from app.services.briefing.editions.artworks import (
    artwork_catalogue,
    artwork_weights,
    artworks_for,
)

_USER = "64f1c0ffee0000000000abcd"


def _family_with_a_work_it_cannot_hang() -> tuple[ArtFamily, str]:
    for family in ArtFamily:
        unfit = sorted(set(artwork_catalogue()) - artworks_for(family))
        if unfit:
            return family, unfit[0]
    pytest.fail("every work fits every frame, so the eligibility draw has nothing to narrow")


def _user_whose_bag_opens_on(slug: str) -> UserDocument:
    rest = sorted(set(artwork_catalogue()) - {slug})
    bag = ShuffleBag(order=[slug, *rest], index=0)
    return UserDocument(
        id=_USER,
        email="ada@example.com",
        name="Ada",
        briefing_shuffle_bags={BriefingBag.ARTWORK: bag},
    )


def _payload(family: str) -> BriefingPayload:
    return BriefingPayload(
        kicker="k",
        date="2026-10-14",
        headline="h",
        lede="l",
        mood="clear",
        caption="c",
        template_family=family,
    )


@pytest.mark.unit
class TestDrawFromBag:
    def test_only_an_eligible_member_is_drawn_and_the_others_keep_their_turn(self) -> None:
        family, unfit = _family_with_a_work_it_cannot_hang()
        user = _user_whose_bag_opens_on(unfit)
        eligible = artworks_for(family)

        drawn = draw_from_bag(user, BriefingBag.ARTWORK, artwork_weights(), eligible=eligible)

        assert drawn.member in eligible
        assert drawn.next_state.index == 1
        assert drawn.next_state.order[drawn.next_state.index :].count(unfit) == 1


@pytest.mark.unit
class TestDrawStampOrArtwork:
    def test_a_framed_family_hangs_a_painting_that_fits_its_frame(self) -> None:
        family, unfit = _family_with_a_work_it_cannot_hang()
        payload = _payload(family.value)

        [drawn] = draw_stamp_or_artwork(_user_whose_bag_opens_on(unfit), payload)

        assert payload.artwork_id == drawn.member
        assert drawn.member in artworks_for(family)
