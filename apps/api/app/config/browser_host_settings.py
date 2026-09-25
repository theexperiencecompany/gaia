"""Settings the browser host process reads, and nothing else.

The host renders attacker-controlled pages, so it never loads app.config.settings:
that would need the Infisical identity, which unlocks every production secret,
and dozens of fields the host never uses. The API and worker inherit these fields
through their own settings, so both sides read one declaration.
"""

from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.constants.browser import BrowserEngine


class BrowserHostSettings(BaseSettings):
    """The browser host's configuration, read from its own environment only."""

    model_config = SettingsConfigDict(extra="ignore")

    ENV: Literal["production", "development"] = "production"

    # Interface the host binds. Loopback for a native run; the api image sets
    # 0.0.0.0, where the container sits on the internal network, port unpublished.
    BROWSER_HOST_BIND_ADDRESS: str = "127.0.0.1"
    # Port this process serves on when it runs as a browser host.
    BROWSER_HOST_PORT: int = 8930
    # Concurrent sessions one browser host accepts before it answers 429.
    BROWSER_HOST_MAX_SESSIONS: int = 200
    BROWSER_HOST_URL: str = "http://browser-host:8930"  # NOSONAR python:S5332 — internal docker service, plain HTTP on the private network by design (TLS terminates at the edge)
    # Shared secret the API/worker must present to every host endpoint. Required
    # in production: the host renders attacker-controlled pages in the SAME
    # container, so a page could otherwise reach the control plane on localhost.
    BROWSER_HOST_KEY: str | None = None
    # Memory-based admission reading the cgroup's used/limit: admits while a new
    # session's projected cost stays under HIGH_WATERMARK, sheds idle sessions
    # between SOFT and HIGH. LIMIT_MB pins the budget when the cgroup is unreadable.
    BROWSER_HOST_MEMORY_LIMIT_MB: int | None = None
    BROWSER_HOST_MEMORY_HIGH_WATERMARK: float = 0.85
    BROWSER_HOST_MEMORY_SOFT_WATERMARK: float = 0.75
    # Dispose a context after this many seconds with no activity and no live viewer.
    BROWSER_HOST_IDLE_TTL_SECONDS: int = 300
    # Run Chromium headed (under Xvfb) instead of --headless=new, for anti-bot.
    BROWSER_HOST_HEADED: bool = False
    # Which engine the host launches. Obscura (a low-RAM Rust CDP server) is the
    # default; Chromium (headless-shell) is the flag-selectable break-glass engine
    # over the same CDP plane. Set BROWSER_ENGINE=chromium to fall back.
    BROWSER_ENGINE: BrowserEngine = BrowserEngine.OBSCURA
    # Path to the Obscura binary; required when BROWSER_ENGINE=obscura (the gaia
    # image sets it via ENV). Missing it fails the host launch loud, no fallback.
    OBSCURA_BIN: str | None = None
    # Page.navigate blocks until load or this deadline; past it the page's
    # remaining scripts never run. On a 70 KB/s link one 353 KB stylesheet took
    # 25 s, so a 30 s deadline left jQuery pages inert (measured 2026-09-22).
    OBSCURA_NAV_TIMEOUT_SECONDS: int = 90
    # How long Obscura gives a page's script phase before it stops running them.
    OBSCURA_SCRIPT_DEADLINE_SECONDS: int = 60
    # An idle engine tree over this many MB is relaunched; None disables it.
    # Obscura keeps ~50 MB per disposed context, and an 11-hour process took 57 s
    # for a document read a fresh one did in 0.8 s (measured 2026-09-22).
    BROWSER_ENGINE_RECYCLE_MB: int | None = 1500
    # Path to a Chromium/Chrome binary for BROWSER_ENGINE=chromium. Unset, the
    # host resolves Playwright's headless shell (its download can be
    # unreachable from a dev box); set, that binary is used as is.
    CHROMIUM_BIN: str | None = None
    # Port Obscura's CDP server binds. Fixed (not ephemeral) because Obscura only
    # publishes its /json/version — and thus its ws endpoint — at a port we name.
    OBSCURA_PORT: int = 9222


load_dotenv()
browser_host_settings = BrowserHostSettings()
