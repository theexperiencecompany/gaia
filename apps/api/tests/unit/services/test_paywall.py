"""Unit tests for app/services/payments/paywall.py."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.config.feature_flags import OnboardingPaywallVariant
from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.payments.paywall import get_paywall

USER_ID = "64abc123def4567890abcdef"
PREFERENCES = OnboardingPreferences(profession="founder", needs=[OnboardingNeed.INBOX])


def _user(preferences: OnboardingPreferences | None) -> MagicMock:
    user = MagicMock()
    user.onboarding = MagicMock(preferences=preferences) if preferences else None
    return user


async def test_value_preview_lists_the_jobs_drafted_from_the_users_answers() -> None:
    seeded = AsyncMock(return_value=["Clear my inbox", "Prep tomorrow"])
    with (
        patch(
            "app.services.payments.paywall.onboarding_paywall_variant",
            AsyncMock(return_value=OnboardingPaywallVariant.VALUE_PREVIEW),
        ),
        patch(
            "app.services.payments.paywall.user_repository.get",
            AsyncMock(return_value=_user(PREFERENCES)),
        ),
        patch("app.services.payments.paywall.seeded_chips", seeded),
    ):
        paywall = await get_paywall(USER_ID)

    assert paywall.variant is OnboardingPaywallVariant.VALUE_PREVIEW
    assert paywall.starting_jobs == ["Clear my inbox", "Prep tomorrow"]
    seeded.assert_awaited_once_with(USER_ID, PREFERENCES)


async def test_value_preview_before_any_answer_lists_nothing() -> None:
    seeded = AsyncMock()
    with (
        patch(
            "app.services.payments.paywall.onboarding_paywall_variant",
            AsyncMock(return_value=OnboardingPaywallVariant.VALUE_PREVIEW),
        ),
        patch(
            "app.services.payments.paywall.user_repository.get",
            AsyncMock(return_value=_user(None)),
        ),
        patch("app.services.payments.paywall.seeded_chips", seeded),
    ):
        paywall = await get_paywall(USER_ID)

    assert paywall.starting_jobs == []
    seeded.assert_not_awaited()


async def test_classic_never_reads_the_drafted_jobs() -> None:
    seeded = AsyncMock(return_value=["Clear my inbox"])
    with (
        patch(
            "app.services.payments.paywall.onboarding_paywall_variant",
            AsyncMock(return_value=OnboardingPaywallVariant.CLASSIC),
        ),
        patch("app.services.payments.paywall.seeded_chips", seeded),
    ):
        paywall = await get_paywall(USER_ID)

    assert paywall.variant is OnboardingPaywallVariant.CLASSIC
    assert paywall.starting_jobs == []
    seeded.assert_not_awaited()
