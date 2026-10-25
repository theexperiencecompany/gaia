"""Redis state for delivery-failure incidents.

An incident groups failures sharing a fingerprint until DELIVERY_INCIDENT_QUIET_SECONDS
pass with none. Every write happens under the incident's lock (incident_lock_key), so
read-modify-write on the hash needs no transaction.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.constants.delivery_alerts import (
    DELIVERY_INCIDENT_KEY_PREFIX,
    DELIVERY_INCIDENT_QUIET_SECONDS,
    DeliveryFailureKind,
)
from app.db.redis import AsyncRedisCommands
from app.schemas.delivery_failures import DeliveryFailure


class Incident(BaseModel):
    """One open incident as stored, enough to render its Slack message."""

    model_config = ConfigDict(frozen=True)

    fingerprint: str
    platform: str
    kind: DeliveryFailureKind
    reason: str
    error_code: str | None
    error_message: str | None
    count: int
    users: int
    countries: tuple[str, ...]
    first_at: datetime
    last_at: datetime
    slack_ts: str | None = None

    @field_validator("error_code", "error_message", mode="before")
    @classmethod
    def _blank_is_absent(cls, value: object) -> object:
        """Read a blank as absent: a Redis hash cannot hold None."""
        return None if value == "" else value


def incident_fingerprint(failure: DeliveryFailure) -> str:
    """Failures alert together when platform, kind and cause match."""
    return f"{failure.platform.value}:{failure.kind.value}:{failure.error_code or failure.reason}"


def _hash_key(fingerprint: str) -> str:
    return f"{DELIVERY_INCIDENT_KEY_PREFIX}{fingerprint}"


def _users_key(fingerprint: str) -> str:
    return f"{_hash_key(fingerprint)}:users"


def _countries_key(fingerprint: str) -> str:
    return f"{_hash_key(fingerprint)}:countries"


def incident_lock_key(fingerprint: str) -> str:
    """Return the key of the lock every read-modify-write of one incident runs under."""
    return f"{_hash_key(fingerprint)}:lock"


def _recipient_key(failure: DeliveryFailure) -> str | None:
    if failure.user_id:
        return f"user:{failure.user_id}"
    if failure.destination_id:
        return f"destination:{failure.destination_id}"
    return None


async def record_occurrence(redis: AsyncRedisCommands, failure: DeliveryFailure) -> Incident:
    """Add one failure to its incident, opening it if none is open, and slide its expiry."""
    fingerprint = incident_fingerprint(failure)
    key = _hash_key(fingerprint)
    stored = await read_incident(redis, fingerprint)

    users = stored.users if stored else 0
    recipient = _recipient_key(failure)
    if recipient is not None and await redis.sadd(_users_key(fingerprint), recipient):
        users += 1
    if failure.country:
        await redis.sadd(_countries_key(fingerprint), failure.country)

    occurred_at = failure.occurred_at.isoformat()
    fields = {
        "count": str((stored.count if stored else 0) + 1),
        "users": str(users),
        "last_at": occurred_at,
    }
    if stored is None:
        fields |= {
            "platform": failure.platform.value,
            "kind": failure.kind.value,
            "reason": failure.reason,
            "error_code": failure.error_code or "",
            "error_message": failure.error_message or "",
            "first_at": occurred_at,
        }
    await redis.hset(key, mapping=fields)
    for member_key in (key, _users_key(fingerprint), _countries_key(fingerprint)):
        await redis.expire(member_key, DELIVERY_INCIDENT_QUIET_SECONDS)

    incident = await read_incident(redis, fingerprint)
    if incident is None:
        raise RuntimeError(f"delivery incident {fingerprint} vanished right after it was written")
    return incident


async def read_incident(redis: AsyncRedisCommands, fingerprint: str) -> Incident | None:
    """Return the open incident for fingerprint, or None once it has gone quiet."""
    stored = await redis.hgetall(_hash_key(fingerprint))
    if not stored:
        return None
    countries = await redis.smembers(_countries_key(fingerprint))
    return Incident.model_validate(
        stored | {"fingerprint": fingerprint, "countries": tuple(sorted(countries))}
    )


async def attach_slack_message(redis: AsyncRedisCommands, fingerprint: str, ts: str) -> None:
    """Remember the incident's parent Slack message so later failures thread under it."""
    await redis.hset(_hash_key(fingerprint), mapping={"slack_ts": ts})


async def discard_incident(redis: AsyncRedisCommands, fingerprint: str) -> None:
    """Forget an incident whose Slack message could not be posted, so the next failure retries."""
    await redis.delete(_hash_key(fingerprint), _users_key(fingerprint), _countries_key(fingerprint))
