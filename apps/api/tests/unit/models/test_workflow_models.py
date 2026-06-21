"""Unit tests for TriggerConfig scheduling math — the workflow next-run truth.

This is the model-level computation behind the reported bug ("daily at 9 AM" ran
in UTC). It composes Timezone.parse + cron_utils.get_next_run_time, both covered
in test_timezone.py / test_cron_utils.py; here we assert the composition.
"""

from datetime import UTC, datetime

import pytest

from app.models.workflow_models import TriggerConfig, TriggerType

BASE = datetime(2025, 1, 1, 0, 0, tzinfo=UTC)  # midnight UTC


def _schedule(cron: str = "0 9 * * *", tz: str | None = None) -> TriggerConfig:
    return TriggerConfig(type=TriggerType.SCHEDULE, cron_expression=cron, timezone=tz)


@pytest.mark.unit
class TestTriggerConfigCalculateNextRun:
    def test_daily_9am_in_kolkata_is_0330_utc(self) -> None:
        # The bug: this must NOT be 09:00 UTC.
        result = _schedule(tz="Asia/Kolkata").calculate_next_run(base_time=BASE)
        assert result == datetime(2025, 1, 1, 3, 30, tzinfo=UTC)

    def test_offset_zone_matches_iana(self) -> None:
        by_name = _schedule(tz="Asia/Kolkata").calculate_next_run(base_time=BASE)
        by_offset = _schedule(tz="+05:30").calculate_next_run(base_time=BASE)
        assert by_name == by_offset

    def test_user_timezone_param_overrides_stored(self) -> None:
        # activate/create pass an explicit user_timezone; it wins over stored.
        tc = _schedule(tz="UTC")
        result = tc.calculate_next_run(base_time=BASE, user_timezone="Asia/Kolkata")
        assert result == datetime(2025, 1, 1, 3, 30, tzinfo=UTC)

    def test_stored_timezone_used_when_no_param(self) -> None:
        result = _schedule(tz="Asia/Kolkata").calculate_next_run(base_time=BASE)
        assert (result.hour, result.minute) == (3, 30)

    def test_none_timezone_computes_in_utc(self) -> None:
        result = _schedule(tz=None).calculate_next_run(base_time=BASE)
        assert result == datetime(2025, 1, 1, 9, 0, tzinfo=UTC)

    def test_default_timezone_is_none_sentinel(self) -> None:
        # Default changed from "UTC" to None so create/update can distinguish a
        # user-chosen zone from an unset one. Omit timezone to exercise the model
        # default (not _schedule(), which passes timezone=None explicitly).
        assert TriggerConfig(type=TriggerType.SCHEDULE).timezone is None

    def test_non_schedule_trigger_returns_none(self) -> None:
        assert TriggerConfig(type=TriggerType.MANUAL).calculate_next_run(base_time=BASE) is None

    def test_no_cron_returns_none(self) -> None:
        assert TriggerConfig(type=TriggerType.SCHEDULE).calculate_next_run(base_time=BASE) is None

    def test_result_is_utc(self) -> None:
        result = _schedule(tz="America/New_York").calculate_next_run(base_time=BASE)
        assert result.tzinfo == UTC


@pytest.mark.unit
class TestTriggerConfigUpdateNextRun:
    def test_sets_next_run_and_reports_change(self) -> None:
        tc = _schedule(tz="Asia/Kolkata")
        assert tc.next_run is None
        changed = tc.update_next_run(base_time=BASE)
        assert changed is True
        assert tc.next_run == datetime(2025, 1, 1, 3, 30, tzinfo=UTC)

    def test_no_change_reported_when_value_stable(self) -> None:
        tc = _schedule(tz="Asia/Kolkata")
        tc.update_next_run(base_time=BASE)
        # Same base + zone => same next_run => no change on the second call.
        assert tc.update_next_run(base_time=BASE) is False
