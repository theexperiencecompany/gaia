"""Code shape (first name + suffix) and the first-touch attribution cookie."""

import re

import pytest

from app.constants.referrals import CODE_MAX_LENGTH, ReferralCopyVariant
from app.services.referrals.attribution import ReferralAttribution, first_touch_cookie
from app.services.referrals.codes import mint_code

CODE_SHAPE = re.compile(r"^[a-z]{1,12}-[a-z2-9]{4}$")


@pytest.mark.parametrize(
    ("first_name", "prefix"),
    [
        ("Aryan", "aryan-"),
        ("José", "jose-"),
        ("Mary-Kate O'Neil", "marykateonei-"),
        ("李", "friend-"),
        (None, "friend-"),
    ],
)
def test_a_code_is_the_ascii_first_name_and_a_short_suffix(
    first_name: str | None, prefix: str
) -> None:
    code = mint_code(first_name)

    assert code.startswith(prefix)
    assert CODE_SHAPE.match(code)
    assert len(code) <= CODE_MAX_LENGTH


def test_codes_for_one_name_differ() -> None:
    assert len({mint_code("Aryan") for _ in range(50)}) > 40


def test_the_cookie_round_trips_code_and_landing_variant() -> None:
    clicked = ReferralAttribution(code="aryan-k7f2", landing_variant=ReferralCopyVariant.TIME_BACK)

    assert ReferralAttribution.from_cookie(clicked.cookie_value()) == clicked
    assert ReferralAttribution.from_cookie("aryan-k7f2") == ReferralAttribution(code="aryan-k7f2")


@pytest.mark.parametrize("raw", [None, "", "x" * (CODE_MAX_LENGTH + 1)])
def test_a_missing_or_malformed_cookie_attributes_nothing(raw: str | None) -> None:
    assert ReferralAttribution.from_cookie(raw) is None


def test_an_unknown_variant_keeps_the_code_and_drops_the_variant() -> None:
    assert ReferralAttribution.from_cookie("aryan-k7f2.bogus") == ReferralAttribution(
        code="aryan-k7f2"
    )


class TestFirstTouch:
    def test_the_first_valid_click_sets_the_cookie(self) -> None:
        clicked = ReferralAttribution(code="aryan-k7f2")
        assert first_touch_cookie(None, clicked, valid=True) == "aryan-k7f2"

    def test_a_later_click_never_replaces_the_first(self) -> None:
        later = ReferralAttribution(code="priya-ab23")
        assert first_touch_cookie("aryan-k7f2", later, valid=True) is None

    def test_an_invalid_code_sets_nothing(self) -> None:
        assert (
            first_touch_cookie(None, ReferralAttribution(code="nobody-zzzz"), valid=False) is None
        )
