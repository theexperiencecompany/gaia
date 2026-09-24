"""Values the run typed into password fields, and the one rule that keeps them out of what people read."""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import quote, quote_plus

from app.constants.browser import JEV_SECRET_MASK
from app.services.browser.jev.observation import JevObservation


class TypedSecrets:
    """Every value typed into a password field this run, as typed and as a URL carries it."""

    def __init__(self) -> None:
        self._forms: set[str] = set()

    def add(self, value: str) -> None:
        # A form sent by GET puts the password in the next page's URL, encoded.
        self._forms |= {form for form in (value, quote_plus(value), quote(value)) if form}

    def mask_fields(self, observation: JevObservation) -> JevObservation:
        """Show a filled password field as filled, never its value; an empty one stays empty.

        The engine's live value decides (both engines report a password field's
        value), so a field the page cleared reads empty and is filled again.
        """
        elements = tuple(
            replace(element, value=JEV_SECRET_MASK) if element.secret and element.value else element
            for element in observation.elements
        )
        return replace(observation, elements=elements)

    def redact(self, text: str) -> str:
        """Return text with every typed secret replaced by the mask."""
        # Longest first, so a longer form is never half-replaced by a shorter one inside it.
        for form in sorted(self._forms, key=len, reverse=True):
            text = text.replace(form, JEV_SECRET_MASK)
        return text


__all__ = ["TypedSecrets"]
