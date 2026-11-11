"""A held drain waits at least the moment it was held until, never less."""

from datetime import UTC, datetime, timedelta

import time_machine

from app.services.triggers.batching import _seconds_until

NOW = datetime(2026, 11, 6, 6, 59, 59, 600000, tzinfo=UTC)


def test_a_sub_second_delay_rounds_up_rather_than_to_zero() -> None:
    """Truncating to 0 would let the drain run early, re-enqueue its own job id, and strand the batch."""
    with time_machine.travel(NOW, tick=False):
        assert _seconds_until(NOW + timedelta(milliseconds=400)) == 1


def test_a_whole_second_delay_is_returned_unchanged() -> None:
    with time_machine.travel(NOW, tick=False):
        assert _seconds_until(NOW + timedelta(seconds=90)) == 90


def test_a_moment_already_passed_never_defers_below_zero() -> None:
    with time_machine.travel(NOW, tick=False):
        assert _seconds_until(NOW - timedelta(seconds=5)) == 0
