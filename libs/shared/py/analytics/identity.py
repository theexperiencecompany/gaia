"""The only identities an analytics event may be attributed to.

A distinct_id that is an email, "system" or empty splits one person into
several PostHog profiles, so capture accepts nothing but these two types.
"""

from dataclasses import dataclass
import re

_OBJECT_ID = re.compile(r"^[0-9a-f]{24}$")
_PLATFORM = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class UserId:
    """GAIA's stable user id, the Mongo ObjectId of the users document."""

    value: str

    def __post_init__(self) -> None:
        """Refuse anything that is not a 24-hex ObjectId string."""
        if not _OBJECT_ID.fullmatch(self.value):
            raise ValueError(f"UserId must be a Mongo ObjectId, got {self.value!r}")

    @property
    def distinct_id(self) -> str:
        """Return the PostHog distinct_id."""
        return self.value


@dataclass(frozen=True, slots=True)
class PlatformIdentity:
    """A bot user who has not linked a GAIA account yet; linking aliases it into the UserId."""

    platform: str
    platform_user_id: str

    def __post_init__(self) -> None:
        """Refuse an unnamed platform or an empty platform user id."""
        if not _PLATFORM.fullmatch(self.platform):
            raise ValueError(f"PlatformIdentity needs a platform slug, got {self.platform!r}")
        if not self.platform_user_id.strip():
            raise ValueError("PlatformIdentity needs a platform user id")

    @property
    def distinct_id(self) -> str:
        """Return the PostHog distinct_id, "<platform>:<platform user id>"."""
        return f"{self.platform}:{self.platform_user_id}"


AnalyticsId = UserId | PlatformIdentity

__all__ = ["AnalyticsId", "PlatformIdentity", "UserId"]
