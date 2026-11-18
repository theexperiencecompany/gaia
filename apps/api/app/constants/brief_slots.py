"""How brief runs are spread across their hour (app/workers/brief_slots.py), and the queues they run on."""

from typing import Final

#: Minutes past the hour a user's brief may land on; each user keeps one of them for good.
BRIEF_SLOT_SPREAD_MINUTES: Final[int] = 30

#: The queue brief runs take, so an hour's briefs never wait behind (or hold up) the shared queue.
BRIEF_QUEUE: Final[str] = "arq:queue:brief"
#: Briefs one worker process runs at once; the rest wait on the brief queue, not the shared one.
BRIEF_QUEUE_MAX_JOBS: Final[int] = 6
#: The queue each brief's scouts are refreshed on, ahead of the brief's slot.
SCOUT_QUEUE: Final[str] = "arq:queue:scouts"
#: Scout refreshes one worker process runs at once; each runs up to SCOUT_CONCURRENCY scouts.
SCOUT_QUEUE_MAX_JOBS: Final[int] = 4
