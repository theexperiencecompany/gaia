"""The credentials a task was given, by name, and the one rule that keeps them out of what people and models read.

The task carries <secret>name</secret> placeholders; only the page ever
receives a value: Jev fills a password field from here, and the Browser-Use
agent through its sensitive_data.
"""

from __future__ import annotations

import re
from urllib.parse import quote, quote_plus, urlsplit

from app.constants.browser import JEV_SECRET_MASK

_PLACEHOLDER = re.compile(r"<secret>([\w.-]+)</secret>")


class RunSecrets:
    """Secret values by placeholder name, as typed and as a URL carries them."""

    def __init__(self, values: dict[str, str], sites: list[str]) -> None:
        self._values = {name: value for name, value in values.items() if value}
        #: The hosts a value may be typed on: the sites the task names. Empty admits none.
        self._sites = [site.lower().removeprefix("www.") for site in sites]
        # A form sent by GET puts a password in the next page's URL, encoded.
        # Longest first, so a longer form is never half-replaced by a shorter one inside it.
        self._forms = sorted(
            (
                (form, name)
                for name, value in self._values.items()
                for form in {value, quote_plus(value), quote(value)}
            ),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    @property
    def names(self) -> list[str]:
        return list(self._values)

    def value_for(self, placeholder: str, url: str) -> str | None:
        """The value a <secret>name</secret> placeholder stands for on url's page; None off the task's sites or when none was given."""
        match = _PLACEHOLDER.fullmatch(placeholder)
        host = (urlsplit(url).hostname or "").lower()
        on_site = any(host == site or host.endswith("." + site) for site in self._sites)
        return self._values.get(match.group(1)) if match and on_site else None

    def mask(self, text: str) -> str:
        """Replace every secret value in text with its placeholder, for text a model reads."""
        for form, name in self._forms:
            text = text.replace(form, f"<secret>{name}</secret>")
        return text

    def redact(self, text: str) -> str:
        """Replace every secret value and placeholder with the mask, for text a person reads."""
        for form, _name in self._forms:
            text = text.replace(form, JEV_SECRET_MASK)
        return _PLACEHOLDER.sub(JEV_SECRET_MASK, text)

    def sensitive_data(self) -> dict[str, str | dict[str, str]]:
        """The map Browser-Use's agent fills <secret>name</secret> from, scoped to the task's sites."""
        scoped: dict[str, str | dict[str, str]] = {}
        for site in self._sites:
            scoped[f"https://{site}"] = dict(self._values)
            scoped[f"https://*.{site}"] = dict(self._values)
        return scoped
