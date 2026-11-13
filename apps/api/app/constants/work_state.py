"""Bounds on the work-state block comms reads at the start of every interactive turn."""

from typing import Final

from app.constants.cache import ONE_DAY_TTL

#: Most ongoing follow-ups, waiting asks and untold results one block lists.
WORK_STATE_LIST_MAX: Final = 5

#: How far back a message told somewhere else than this chat still counts as recent.
WORK_STATE_TOLD_ELSEWHERE_WINDOW_SECONDS: Final = ONE_DAY_TTL

#: Most messages told elsewhere that one block lists, newest first.
WORK_STATE_TOLD_ELSEWHERE_MAX: Final = 3

#: Longest excerpt of a message told elsewhere.
WORK_STATE_TOLD_EXCERPT_CHARS: Final = 160
