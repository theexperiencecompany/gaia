"""Unit tests for the abandoned iMessage registration sweep ARQ task."""

from datetime import UTC
from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.platform_link_tasks import sweep_abandoned_imessage_registrations

_MOD = "app.workers.tasks.platform_link_tasks"


@pytest.mark.unit
class TestSweepAbandonedImessageRegistrations:
    async def test_it_reports_how_many_registrations_it_released(self):
        with patch(
            f"{_MOD}.reap_abandoned_imessage_registrations", new_callable=AsyncMock, return_value=3
        ):
            summary = await sweep_abandoned_imessage_registrations({})

        assert "3" in summary

    async def test_the_reaped_count_lands_on_the_wide_event(self):
        from shared.py.wide_events import log

        log.reset()
        with patch(
            f"{_MOD}.reap_abandoned_imessage_registrations", new_callable=AsyncMock, return_value=2
        ):
            await sweep_abandoned_imessage_registrations({})

        assert log.get()["imessage_registrations_reaped"] == 2

    async def test_it_sweeps_against_the_current_utc_time(self):
        """A naive or stale clock would compare against the wrong TTL cutoff."""
        reap = AsyncMock(return_value=0)
        with patch(f"{_MOD}.reap_abandoned_imessage_registrations", reap):
            await sweep_abandoned_imessage_registrations({})

        (now,) = reap.await_args.args
        assert now.tzinfo is UTC
