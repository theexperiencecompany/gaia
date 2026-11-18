"""The painting drawn for a framed edition is one its frame can hang."""

import pytest
from tests.factories import make_user_id

from app.constants.briefing import ArtFamily, BriefingBag, EditionFamily
from app.models.brief_composition_models import ChartBlock, ChartKind
from app.models.brief_pool_models import DataSeries, SeriesPoint, SeriesShape
from app.models.user_models import ShuffleBag, UserDocument
from app.services.briefing.edition_draws import draw_edition, draw_from_bag
from app.services.briefing.editions import DAILY_FAMILY_WEIGHTS
from app.services.briefing.editions.artworks import (
    artwork_catalogue,
    artwork_weights,
    artworks_for,
)
from app.services.briefing.editions.capabilities import edition_capabilities

USER_ID = make_user_id()


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
        id=USER_ID,
        email="ada@example.com",
        name="Ada",
        briefing_shuffle_bags={BriefingBag.ARTWORK: bag},
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
class TestDrawEdition:
    def test_a_daily_edition_is_drawn_among_the_families_that_can_draw_its_blocks(
        self,
    ) -> None:
        pool = sorted(f.value for f, n in DAILY_FAMILY_WEIGHTS.items() for _ in range(n))
        pool.remove(EditionFamily.MENU.value)
        bag = ShuffleBag(order=[EditionFamily.MENU.value, *pool], index=0)
        user = UserDocument(
            id=USER_ID,
            email="ada@example.com",
            name="Ada",
            briefing_shuffle_bags={BriefingBag.EDITION_FAMILY: bag},
        )
        chart = ChartBlock(
            chart=ChartKind.LINE,
            title="Meetings",
            takeaway="A busy week",
            series=[
                DataSeries(
                    id="meetings",
                    label="Meetings",
                    source="gaia",
                    app="GAIA",
                    shape=SeriesShape.TIME_SERIES,
                    points=[SeriesPoint(x=f"2026-11-{d:02d}", y=d) for d in range(5, 12)],
                )
            ],
        )

        edition = draw_edition(user, [chart], None)

        assert edition.family is not EditionFamily.MENU
        assert edition_capabilities(edition.family).draws(chart)

    def test_a_daily_edition_is_the_family_its_bag_drew_first(self) -> None:
        user = UserDocument(id=USER_ID, email="ada@example.com", name="Ada")

        edition = draw_edition(user, [], None)

        first = edition.draws[0]
        assert first.bag is BriefingBag.EDITION_FAMILY
        assert edition.family is EditionFamily(first.member)
        assert edition.family in DAILY_FAMILY_WEIGHTS

    def test_a_framed_family_hangs_a_painting_that_fits_its_frame(self) -> None:
        family, unfit = _family_with_a_work_it_cannot_hang()

        edition = draw_edition(_user_whose_bag_opens_on(unfit), [], EditionFamily(family))

        [drawn] = edition.draws
        assert edition.artwork_id == drawn.member
        assert drawn.member in artworks_for(family)
