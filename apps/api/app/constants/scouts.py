"""Brief scouts: one per connected integration, watching what needs the user now or soon."""

from datetime import timedelta
from typing import Final

#: Integrations another part of the brief already covers: mail through the inbox desk,
#: the day's events through the calendar section. A scout there would count them twice.
SCOUTED_ELSEWHERE: Final[frozenset[str]] = frozenset({"gmail", "googlecalendar"})

#: Graph steps a learn run may take; each tool call costs two (the model turn and the call).
SCOUT_LEARN_RECURSION_LIMIT: Final[int] = 24
#: Wall clock a learn run gets before it is abandoned as a skipped scout.
SCOUT_LEARN_TIMEOUT: Final = timedelta(seconds=120)
#: Most read-only tools bound onto one learn run; provider caps on bound tools sit near 128.
SCOUT_MAX_BOUND_TOOLS: Final[int] = 100

#: Safety ceiling on signals one scout may hand the brief: a runaway list, not a quota.
SCOUT_SIGNAL_CEILING: Final[int] = 50

#: What one user's scouts may spend on learn runs in a UTC day before the rest are skipped.
SCOUT_DAILY_COST_CEILING_USD: Final[float] = 0.05
#: Redis tally of that spend, per user per UTC day.
SCOUT_SPEND_KEY: Final[str] = "scouts:spend:{user_id}:{day}"
SCOUT_SPEND_TTL_SECONDS: Final[int] = 2 * 24 * 60 * 60

#: The ARQ task a newly connected integration enqueues so the next brief already scouts it.
LEARN_SCOUT_TASK: Final[str] = "learn_scout"

#: A replayed signal due within this window (or overdue) reads as important.
SIGNAL_URGENT_WINDOW: Final = timedelta(hours=24)

#: Stored as a scout playbook's result brief: a scout is never narrated.
SCOUT_RESULT_BRIEF: Final[str] = "Replayed without narration; its items become brief signals."

#: What a learn run's graph is metered and logged as.
SCOUT_AGENT_NAME: Final[str] = "brief_scout"
