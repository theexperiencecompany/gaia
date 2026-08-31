"""One-second occurrence identity for scheduled fires.

A scheduled ARQ job carries the occurrence it was armed for, and the claim gate
rejects a fire whose occurrence no longer matches the row. ARQ args are
serialized, so that instant travels as a unix int — which floors it to the
second. Encode, decode and compare therefore have to agree on that resolution,
and they live together here so they cannot drift apart.

One second is already the scheduler's unit of occurrence identity:
``_enqueue_task`` derives each job id from ``occurrence_stamp``, so two fires
inside the same second are one job and were never distinguishable.
"""

from datetime import UTC, datetime, timedelta

from shared.py.wide_events import log

OCCURRENCE_RESOLUTION = timedelta(seconds=1)


def occurrence_stamp(moment: datetime) -> int:
    """Encode an armed occurrence for transport through ARQ's serialized args."""
    return int(moment.timestamp())


def parse_occurrence_stamp(raw: object, task_id: str) -> datetime | None:
    """The occurrence a scheduled job was armed for, or None when unstamped.

    Only a real number is scheduler provenance: manual "run now" callers build
    their own job args, so a hand-typed value is discarded (leaving the fire
    ungated) rather than crashing ``fromtimestamp`` mid-run. ``bool`` is excluded
    explicitly — it is an ``int`` subclass.
    """
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        if raw is not None:
            log.warning(
                "Unparseable occurrence stamp on a scheduled fire; treating as unstamped",
                task_id=task_id,
                scheduled_for=str(raw)[:32],
            )
        return None
    try:
        return datetime.fromtimestamp(raw, tz=UTC)
    except (ValueError, OverflowError, OSError):
        log.warning(
            "Unparseable occurrence stamp on a scheduled fire; treating as unstamped",
            task_id=task_id,
            scheduled_for=str(raw)[:32],
        )
        return None


def occurrence_window(moment: datetime) -> dict[str, datetime]:
    """A Mongo filter matching the second ``moment`` falls in.

    The inverse of the floor in ``occurrence_stamp``, and the reason the claim
    gate cannot compare for equality: the stamp round-trips to a whole second
    while Mongo stores the armed instant at BSON's millisecond precision, so a
    reminder armed for ``10:53:56.465`` is pinned by a stamp that reads back as
    ``10:53:56``. Equality there matched nothing — every "remind me in N minutes"
    arms ``now + delta`` and so always carries a sub-second component — and the
    reminder silently never fired.
    """
    start = moment.replace(microsecond=0)
    return {"$gte": start, "$lt": start + OCCURRENCE_RESOLUTION}
