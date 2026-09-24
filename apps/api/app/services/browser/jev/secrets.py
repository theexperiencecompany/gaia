"""Values the run typed into password fields, and the one rule that keeps them out of what people read."""

from __future__ import annotations

from urllib.parse import quote, quote_plus

from app.constants.browser import JEV_SECRET_MASK


class TypedSecrets:
    """Every value typed into a password field this run, as typed and as a URL carries it."""

    def __init__(self) -> None:
        self._forms: set[str] = set()

    def add(self, value: str) -> None:
        # A form sent by GET puts the password in the next page's URL, encoded.
        self._forms |= {form for form in (value, quote_plus(value), quote(value)) if form}

    def redact(self, text: str) -> str:
        """Return text with every typed secret replaced by the mask."""
        # Longest first, so a longer form is never half-replaced by a shorter one inside it.
        for form in sorted(self._forms, key=len, reverse=True):
            text = text.replace(form, JEV_SECRET_MASK)
        return text


__all__ = ["TypedSecrets"]
