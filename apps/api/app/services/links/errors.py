"""The errors a link route answers with, and the copy the link page shows for each.

Each denial is one ErrorEnvelope code. mise links:constants generates LINK_PAGE_COPY
into the web app, which renders it for the codes the API answers and for a 404 page.
"""

from dataclasses import dataclass
from typing import Self

from app.constants.http import RATE_LIMIT_EXCEEDED_CODE
from app.models.short_link_models import LinkDenial
from app.utils.errors import AppError

LINK_LOOKUP_LOCKED_CODE = "link_lookup_locked"

_DENIALS: dict[LinkDenial, tuple[int, str]] = {
    LinkDenial.NOT_FOUND: (404, "This link doesn't exist."),
    LinkDenial.REVOKED: (
        410,
        "This link was turned off by the person who shared it. Ask them for a new one.",
    ),
    LinkDenial.EXPIRED: (
        410,
        "This link has expired. Ask the person who shared it for a new one.",
    ),
    LinkDenial.REMOVED: (410, "This link was removed for breaking GAIA's terms."),
    LinkDenial.TARGET_DELETED: (410, "What this link pointed to was deleted."),
    LinkDenial.SIGN_IN_REQUIRED: (401, "Sign in to open this."),
    LinkDenial.FORBIDDEN: (403, "You don't have access to this."),
}

#: The heading the link page shows, by the ErrorEnvelope code that refused the open.
LINK_PAGE_COPY: dict[str, str] = {
    **{denial.value: message for denial, (_status, message) in _DENIALS.items()},
    LINK_LOOKUP_LOCKED_CODE: (
        "Too many links that don't exist were opened from here. Try again in an hour."
    ),
    # The limiter's own message names no link, so the page says it in link terms.
    RATE_LIMIT_EXCEEDED_CODE: "Too many links were opened from here. Try again in a minute.",
}


@dataclass
class LinkTargetNotFoundError(AppError):
    """The owner has no such artifact, or no such live link."""

    message: str = "Target not found"
    status_code: int = 404
    code: str = "link_target_not_found"


@dataclass
class LinkLookupLockedError(AppError):
    """A viewer opened too many unknown slugs and is locked out of every resolve for a while."""

    message: str = LINK_PAGE_COPY[LINK_LOOKUP_LOCKED_CODE]
    status_code: int = 429
    code: str = LINK_LOOKUP_LOCKED_CODE


@dataclass
class LinkDeniedError(AppError):
    """A viewer may not open a link; code is the LinkDenial the page shows."""

    @classmethod
    def for_denial(cls, denial: LinkDenial, *, signed_in_as: str | None = None) -> Self:
        status, message = _DENIALS[denial]
        public: dict[str, object] = {"signed_in_as": signed_in_as} if signed_in_as else {}
        return cls(message=message, status_code=status, code=denial.value, public=public)
