"""gaia-browser-host: one low-RAM Chromium, one isolated context per session.

Replaces self-hosted Steel. A single long-lived Chromium is multiplexed into one
``Target.createBrowserContext`` per active session; a per-session CDP-filtering
proxy makes browser-use believe it owns the browser, an authenticated screencast
serves the live view, and idle contexts are reaped. Runs as its own container off
the same API image: ``python -m app.browser_host``.
"""
