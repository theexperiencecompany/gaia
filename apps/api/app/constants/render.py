"""Server-side headless Chromium renders (app.services.render)."""

from app.constants.search import BROWSER_REAPER_MAX_AGE_SECONDS

# Unhinted glyphs keep fractional advances on Linux, so text spaces as it does on macOS.
CHROMIUM_LAUNCH_ARGS = ("--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none")

#: Chromium renders running at once in one process; the rest wait their turn.
CHROMIUM_MAX_CONCURRENT_RENDERS = 2

# The browser reaper kills any Playwright driver older than BROWSER_REAPER_MAX_AGE_SECONDS, so
# a busy browser is replaced at half that age and an idle one closes well inside it.
CHROMIUM_RECYCLE_AGE_SECONDS = BROWSER_REAPER_MAX_AGE_SECONDS / 2
CHROMIUM_IDLE_CLOSE_SECONDS = 300.0

#: What Playwright raises with once its driver process is gone (playwright/_impl/_transport.py).
CHROMIUM_DEAD_DRIVER_MESSAGE = "Connection closed while reading from the driver"
