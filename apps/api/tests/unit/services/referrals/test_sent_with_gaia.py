"""The Sent with GAIA line signs mail only for a subscriber who turned it on."""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from app.models.user_models import OnboardingPreferences, OnboardingSubdocument, UserDocument
from app.services.referrals.codes import share_link
from app.services.referrals.sent_with_gaia import sent_with_gaia_link

MODULE = "app.services.referrals.sent_with_gaia"


def _user(sent_with_gaia: bool | None) -> UserDocument:
    return UserDocument(
        id="64a0000000000000000000a1",
        first_name="Aryan",
        onboarding=OnboardingSubdocument(
            preferences=OnboardingPreferences(sent_with_gaia=sent_with_gaia)
        ),
    )


@dataclass
class Seams:
    load_user: AsyncMock
    subscription: AsyncMock
    ensure_code: AsyncMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    with (
        patch(f"{MODULE}.load_user", AsyncMock(return_value=_user(True))) as load_user,
        patch(
            f"{MODULE}.subscription_repository.get_active_for_user",
            AsyncMock(return_value=object()),
        ) as subscription,
        patch(f"{MODULE}.ensure_code", AsyncMock(return_value="aryan-k7f2")) as ensure_code,
    ):
        yield Seams(load_user, subscription, ensure_code)


async def test_a_subscriber_who_turned_it_on_signs_with_their_invite_link(
    seams: Seams,
) -> None:
    assert await sent_with_gaia_link("64a0000000000000000000a1") == share_link("aryan-k7f2")

    seams.load_user.assert_awaited_once_with("64a0000000000000000000a1")
    seams.subscription.assert_awaited_once_with("64a0000000000000000000a1")
    assert seams.ensure_code.await_args.args[0].id == "64a0000000000000000000a1"


@pytest.mark.parametrize(
    "user",
    [
        _user(False),
        _user(None),
        UserDocument(id="64a0000000000000000000a1", onboarding=OnboardingSubdocument()),
        UserDocument(id="64a0000000000000000000a1"),
    ],
    ids=["turned-off", "never-chose", "no-preferences", "never-onboarded"],
)
async def test_without_the_setting_on_mail_goes_out_unsigned(
    seams: Seams, user: UserDocument
) -> None:
    seams.load_user.return_value = user

    assert await sent_with_gaia_link(user.id) is None
    seams.subscription.assert_not_awaited()


async def test_a_lapsed_subscriber_has_no_link_to_sign_with(seams: Seams) -> None:
    seams.subscription.return_value = None

    assert await sent_with_gaia_link("64a0000000000000000000a1") is None
    seams.ensure_code.assert_not_awaited()
