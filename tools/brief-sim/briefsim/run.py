"""The discrete-event loop: jump to the next thing that happens, let GAIA's worker catch up, repeat.

The next thing is the earliest persona action or queued ARQ job (briefs, reminders, deferred
deliveries), so each fires at its own instant. ARQ queues every cron run a jump skipped, one
per poll, so the worker does the same sweeps production would over that span; the sim polls
fast (ARQ_POLL_DELAY_SECONDS) so that takes seconds. When the run ends, everything GAIA stored
and sent is exported next to the world's own call log for the oracle and the report.
"""

from datetime import UTC, datetime
import json
from pathlib import Path
import signal
import time
from types import FrameType
from zoneinfo import ZoneInfo

from pymongo import MongoClient
import redis

from briefsim import oracle
from briefsim.clock import SimClock
from briefsim.personas.scripted import TIMEZONE, Founder
from briefsim.stack import MONGO_DB, MONGO_URI, REDIS_URL, running_stack
from briefsim.world.scenario import Clockwork

JsonObject = dict[str, object]
#: Exported per user after the run: what GAIA stored and what reached the user in-app.
EXPORTED = [
    "briefings",
    "notifications",
    "scouts",
    "signal_memory",
    "pending_brief_items",
    "llm_calls",
]


def _log_jump(out: Path, start: datetime, to: datetime, reason: str, queue: list[str]) -> None:
    row = {"from": start.isoformat(), "to": to.isoformat(), "reason": reason, "queue": queue}
    with (out / "clock.jsonl").open("a") as sink:
        sink.write(json.dumps(row) + "\n")


def _export(out: Path, mongo: MongoClient[JsonObject], user_id: str) -> None:
    db = mongo[MONGO_DB]
    for name in EXPORTED:
        # llm_calls is the run's whole LLM ledger; scout and helper calls do not all carry a user.
        rows = list(db[name].find({} if name == "llm_calls" else {"user_id": user_id}))
        with (out / f"{name}.jsonl").open("w") as sink:
            for row in rows:
                row["_id"] = str(row["_id"])
                sink.write(json.dumps(row, default=str) + "\n")


def _stop_on_sigterm() -> None:
    """Turn SIGTERM into SystemExit so the stack's teardown runs."""

    def stop(signum: int, _frame: FrameType | None) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)


def run(out: Path, origin: datetime, days: int) -> None:
    """Simulate the founder for days from origin and write the run's artifacts under out."""
    _stop_on_sigterm()
    out.mkdir(parents=True, exist_ok=True)
    for stale in ("world_calls.jsonl", "persona.jsonl", "clock.jsonl"):
        (out / stale).unlink(missing_ok=True)
    mongo: MongoClient[JsonObject] = MongoClient(MONGO_URI)
    redis_client = redis.Redis.from_url(REDIS_URL)
    clock = SimClock.create(out / "clock" / "now", origin, redis_client, mongo[MONGO_DB])
    tz = ZoneInfo(TIMEZONE)
    clockwork = Clockwork(tz, origin.astimezone(tz).date())
    end = clockwork.at(days)
    started = time.monotonic()
    with running_stack(out, clock.path, origin.isoformat(), days) as stack:
        founder = Founder(
            stack.api,
            stack.world,
            mongo[MONGO_DB],
            redis_client,
            stack.env,
            clockwork,
            out / "persona.jsonl",
        )
        pending = founder.schedule(days)
        while datetime.now(UTC) < end:
            stack.check_alive()
            clock.wait_quiet()
            while pending and pending[0].at <= datetime.now(UTC):
                founder.act(pending.pop(0))
                clock.wait_quiet()
            wake = {"end": end}
            if pending:
                wake[pending[0].name] = pending[0].at
            if (due := clock.next_event_job_at()) is not None:
                wake["arq job"] = due
            reason, to = min(wake.items(), key=lambda item: item[1])
            _log_jump(out, datetime.now(UTC), to, reason, clock.queue_head())
            clock.jump(to)
        clock.wait_quiet()
        _export(out, mongo, founder.user_id)
    (out / "run.json").write_text(
        json.dumps(
            {
                "origin": origin.isoformat(),
                "days": days,
                "timezone": TIMEZONE,
                "user_id": founder.user_id,
                "wall_clock_s": round(time.monotonic() - started),
            }
        )
    )
    oracle.write_findings(out)
