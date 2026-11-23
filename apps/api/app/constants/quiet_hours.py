"""The user's quiet hours: local hours in which GAIA holds what can wait for the morning."""

from typing import Final

# Hours on the user's own clock; the span crosses midnight.
QUIET_HOURS_START: Final[int] = 22
QUIET_HOURS_END: Final[int] = 8
