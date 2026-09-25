"""Which Browser-Use sessions run on the Obscura host.

The engine is chosen per job (Chrome by default, Obscura opt-in), so a patch
that works around an Obscura gap applies to that session only; a Chrome
session keeps Browser-Use's own behaviour.
"""

from urllib.parse import urlsplit

from browser_use.browser.session import BrowserSession

from app.config.settings import settings
from app.constants.browser import BrowserEngine


def on_obscura(session: BrowserSession) -> bool:
    """Whether session is a context on the Obscura host."""
    if settings.BROWSER_ENGINE is not BrowserEngine.OBSCURA or not session.cdp_url:
        return False
    return urlsplit(session.cdp_url).netloc == urlsplit(settings.BROWSER_HOST_URL).netloc
