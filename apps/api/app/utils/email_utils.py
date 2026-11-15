"""Email address parsing utilities. Outbound sending lives in app/services/email."""

import re

from app.constants.email import GMAIL_CANONICAL_DOMAIN, GMAIL_DOMAINS, MAILTO_PREFIX

# Separators an email local part uses between name words, plus the trailing
# digits people append to disambiguate ("john.doe83").
_LOCAL_PART_WORD_SPLIT = re.compile(r"[._\-]+")
_TRAILING_DIGITS = re.compile(r"\d+$")


def normalize_email(value: str) -> str | None:
    """Return the bare lowercase email from a mailto: URL or raw address.

    mailto: URLs may carry ?subject=... query parts, which are
    stripped. Returns None when the value is not a plausible address.
    """
    candidate = value.strip()
    if candidate.lower().startswith(MAILTO_PREFIX):
        candidate = candidate[len(MAILTO_PREFIX) :].split("?", 1)[0]
    candidate = candidate.strip().lower()
    if "@" not in candidate or "." not in candidate.split("@")[-1]:
        return None
    return candidate


def derive_name_from_email(email: str) -> str:
    """Best-effort presentable name from an email's local part.

    aryan.randeriya@x.com -> Aryan Randeriya. Plus-tags are dropped,
    . _ - separate words, trailing digits are trimmed off each word. When
    nothing presentable survives (all digits, empty local part) the raw local
    part is returned rather than an empty string.
    """
    local_part = email.partition("@")[0].strip()
    words = [
        stripped.capitalize()
        for word in _LOCAL_PART_WORD_SPLIT.split(local_part.partition("+")[0])
        if (stripped := _TRAILING_DIGITS.sub("", word))
    ]
    return " ".join(words) if words else local_part


def email_identity(email: str) -> str:
    """Return the one address every spelling of a mailbox delivers to, for same-person checks.

    Lowercases, drops a +tag, and for Gmail drops the dots and folds
    googlemail.com into gmail.com: a.ryan+x@googlemail.com -> aryan@gmail.com.
    """
    local, _, domain = email.strip().lower().rpartition("@")
    local = local.partition("+")[0]
    if domain in GMAIL_DOMAINS:
        return f"{local.replace('.', '')}@{GMAIL_CANONICAL_DOMAIN}"
    return f"{local}@{domain}"


def is_email_target(value: str) -> bool:
    """Return True when the string is a bare email address or a mailto: URL."""
    # Exclude web URLs (anything with a scheme) so links never resolve as emails.
    return normalize_email(value) is not None and "://" not in value
