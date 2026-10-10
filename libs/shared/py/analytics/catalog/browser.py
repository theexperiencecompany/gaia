"""Browser automation events."""

from typing import ClassVar

from shared.py.analytics.catalog.base import ServerEvent
from shared.py.analytics.catalog.properties import Hostname, Identifier

__all__ = [
    "BrowserEngineSwitched",
    "BrowserHandoffResolved",
    "BrowserImportTokenMinted",
    "BrowserLoginsImported",
    "BrowserTaskFinished",
]


class BrowserTaskFinished(ServerEvent):
    """A browser run finished; captured at the end, never on start, so attempts never count as successes."""

    event: ClassVar[str] = "browser:task_finished"
    budget_per_user_day: ClassVar[int] = 50

    status: Identifier
    success: bool
    steps: int
    actions: int
    duration_ms: int
    source: Identifier
    # With success, whether the fallback engine recovered a run the primary could not finish.
    engine_fallback: bool


class BrowserEngineSwitched(ServerEvent):
    """The agent moved an Obscura run to Chrome: the sites where the fast engine falls short."""

    event: ClassVar[str] = "browser:engine_switched"
    budget_per_user_day: ClassVar[int] = 50

    reason: Identifier
    engine: Identifier
    # The host alone, never what the user opened.
    host: Hostname | None = None


class BrowserHandoffResolved(ServerEvent):
    """A human resolved a browser handoff: continued it or cancelled the run."""

    event: ClassVar[str] = "browser:handoff_resolved"
    budget_per_user_day: ClassVar[int] = 50

    decision: Identifier
    with_note: bool


class BrowserImportTokenMinted(ServerEvent):
    """The web session minted a gaia connect import code; first half of the login import funnel."""

    event: ClassVar[str] = "browser:import_token_minted"
    budget_per_user_day: ClassVar[int] = 50


class BrowserLoginsImported(ServerEvent):
    """The gaia connect CLI redeemed its code and uploaded browser logins; second half of the funnel."""

    event: ClassVar[str] = "browser:logins_imported"
    budget_per_user_day: ClassVar[int] = 50

    host_count: int
    cookie_count: int
    source_browser: Identifier | None = None
