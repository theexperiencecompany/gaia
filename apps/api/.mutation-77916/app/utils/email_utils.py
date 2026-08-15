"""Email address parsing utilities. Outbound sending lives in app/services/email."""

from app.constants.email import MAILTO_PREFIX


def normalize_email(value: str) -> str | None:
    """Return the bare lowercase email from a ``mailto:`` URL or raw address.

    ``mailto:`` URLs may carry ``?subject=...`` query parts, which are
    stripped. Returns None when the value is not a plausible address.
    """
    candidate = value.strip()
    if candidate.lower().startswith(MAILTO_PREFIX):
        candidate = candidate[len(MAILTO_PREFIX) :].split("?", 1)[0]
    candidate = candidate.strip().lower()
    if "@" not in candidate or "." not in candidate.split("@")[-1]:
        return None
    return candidate


def is_email_target(value: str) -> bool:
    """True when the string is a bare email address or a ``mailto:`` URL."""
    # Exclude web URLs (anything with a scheme) so links never resolve as emails.
    return normalize_email(value) is not None and "://" not in value
