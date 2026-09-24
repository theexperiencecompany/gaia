"""The job's replayable card feed — one Redis stream per background browser job.

The worker publishes every already-normalized card frame here; the API-side
relay replays it into the conversation's live stream. A stream rather than a
pub/sub channel so a relay that starts late, or restarts, still reads from 0-0
and shows the run from step 1.
"""

import json
from typing import TypedDict

from pydantic import TypeAdapter

from app.constants.browser import (
    BROWSER_JOB_EVENTS_MAXLEN,
    BROWSER_JOB_EVENTS_PREFIX,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.browser.job_lifetime import browser_job_ttl_seconds
from shared.py.wide_events import log

#: Closes a job's feed. Not a card: the relay stops on it without having to
#: re-read the job state on every frame, and the worker is the only publisher.
JOB_TERMINAL_FRAME: dict[str, object] = {"browser_job_done": True}


class _StreamFields(TypedDict, total=False):
    """One Redis stream entry's fields, as this module writes them."""

    payload: str


_STREAM_FIELDS: TypeAdapter[_StreamFields] = TypeAdapter(_StreamFields)


def _key(job_id: str) -> str:
    return f"{BROWSER_JOB_EVENTS_PREFIX}{job_id}"


async def publish_job_event(job_id: str, payload: dict[str, object]) -> None:
    """Append one already-normalized stream frame to the job's replayable card feed."""
    key = _key(job_id)
    await redis_cache.client.xadd(
        key,
        {"payload": json.dumps(payload)},
        maxlen=BROWSER_JOB_EVENTS_MAXLEN,
    )
    await redis_cache.client.expire(key, browser_job_ttl_seconds())


async def read_job_events(
    job_id: str, cursor: str, block_ms: int
) -> list[tuple[str, dict[str, object]]]:
    """Read frames after cursor; returns (entry_id, payload) pairs.

    block_ms of 0 reads whatever is already there instead of blocking forever,
    so draining a finished job's whole feed can never hang on an empty stream.
    """
    results = await redis_cache.client.xread(
        {_key(job_id): cursor}, block=block_ms if block_ms > 0 else None
    )
    events: list[tuple[str, dict[str, object]]] = []
    for _stream, entries in results:
        for entry_id, fields in entries:
            typed_fields: _StreamFields = _STREAM_FIELDS.validate_python(fields)
            payload = _decode(entry_id, typed_fields.get("payload"))
            if payload is not None:
                events.append((entry_id, payload))
    return events


def _decode(entry_id: str, raw: str | None) -> dict[str, object] | None:
    # A frame nobody can read is dropped, never raised: one poisoned entry must
    # not end the relay and cost the user every remaining card. An entry with
    # no payload field at all (raw is None) fails json.loads with TypeError.
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        log.error(f"{LogTag.BROWSER} Dropping malformed browser job frame", entry_id=entry_id)
        return None
    if not isinstance(payload, dict):
        log.error(f"{LogTag.BROWSER} Dropping non-object browser job frame", entry_id=entry_id)
        return None
    return payload
