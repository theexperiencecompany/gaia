"""The sites the user named for a task: the only ones a bot check there is put to them for.

A site is named when the task text writes its host, the run starts on it, or a
secret was given for it. A host written with "www." names the whole site.
"""

from __future__ import annotations

from collections.abc import Iterable
import re
from urllib.parse import urlsplit

#: A host as a task writes it, with or without a scheme: labels joined by dots, ending in a TLD.
_HOST = re.compile(
    r"(?<![\w.@-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63})(?![\w-])", re.I
)
_WWW = "www."


def _site(host: str) -> str:
    return host.lower().removeprefix(_WWW)


class UserSites:
    """The hosts a task names; a page is on one when its host is that host or under it."""

    def __init__(self, task: str, start_url: str | None, secret_sites: Iterable[str]) -> None:
        named = [match.group(1) for match in _HOST.finditer(task)]
        start = urlsplit(start_url).hostname if start_url else None
        self._sites = frozenset(
            _site(host) for host in [*named, *([start] if start else []), *secret_sites]
        )

    def named(self, url: str | None) -> bool:
        """Whether the page at url is on a site the user named."""
        host = urlsplit(url).hostname if url else None
        if host is None:
            return False
        site = _site(host)
        return any(site == named or site.endswith(f".{named}") for named in self._sites)
