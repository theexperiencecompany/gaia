"""The only fixed copy GAIA says to a user: a closed set, keyed by locale.

Everything else a user reads is composed. A kind with no copy in the user's locale
is said in DEFAULT_LOCALE rather than not said.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.constants.outbox import DEFAULT_LOCALE


class PrerenderedKind(StrEnum):
    """A message the outbox may say without composing it."""

    COMPOSE_DEGRADED = "compose_degraded"
    ACCOUNT_LINKED = "account_linked"
    FIRST_CONTACT = "first_contact"
    GENERIC_PREVIEW = "generic_preview"


#: Kinds that say hello: worth nothing late, so the bot's queue drops one that waited too long.
GREETING_KINDS: Final = frozenset({PrerenderedKind.ACCOUNT_LINKED, PrerenderedKind.FIRST_CONTACT})


class PrerenderedMessage(BaseModel):
    """A producer's request to say a prerendered kind: the value its copy names, or the bubbles its code built."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: PrerenderedKind
    #: The platform's display name, for the kind whose copy names it.
    platform: str | None = Field(default=None, min_length=1)
    #: The per-user bubbles of a first contact, built in code from the user's picks.
    bubbles: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _carries_what_its_kind_needs(self) -> Self:
        if (self.platform is not None) != (self.kind is PrerenderedKind.ACCOUNT_LINKED):
            raise ValueError(f"{self.kind.value} does not take this platform setting")
        if bool(self.bubbles) != (self.kind is PrerenderedKind.FIRST_CONTACT):
            raise ValueError(f"{self.kind.value} does not take these bubbles")
        return self


_COPY: Final[Mapping[PrerenderedKind, Mapping[str, str]]] = {
    PrerenderedKind.COMPOSE_DEGRADED: {
        "en": "I couldn't word this one properly, so here it is plainly:",
    },
    PrerenderedKind.GENERIC_PREVIEW: {
        "en": "Something needs your attention.",
    },
    PrerenderedKind.ACCOUNT_LINKED: {
        "en": (
            "✅ **You're connected**\n\n"
            "Your {platform} account is linked. "
            "Message me anytime, or send `/help` to see what I can do."
        ),
    },
}


def prerendered_text(kind: PrerenderedKind, locale: str, **values: str) -> str:
    """Return the copy for kind in locale, or in DEFAULT_LOCALE when locale has none, with values filled in."""
    by_locale = _COPY[kind]
    return by_locale.get(locale, by_locale[DEFAULT_LOCALE]).format(**values)


def prerendered_parts(message: PrerenderedMessage, locale: str) -> list[str]:
    """Return the bubbles a prerendered message says to a user in locale."""
    if message.kind is PrerenderedKind.FIRST_CONTACT:
        return list(message.bubbles)
    values = {"platform": message.platform} if message.platform else {}
    return [prerendered_text(message.kind, locale, **values)]
