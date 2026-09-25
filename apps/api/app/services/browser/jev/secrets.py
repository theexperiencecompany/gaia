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


def _forms_of(values: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """Every form a value takes (as typed, and as a URL encodes it) with its name, longest first."""
    return sorted(
        (
            (form, name)
            for name, value in values
            for form in {value, quote_plus(value), quote(value)}
        ),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )


class RunSecrets:
    """Secret values by placeholder name, as typed and as a URL carries them."""

    def __init__(self, values: dict[str, str], sites: list[str]) -> None:
        self._values = {name: value for name, value in values.items() if value}
        #: The hosts a value may be typed on: the sites the task names. Empty admits none.
        self._sites = [site.lower().removeprefix("www.") for site in sites]
        # A form sent by GET puts a password in the next page's URL, encoded.
        # Longest first, so a longer form is never half-replaced by a shorter one inside it.
        self._forms = _forms_of(self._values.items())
        #: Values the run typed into a password field that the task never named a secret.
        self._typed: list[str] = []
        self._redacted = self._forms

    @property
    def names(self) -> list[str]:
        return list(self._values)

    def value_for(self, placeholder: str, url: str) -> str | None:
        """Return the value a <secret>name</secret> placeholder stands for on url's page, or None off the task's sites."""
        match = _PLACEHOLDER.fullmatch(placeholder)
        host = (urlsplit(url).hostname or "").lower()
        on_site = any(host == site or host.endswith("." + site) for site in self._sites)
        return self._values.get(match.group(1)) if match and on_site else None

    def mask(self, text: str) -> str:
        """Replace every secret value in text with its placeholder, for text a model reads."""
        for form, name in self._forms:
            text = text.replace(form, f"<secret>{name}</secret>")
        return text

    def learn(self, typed: str) -> None:
        """Treat a value the run typed into a password field as a secret for everything a person reads.

        A task can spell a password out instead of naming a secret; once it is in
        a password field, it is one, and the page may echo it (a GET form puts it in the URL).
        """
        if (
            not typed
            or _PLACEHOLDER.fullmatch(typed)
            or typed in {*self._values.values(), *self._typed}
        ):
            return
        self._typed.append(typed)
        self._redacted = _forms_of(
            [*self._values.items(), *(("typed", value) for value in self._typed)]
        )

    def redact(self, text: str) -> str:
        """Replace every secret value and placeholder with the mask, for text a person reads."""
        for form, _name in self._redacted:
            text = text.replace(form, JEV_SECRET_MASK)
        return _PLACEHOLDER.sub(JEV_SECRET_MASK, text)

    def sensitive_data(self) -> dict[str, str | dict[str, str]]:
        """Return the map Browser-Use's agent fills <secret>name</secret> from, scoped to the task's sites."""
        scoped: dict[str, str | dict[str, str]] = {}
        if not self._values:
            return scoped
        for site in self._sites:
            scoped[f"https://{site}"] = dict(self._values)
            scoped[f"https://*.{site}"] = dict(self._values)
        return scoped
