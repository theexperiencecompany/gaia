"""Code shape (first name + suffix), minting it once per user, and the first-touch attribution cookie."""

from datetime import UTC, datetime
import re
from unittest.mock import AsyncMock, call, patch

from pymongo.errors import DuplicateKeyError
import pytest

from app.config.settings import settings
from app.constants.referrals import (
    CODE_MAX_LENGTH,
    CODE_MINT_ATTEMPTS,
    ReferralCopyVariant,
    ReferralSource,
)
from app.models.referral_models import ReferralCodeDocument
from app.models.user_models import UserDocument
from app.services.referrals.attribution import ReferralAttribution, first_touch_cookie
from app.services.referrals.codes import (
    ensure_code,
    first_name_of,
    load_user,
    mint_code,
    share_link,
)
from app.utils.errors import AppError
from tests.helpers import captured_wide_event

CODES = "app.services.referrals.codes"

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


@pytest.mark.parametrize(
    "clicked",
    [
        ReferralAttribution(code="aryan-k7f2", source=ReferralSource.WORKFLOW),
        ReferralAttribution(
            code="aryan-k7f2",
            landing_variant=ReferralCopyVariant.GIFT,
            source=ReferralSource.WORKFLOW,
        ),
    ],
)
def test_the_cookie_round_trips_a_workflow_source(clicked: ReferralAttribution) -> None:
    assert ReferralAttribution.from_cookie(clicked.cookie_value()) == clicked


def test_an_invite_link_cookie_keeps_its_original_shape() -> None:
    assert ReferralAttribution(code="aryan-k7f2").cookie_value() == "aryan-k7f2"
    assert (
        ReferralAttribution(
            code="aryan-k7f2", landing_variant=ReferralCopyVariant.GIFT
        ).cookie_value()
        == "aryan-k7f2.gift"
    )


def test_an_unknown_source_falls_back_to_the_invite_link() -> None:
    assert ReferralAttribution.from_cookie("aryan-k7f2..bogus") == ReferralAttribution(
        code="aryan-k7f2"
    )


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


@pytest.mark.parametrize(
    ("first_name", "name", "expected"),
    [
        ("Priya", "Priya Shah", "Priya"),
        (None, "Aryan Randeriya", "Aryan"),
        (None, "   ", None),
        (None, None, None),
    ],
)
def test_a_friend_knows_a_user_by_their_first_name(
    first_name: str | None, name: str | None, expected: str | None
) -> None:
    assert first_name_of(UserDocument(id="u", first_name=first_name, name=name)) == expected


def test_a_code_is_shared_as_the_frontend_invite_link() -> None:
    assert share_link("aryan-k7f2") == f"{settings.FRONTEND_URL}/invite/aryan-k7f2"


async def test_a_session_whose_user_is_gone_is_a_404() -> None:
    with (
        patch(f"{CODES}.user_repository.get", AsyncMock(return_value=None)) as get,
        pytest.raises(AppError) as missing,
    ):
        await load_user("u-gone")

    get.assert_awaited_once_with("u-gone")
    assert missing.value.status_code == 404
    assert missing.value.to_dict() == {"message": "User not found", "user_id": "u-gone"}


async def test_a_user_who_exists_is_loaded() -> None:
    user = UserDocument(id="u-1")
    with patch(f"{CODES}.user_repository.get", AsyncMock(return_value=user)):
        assert await load_user("u-1") is user


class TestEnsureCode:
    USER = UserDocument(id="u-1", first_name="Aryan")

    @staticmethod
    def _code(code: str) -> ReferralCodeDocument:
        return ReferralCodeDocument(user_id="u-1", code=code, created_at=datetime.now(UTC))

    async def test_an_existing_code_is_returned_unchanged(self) -> None:
        with (
            patch(
                f"{CODES}.referral_code_repository.get_for_user",
                AsyncMock(return_value=self._code("aryan-k7f2")),
            ) as get_for_user,
            patch(f"{CODES}.referral_code_repository.create", AsyncMock()) as create,
        ):
            assert await ensure_code(self.USER) == "aryan-k7f2"

        get_for_user.assert_awaited_once_with("u-1")
        create.assert_not_awaited()

    async def test_a_first_ask_mints_and_stores_a_code_for_the_user(self) -> None:
        create = AsyncMock(side_effect=lambda doc: doc)
        with (
            patch(f"{CODES}.referral_code_repository.get_for_user", AsyncMock(return_value=None)),
            patch(f"{CODES}.referral_code_repository.create", create),
        ):
            async with captured_wide_event() as event:
                code = await ensure_code(self.USER)

        (stored,) = [c.args[0] for c in create.await_args_list]
        assert (stored.user_id, stored.code) == ("u-1", code)
        assert stored.created_at.tzinfo is UTC
        assert code.startswith("aryan-")
        assert event["referral"]["code_minted"] is True

    async def test_a_racing_mint_for_the_same_user_returns_the_winners_code(self) -> None:
        with (
            patch(
                f"{CODES}.referral_code_repository.get_for_user",
                AsyncMock(side_effect=[None, self._code("aryan-win1")]),
            ) as get_for_user,
            patch(
                f"{CODES}.referral_code_repository.create",
                AsyncMock(side_effect=DuplicateKeyError("dup")),
            ) as create,
        ):
            assert await ensure_code(self.USER) == "aryan-win1"

        assert create.await_count == 1
        assert get_for_user.await_args_list == [call("u-1"), call("u-1")]

    async def test_a_clashing_suffix_is_retried_with_a_fresh_one(self) -> None:
        create = AsyncMock(side_effect=[DuplicateKeyError("dup"), self._code("aryan-ok22")])
        with (
            patch(f"{CODES}.referral_code_repository.get_for_user", AsyncMock(return_value=None)),
            patch(f"{CODES}.referral_code_repository.create", create),
        ):
            assert await ensure_code(self.USER) == "aryan-ok22"

        assert create.await_count == 2

    async def test_every_suffix_taken_is_a_500_naming_the_user(self) -> None:
        create = AsyncMock(side_effect=DuplicateKeyError("dup"))
        with (
            patch(f"{CODES}.referral_code_repository.get_for_user", AsyncMock(return_value=None)),
            patch(f"{CODES}.referral_code_repository.create", create),
            pytest.raises(AppError) as exhausted,
        ):
            await ensure_code(self.USER)

        assert create.await_count == CODE_MINT_ATTEMPTS
        assert exhausted.value.status_code == 500
        assert exhausted.value.to_dict() == {
            "message": "Could not create a referral code",
            "why": f"{CODE_MINT_ATTEMPTS} random suffixes in a row were already taken",
            "user_id": "u-1",
        }
