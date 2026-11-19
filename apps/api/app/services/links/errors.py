"""The errors a link route answers with; each denial is one ErrorEnvelope code."""

from dataclasses import dataclass
from typing import Self

from app.models.short_link_models import LinkDenial
from app.utils.errors import AppError

_DENIALS: dict[LinkDenial, tuple[int, str]] = {
    LinkDenial.NOT_FOUND: (404, "This link doesn't exist."),
    LinkDenial.REVOKED: (410, "This link was turned off by the person who shared it."),
    LinkDenial.EXPIRED: (410, "This link has expired."),
    LinkDenial.REMOVED: (410, "This link was removed for breaking GAIA's terms."),
    LinkDenial.TARGET_DELETED: (410, "What this link pointed to was deleted."),
    LinkDenial.SIGN_IN_REQUIRED: (401, "Sign in to open this."),
    LinkDenial.FORBIDDEN: (403, "You don't have access to this."),
}


@dataclass
class LinkTargetNotFoundError(AppError):
    """The owner has no such artifact, or no such live link."""

    message: str = "Target not found"
    status_code: int = 404
    code: str = "link_target_not_found"


@dataclass
class LinkDeniedError(AppError):
    """A viewer may not open a link; code is the LinkDenial the page shows."""

    @classmethod
    def for_denial(cls, denial: LinkDenial, *, signed_in_as: str | None = None) -> Self:
        status, message = _DENIALS[denial]
        public: dict[str, object] = {"signed_in_as": signed_in_as} if signed_in_as else {}
        return cls(message=message, status_code=status, code=denial.value, public=public)
