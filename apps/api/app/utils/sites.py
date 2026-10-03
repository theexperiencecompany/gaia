"""What site an address is on, which sites a task named, and the placeholder a task names a credential by.

One reading of each for every caller: the browser's saved logins, a secret's
site, the agent's captions, where a bot check is put to the user, and the two
typists (Jev and Browser-Use) that must agree on which placeholder they fill.
"""

from __future__ import annotations

from collections.abc import Iterable
import re
from urllib.parse import urlsplit

#: <secret>name</secret>, read as Browser-Use reads it (<secret>(.*?)</secret>) but never across
#: two placeholders, so a whole-text match is one placeholder or none.
PLACEHOLDER = re.compile(r"<secret>((?:(?!</secret>).)*)</secret>")

#: A host as a task writes it, with or without a scheme: labels joined by dots, ending in a TLD.
_WRITTEN_HOST = re.compile(
    r"(?<![\w.@-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63})(?![\w-])", re.I
)
_WWW = "www."
#: A URL's scheme (https:, about:, mailto:); what follows a site's colon is its port, digits.
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:(?!\d)", re.I)


def host_of(address: str | None) -> str | None:
    """Return the lowercased host of a URL or a bare site ("github.com/login"), or None when it names none."""
    if not address:
        return None
    try:
        host = urlsplit(address if _SCHEME.match(address) else f"https://{address}").hostname
    except ValueError:
        return None
    return host or None


def site_of(address: str | None) -> str | None:
    """Return the site an address is on: its host, a written "www." naming the whole site."""
    host = host_of(address)
    return host.removeprefix(_WWW) if host is not None else None


def on_site(host: str, site: str) -> bool:
    """Whether host is site itself or one of its subdomains, never a lookalike (notgithub.com)."""
    return host == site or host.endswith(f".{site}")


class UserSites:
    """The sites a task named: written in its text, the page it starts on, or a secret's site."""

    def __init__(self, task: str, start_url: str | None, secret_sites: Iterable[str]) -> None:
        written = [match.group(1) for match in _WRITTEN_HOST.finditer(task)]
        self._sites = frozenset(
            site for site in map(site_of, [*written, start_url, *secret_sites]) if site
        )

    def named(self, url: str | None) -> bool:
        """Whether the page at url is on a site the user named."""
        site = site_of(url)
        return site is not None and any(on_site(site, named) for named in self._sites)
