"""What site an address is on, and the placeholder a task names a credential by.

One reading of both for every caller: the browser's saved logins, a secret's
site, the agent's captions, and the two typists (Jev and Browser-Use) that
must agree on which placeholder they fill.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

#: <secret>name</secret>, read as Browser-Use reads it (<secret>(.*?)</secret>) but never across
#: two placeholders, so a whole-text match is one placeholder or none.
PLACEHOLDER = re.compile(r"<secret>((?:(?!</secret>).)*)</secret>")


def host_of(address: str | None) -> str | None:
    """Return the lowercased host of a URL or a bare site ("github.com/login"), or None when it names none."""
    if not address:
        return None
    try:
        host = urlsplit(address if "://" in address else f"https://{address}").hostname
    except ValueError:
        return None
    return host or None


def on_site(host: str, site: str) -> bool:
    """Whether host is site itself or one of its subdomains, never a lookalike (notgithub.com)."""
    return host == site or host.endswith(f".{site}")
