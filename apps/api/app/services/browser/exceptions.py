"""Typed failures for the browser-automation capability."""


class BrowserAutomationError(Exception):
    """Base class for all browser-automation failures."""


class BrowserUnavailableError(BrowserAutomationError):
    """The capability cannot run: disabled, missing config, or the browser host unreachable."""


class BrowserHandoffCancelled(BrowserAutomationError):
    """The user cancelled a sensitive-step handoff; the run must stop cleanly."""


class BrowserConcurrencyLimit(BrowserAutomationError):
    """Too many browser sessions are already running for this deployment."""
