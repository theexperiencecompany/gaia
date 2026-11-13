import os

from app.constants.browser import BROWSER_USE_EVENT_TIMEOUTS, BROWSER_USE_PHONE_HOME_OFF

# Set here, not in an entrypoint: every GAIA process imports this package before
# anything can import browser_use, and the API imports it before app.patches.
os.environ.update(BROWSER_USE_PHONE_HOME_OFF)
for _event_timeout, _seconds in BROWSER_USE_EVENT_TIMEOUTS.items():
    os.environ.setdefault(_event_timeout, _seconds)

# Nothing else is imported here on purpose. The stackprinter excepthook moved to the
# entrypoints (app/main.py, app/worker.py): importing it here pulled numpy
# (86 modules, ~0.5 s) into every importer of every app module.
