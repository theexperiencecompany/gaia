"""The one scale of how recently a human used GAIA, read by every consumer of user activity."""

from datetime import timedelta
from enum import StrEnum
from typing import Final


class ActivityStatus(StrEnum):
    """How recently a human last used GAIA, from any surface."""

    ACTIVE = "active"
    IDLE = "idle"
    DORMANT = "dormant"


#: Unseen this long, a user is idle: nudged to come back, still fully served.
IDLE_AFTER: Final = timedelta(days=7)
#: Unseen this long, a user is dormant: nudges stop and GAIA stops spending on them.
DORMANT_AFTER: Final = timedelta(days=30)

#: The ARQ task that resumes everything paused while a returning user was dormant.
REACTIVATE_USER_TASK: Final[str] = "reactivate_user"
#: First retry delay of a reactivation that did not finish; grows per try.
REACTIVATE_USER_RETRY_DELAY: Final = timedelta(seconds=30)
