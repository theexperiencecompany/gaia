"""Briefing system workflow constants.

The daily briefing and the weekly digest are ordinary system workflows on the
workflow engine (``app/services/system_workflows/definitions/briefing.py``),
provisioned for every onboarded user rather than per integration. Their keys
and crons live here so the definitions, the provisioner and the tests read
one value.
"""

from typing import Final

BRIEFING_DAILY_KEY: Final[str] = "briefing:daily"
BRIEFING_WEEKLY_KEY: Final[str] = "briefing:weekly"

#: 08:00 in the user's timezone (the provisioner stamps the timezone).
BRIEFING_DAILY_CRON: Final[str] = "0 8 * * *"
#: Sunday 18:00 in the user's timezone: the week is over, the next has not begun.
BRIEFING_WEEKLY_CRON: Final[str] = "0 18 * * 0"
