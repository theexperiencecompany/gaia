"""The session fence's environment must actually hold inside unit tests, not just sit in os.environ."""

from datetime import UTC, datetime
import time


def test_the_fence_puts_the_local_clock_on_utc() -> None:
    """Regression: glibc ignores a runtime TZ change until tzset, so the box's IST clock leaked into naive-time tests."""
    assert time.localtime().tm_gmtoff == 0
    assert abs((datetime.now() - datetime.now(UTC).replace(tzinfo=None)).total_seconds()) < 60
