"""Drive the simulated clock (this process travels with it, so datetime.now is simulated): jump forward, wait for every process to follow, age server-side time.

The clock file and its pids/ directory are the protocol clockboot/sitecustomize.py speaks.
Redis and Mongo keep real time on their own servers, so each jump ages the sim databases by
the same amount: Redis TTLs shrink and Mongo TTL indexes expire what they would have.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import time
from typing import cast

from pymongo.database import Database
import redis
import time_machine

_ACK_TIMEOUT_S = 30.0
_POLL_S = 0.05
_QUIET_POLL_S = 0.5
_QUIET_TIMEOUT_S = 1800.0
#: A job due this soon is the worker's to pick up now (it polls every 0.5 s), not a future wake-up.
_PICKUP_SLACK = timedelta(seconds=5)
#: Every ARQ queue the worker process serves: the shared one, and the brief and scout queues.
ARQ_QUEUES = ("arq:queue", "arq:queue:brief", "arq:queue:scouts")
ARQ_CRON_PREFIX = b"cron:"


class ClockError(RuntimeError):
    """A process stopped following the clock, or the system never went quiet."""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@dataclass
class SimClock:
    path: Path
    redis_client: redis.Redis
    mongo: Database
    traveller: time_machine.Traveller

    @classmethod
    def create(
        cls, path: Path, start: datetime, redis_client: redis.Redis, mongo: Database
    ) -> "SimClock":
        path.parent.mkdir(parents=True, exist_ok=True)
        (path.parent / "pids").mkdir(exist_ok=True)
        path.write_text(start.astimezone(UTC).isoformat())
        traveller = time_machine.travel(start.astimezone(UTC), tick=True).start()
        return cls(path, redis_client, mongo, traveller)

    def followers(self) -> dict[int, Path]:
        pids = {int(p.name): p for p in (self.path.parent / "pids").iterdir()}
        return {pid: p for pid, p in pids.items() if _alive(pid) and pid != os.getpid()}

    def jump(self, to: datetime) -> None:
        """Age the sim databases to the instant to, then move every process there (forward only).

        Ageing comes first: a key a process writes once it is at the new instant (an ARQ
        in-progress lock taken the moment a due job starts) must keep its whole TTL.
        """
        to = to.astimezone(UTC)
        current = datetime.now(UTC)
        if to <= current:
            return
        self._age_redis(to - current)
        self._age_mongo(to)
        instant = to.isoformat()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(instant)
        tmp.replace(self.path)
        self.traveller.move_to(to)
        deadline = time.monotonic() + _ACK_TIMEOUT_S
        while lagging := [
            pid for pid, ack in self.followers().items() if ack.read_text() != instant
        ]:
            if time.monotonic() > deadline:
                raise ClockError(f"processes {lagging} did not follow the clock to {instant}")
            time.sleep(_POLL_S)

    def _age_redis(self, delta: timedelta) -> None:
        ms = int(delta.total_seconds() * 1000)
        for key in self.redis_client.scan_iter(count=1000):
            ttl = cast(int, self.redis_client.pttl(key))
            if ttl <= 0:
                continue
            if ttl <= ms:
                self.redis_client.delete(key)
            else:
                self.redis_client.pexpire(key, ttl - ms)

    def _age_mongo(self, now: datetime) -> None:
        for name in self.mongo.list_collection_names():
            for index in self.mongo[name].list_indexes():
                seconds = index.get("expireAfterSeconds")
                if seconds is None:
                    continue
                field_name = next(iter(index["key"]))
                cutoff = now - timedelta(seconds=float(seconds))
                self.mongo[name].delete_many({field_name: {"$lt": cutoff}})

    def _queued(self, first: int, last: int) -> list[tuple[bytes, float]]:
        """Return the jobs ranked first..last on every queue, merged by score (ms since the epoch)."""
        rows = [
            row
            for queue in ARQ_QUEUES
            for row in cast(
                list[tuple[bytes, float]],
                self.redis_client.zrange(queue, first, last, withscores=True),
            )
        ]
        return sorted(rows, key=lambda row: row[1])

    def due_job_at(self) -> datetime | None:
        """Return when the next ARQ job on any queue is due."""
        first = self._queued(0, 0)
        if not first:
            return None
        return datetime.fromtimestamp(first[0][1] / 1000, UTC)

    def queue_head(self, size: int = 5) -> list[str]:
        """Return the first queued ARQ jobs as job@instant, for the jump log."""
        head = self._queued(0, size - 1)[:size]
        return [
            f"{job.decode()}@{datetime.fromtimestamp(score / 1000, UTC).isoformat()}"
            for job, score in head
        ]

    def next_event_job_at(self) -> datetime | None:
        """Return when the next non-cron ARQ job is due: a brief, a reminder, a deferred delivery.

        Cron sweeps are not events to jump to: ARQ re-queues each one a moment ahead forever,
        and catches up the runs a jump skipped on its own.
        """
        now_ms = datetime.now(UTC).timestamp() * 1000
        upcoming = sorted(
            (
                row
                for queue in ARQ_QUEUES
                for row in cast(
                    list[tuple[bytes, float]],
                    self.redis_client.zrangebyscore(queue, now_ms, "+inf", withscores=True),
                )
            ),
            key=lambda row: row[1],
        )
        score = next((s for job, s in upcoming if not job.startswith(ARQ_CRON_PREFIX)), None)
        return None if score is None else datetime.fromtimestamp(score / 1000, UTC)

    def wait_quiet(self, alive: Callable[[], None]) -> None:
        """Block until no ARQ job is due within the pickup slack; a running job stays queued until it ends.

        alive raises when a simulated process has died, so a dead worker fails the run at once.
        """
        deadline = time.monotonic() + _QUIET_TIMEOUT_S
        while (busy := self._busy()) is not None:
            alive()
            if time.monotonic() > deadline:
                raise ClockError(f"the system never went quiet: {busy}")
            time.sleep(_QUIET_POLL_S)

    def _busy(self) -> str | None:
        """Say what is still in flight: a due ARQ job, or a workflow run outliving its job.

        A brief's job can leave the queue while its run is still storing and delivering, so
        the workflow's own executing state is part of "quiet".
        """
        due = self.due_job_at()
        if due is not None and due <= datetime.now(UTC) + _PICKUP_SLACK:
            return f"an ARQ job due at {due.isoformat()} is queued"
        if (
            running := self.mongo.workflows.find_one({"status": "executing"}, {"_id": 1})
        ) is not None:
            return f"workflow {running['_id']} is executing"
        return None
