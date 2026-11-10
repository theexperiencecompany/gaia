"""The only fixed copy GAIA says to a user: a closed set, keyed by locale.

Everything else a user reads is composed. A kind with no copy in the user's locale
is said in DEFAULT_LOCALE rather than not said.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from app.constants.outbox import DEFAULT_LOCALE


class PrerenderedKind(StrEnum):
    """A message the outbox may say without composing it."""

    COMPOSE_DEGRADED = "compose_degraded"


_COPY: Final[Mapping[PrerenderedKind, Mapping[str, str]]] = {
    PrerenderedKind.COMPOSE_DEGRADED: {
        "en": "I couldn't word this one properly, so here it is plainly:",
    },
}


def prerendered_text(kind: PrerenderedKind, locale: str) -> str:
    """Return the copy for kind in locale, or in DEFAULT_LOCALE when locale has none."""
    by_locale = _COPY[kind]
    return by_locale.get(locale, by_locale[DEFAULT_LOCALE])
