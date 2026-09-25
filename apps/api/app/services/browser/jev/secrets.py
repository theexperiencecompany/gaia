"""The credentials a task was given, by name, and the one rule that keeps them out of what people and models read.

The task carries <secret>name</secret> placeholders; only the page ever
receives a value: Jev fills a password field from here, and the Browser-Use
agent through its sensitive_data.
"""

from __future__ import annotations

from collections.abc import Iterable
import re
from urllib.parse import quote, quote_plus, urlsplit

from app.constants.browser import JEV_SECRET_MASK

_PLACEHOLDER = re.compile(r"<secret>([\w.-]+)</secret>")


def _encodings(value: str) -> set[str]:
    """Return every form a value takes: as typed, and as a URL encodes it."""
    return {value, quote_plus(value), quote(value)}


class _Replacer:
    """Replace each form with its stand-in in one pass, so no stand-in is rewritten again."""

    def __init__(self, stand_ins: dict[str, str]) -> None:
        self._stand_ins = stand_ins
        # Alternatives compete only where one starts another; reverse order puts the longer first.
        forms = sorted(stand_ins, reverse=True)
        self._pattern = re.compile("|".join(map(re.escape, forms))) if forms else None

    def __call__(self, text: str) -> str:
        if self._pattern is None:
            return text
        return self._pattern.sub(lambda match: self._stand_ins[match.group(0)], text)


def _masked_by_name(values: dict[str, str]) -> _Replacer:
    return _Replacer(
        {
            form: f"<secret>{name}</secret>"
            for name, value in values.items()
            for form in _encodings(value)
        }
    )


def _masked(values: Iterable[str]) -> _Replacer:
    return _Replacer({form: JEV_SECRET_MASK for value in values for form in _encodings(value)})


class RunSecrets:
    """Secret values by placeholder name, as typed and as a URL carries them."""

    def __init__(self, values: dict[str, str], sites: list[str]) -> None:
        self._values = {name: value for name, value in values.items() if value}
        #: The hosts a value may be typed on: the sites the task names. Empty admits none.
        self._sites = [site.lower().removeprefix("www.") for site in sites]
        # A form sent by GET puts a password in the next page's URL, encoded.
        self._mask = _masked_by_name(self._values)
        #: Values the run typed into a password field that the task never named a secret.
        self._typed: set[str] = set()
        self._redact = _masked(self._values.values())

    @property
    def names(self) -> list[str]:
        return list(self._values)

    def value_for(self, placeholder: str, url: str) -> str | None:
        """Return the value a <secret>name</secret> placeholder stands for on url's page, or None off the task's sites."""
        match = _PLACEHOLDER.fullmatch(placeholder)
        # hostname is lowercased by urlsplit; a page with no host is on no site.
        host = urlsplit(url).hostname
        on_site = host is not None and any(
            host == site or host.endswith("." + site) for site in self._sites
        )
        return self._values.get(match.group(1)) if match and on_site else None

    def mask(self, text: str) -> str:
        """Replace every secret value in text with its placeholder, for text a model reads."""
        return self._mask(text)

    def learn(self, typed: str) -> None:
        """Treat a value the run typed into a password field as a secret for everything a person reads.

        A task can spell a password out instead of naming a secret; once it is in
        a password field, it is one, and the page may echo it (a GET form puts it in the URL).
        """
        if not typed or _PLACEHOLDER.fullmatch(typed):
            return
        self._typed.add(typed)
        self._redact = _masked([*self._values.values(), *self._typed])

    def redact(self, text: str) -> str:
        """Replace every secret value and placeholder with the mask, for text a person reads."""
        return _PLACEHOLDER.sub(JEV_SECRET_MASK, self._redact(text))

    def sensitive_data(self) -> dict[str, str | dict[str, str]]:
        """Return the map Browser-Use's agent fills <secret>name</secret> from, scoped to the task's sites."""
        scoped: dict[str, str | dict[str, str]] = {}
        if not self._values:
            return scoped
        for site in self._sites:
            scoped[f"https://{site}"] = dict(self._values)
            scoped[f"https://*.{site}"] = dict(self._values)
        return scoped
