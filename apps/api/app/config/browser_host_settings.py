"""Settings the browser host process reads, and nothing else.

The host renders attacker-controlled pages, so it never loads app.config.settings:
that would need the Infisical identity, which unlocks every production secret,
and dozens of fields the host never uses. The API and worker inherit these fields
through their own settings, so both sides read one declaration.
"""

import os
from typing import Annotated, Literal, Self

from dotenv import load_dotenv
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.constants.browser import BrowserEngine
from app.utils.url_safety import http_origin

#: Obscura's own switch that lets it fetch loopback and private addresses.
OBSCURA_PRIVATE_NETWORK_ENV = "OBSCURA_ALLOW_PRIVATE_NETWORK"


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
    # Memory-based admission reading the cgroup's working set and limit: admits while
    # a new session's projected cost stays under HIGH_WATERMARK. LIMIT_MB pins the budget.
    BROWSER_HOST_MEMORY_LIMIT_MB: int | None = None
    BROWSER_HOST_MEMORY_HIGH_WATERMARK: float = 0.85
    # Run Chromium headed (under Xvfb) instead of --headless=new, for anti-bot.
    BROWSER_HOST_HEADED: bool = False
    # Which engine the host at BROWSER_HOST_URL runs: Obscura (a low-RAM Rust CDP
    # server, opt-in per user) or Chromium (headless-shell). Default users run on
    # Chromium, at BROWSER_FALLBACK_HOST_URL when this host runs Obscura.
    BROWSER_ENGINE: BrowserEngine = BrowserEngine.OBSCURA
    # Path to the Obscura binary; required when BROWSER_ENGINE=obscura (the gaia
    # image sets it via ENV). Missing it fails the host launch loud, no fallback.
    OBSCURA_BIN: str | None = None
    # How long Obscura gives a page's script phase before it stops running them.
    OBSCURA_SCRIPT_DEADLINE_SECONDS: int = 60
    # An engine over this many MB is replaced; the fresh one takes new sessions
    # while the old one drains. A safety bound on growth (patch 0033 keeps 60
    # churned sessions at ~170 MB); None disables it.
    BROWSER_ENGINE_RECYCLE_MB: int | None = 1500
    # Path to a Chromium/Chrome binary for BROWSER_ENGINE=chromium. Unset, the
    # host resolves Playwright's headless shell (its download can be
    # unreachable from a dev box); set, that binary is used as is.
    CHROMIUM_BIN: str | None = None
    # Test-only: exact origins (scheme://host:port, comma-separated) a navigation may
    # reach though they resolve private, for the hermetic browser stack's fixture site.
    # Production refuses to boot with any set (see _no_private_reach_in_production).
    BROWSER_HOST_ALLOW_PRIVATE_ORIGINS: Annotated[frozenset[str], NoDecode] = frozenset()

    @field_validator("BROWSER_HOST_KEY", mode="after")
    @classmethod
    def _blank_key_is_unset(cls, v: str | None) -> str | None:
        # Compose spells an unset key ${BROWSER_HOST_KEY:-}, an empty string: that is no key.
        return v or None

    @field_validator("BROWSER_HOST_ALLOW_PRIVATE_ORIGINS", mode="before")
    @classmethod
    def _exact_origins(cls, v: str | frozenset[str]) -> frozenset[str]:
        """Read the list as exact origins: an entry with a path or query, or without its port, is refused."""
        entries = v.split(",") if isinstance(v, str) else v
        origins = {entry.strip() for entry in entries} - {""}
        for origin in origins:
            # Written exactly as http_origin writes it, or a path or a missing port slipped in.
            if http_origin(origin) != origin:
                raise ValueError(
                    f"{origin!r} is not an exact origin; write it as {http_origin(origin)!r}"
                )
        return frozenset(origins)

    @model_validator(mode="after")
    def _no_private_reach_in_production(self) -> Self:
        """Refuse to boot a production process that could browse to private addresses."""
        if self.ENV == "production" and self.BROWSER_HOST_ALLOW_PRIVATE_ORIGINS:
            raise ValueError("BROWSER_HOST_ALLOW_PRIVATE_ORIGINS is set but ENV=production")
        if self.ENV == "production" and os.environ.get(OBSCURA_PRIVATE_NETWORK_ENV):
            raise ValueError(f"{OBSCURA_PRIVATE_NETWORK_ENV} is set but ENV=production")
        return self


load_dotenv()
browser_host_settings = BrowserHostSettings()
