"""Hourly sweep releasing Photon numbers whose iMessage link was never completed."""

from datetime import UTC, datetime
from typing import Any

from app.services.platform_link_service import reap_abandoned_imessage_registrations
from shared.py.wide_events import log


async def sweep_abandoned_imessage_registrations(_ctx: dict[str, Any]) -> str:
    """Release every shared-pool number registered past the TTL and never linked.

    Idempotent: a released number's record is deleted, so the next run does not
    see it; a release that failed keeps its record and is retried next hour.
    """
    reaped = await reap_abandoned_imessage_registrations(datetime.now(UTC))
    log.set(imessage_registrations_reaped=reaped)
    return f"sweep_abandoned_imessage_registrations released {reaped} abandoned registration(s)"
