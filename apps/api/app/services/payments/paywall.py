"""The onboarding paywall: which variant a user sees, and what it shows them."""

from app.config.feature_flags import OnboardingPaywallVariant
from app.db.repositories.users import user_repository
from app.models.payment_models import PaywallResponse
from app.services.feature_flags import onboarding_paywall_variant
from app.services.onboarding.first_question import seeded_chips


async def get_paywall(user_id: str) -> PaywallResponse:
    """Resolve the user's paywall variant and, for the value preview, the jobs drafted from their answers.

    The jobs come from the background draft the Q2 save starts, so they are
    empty until it lands; the client polls briefly rather than waiting on it.
    """
    variant = await onboarding_paywall_variant(user_id)
    if variant is OnboardingPaywallVariant.CLASSIC:
        return PaywallResponse(variant=variant, starting_jobs=[])
    user = await user_repository.get(user_id)
    preferences = user.onboarding.preferences if user and user.onboarding else None
    jobs = await seeded_chips(user_id, preferences) if preferences else []
    return PaywallResponse(variant=variant, starting_jobs=jobs)
