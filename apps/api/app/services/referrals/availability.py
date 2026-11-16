"""The referral program's on/off switch: the REFERRALS flag, on deployments that sell plans at all.

Every entry point that starts something new (a code, a landing, an invite, a
gift, a nudge) asks here once. Rewards for friends already attributed never
do, so a referrer keeps every month they earned while the program is off.
"""

from app.config.feature_flags import FeatureFlag
from app.config.settings import settings
from app.constants.error_codes import REFERRALS_DISABLED
from app.constants.referrals import (
    REFERRALS_DISABLED_FIX,
    REFERRALS_DISABLED_MESSAGE,
    REFERRALS_DISABLED_WHY,
)
from app.services.feature_flags import is_enabled
from app.utils.errors import AppError
from shared.py.wide_events import log


async def referrals_enabled(user_id: str) -> bool:
    """Whether this user may refer or be gifted now; never on a self-host, which has no plans to gift."""
    enabled = settings.deployment.enforces_plans and await is_enabled(
        FeatureFlag.REFERRALS, user_id
    )
    if not enabled:
        log.set_ns("referral", disabled=True)
    return enabled


async def require_referrals(user_id: str) -> None:
    """Raise 403 REFERRALS_DISABLED while the program is off for this user."""
    if not await referrals_enabled(user_id):
        raise AppError(
            message=REFERRALS_DISABLED_MESSAGE,
            why=REFERRALS_DISABLED_WHY,
            fix=REFERRALS_DISABLED_FIX,
            status_code=403,
            code=REFERRALS_DISABLED,
        )
