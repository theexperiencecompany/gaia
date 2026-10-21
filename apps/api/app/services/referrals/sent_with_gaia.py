"""The opt-in "Sent with GAIA" line: mail GAIA writes for a user carries their invite link."""

from app.db.repositories.subscriptions import subscription_repository
from app.services.referrals.codes import ensure_code, load_user, share_link


async def sent_with_gaia_link(user_id: str) -> str | None:
    """Return the invite link to sign GAIA-written mail with; None unless the user turned it on and has a link."""
    user = await load_user(user_id)
    preferences = user.onboarding.preferences if user.onboarding else None
    if preferences is None or not preferences.sent_with_gaia:
        return None
    if await subscription_repository.get_active_for_user(user.id) is None:
        return None
    return share_link(await ensure_code(user))
