"""Per-session browser metrics: resource samples, navigation timing, counts.

Every session on the host gets one :class:SessionMetrics. It is pure
bookkeeping — the host feeds it samples at the three moments that already
happen (session create, navigation complete, session dispose) and the CDP proxy
feeds it navigation/page events, so nothing here polls or busy-loops.

The resource numbers come from the whole engine process tree (browser,
renderers, GPU), shared by every session on that engine, so they cost the
browser while this session was open, not this session alone. Attributing them
per session is only meaningful when comparing runs that each own the host.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import TypedDict


class AggregateSnapshot(TypedDict):
    """Readable form of an :class:Aggregate — omitted entirely when empty."""

    count: int
    min: float
    max: float
    avg: float


class MetricsSnapshot(TypedDict):
    """The metrics block a caller reads off GET /sessions/{id}."""

    session_lifetime_seconds: float
    navigation_count: int
    page_count: int
    rss_mb: AggregateSnapshot | None
    cpu_percent: AggregateSnapshot | None
    navigation_ms: AggregateSnapshot | None


@dataclass(slots=True)
class Aggregate:
    """Running min/max/avg over a stream of samples."""

    count: int = 0
    total: float = 0.0
    minimum: float = 0.0
    maximum: float = 0.0

    def add(self, value: float) -> None:
        if self.count == 0:
            self.minimum = value
            self.maximum = value
        else:
            self.minimum = min(self.minimum, value)
            self.maximum = max(self.maximum, value)
        self.count += 1
        self.total += value

    @property
    def average(self) -> float:
        return self.total / self.count if self.count else 0.0

    def snapshot(self) -> AggregateSnapshot | None:
        """None while nothing has been sampled — an absent number, not a zero."""
        if self.count == 0:
            return None
        return {
            "count": self.count,
            "min": round(self.minimum, 3),
            "max": round(self.maximum, 3),
            "avg": round(self.average, 3),
        }


@dataclass(slots=True)
class SessionMetrics:
    """Resource, timing and count metrics for one browser session."""

    created_at: float = field(default_factory=time.monotonic)
    rss_mb: Aggregate = field(default_factory=Aggregate)
    cpu_percent: Aggregate = field(default_factory=Aggregate)
    navigation_ms: Aggregate = field(default_factory=Aggregate)
    navigation_count: int = 0
    page_count: int = 0
    navigation_started_at: float | None = None

    def add_resource_sample(self, rss_mb: float, cpu_percent: float) -> None:
        self.rss_mb.add(rss_mb)
        self.cpu_percent.add(cpu_percent)

    def start_navigation(self) -> None:
        """Record that a Page.navigate left the client.

        A second one supersedes the first: the earlier load event is never observed, so keeping the old start would
        bill the abandoned navigation's wait to the new one."""
        self.navigation_started_at = time.monotonic()

    def finish_navigation(self) -> float | None:
        """Record a load event; return the elapsed ms, or None if unsolicited.

        Load events also fire for navigations the client never asked for (a
        redirect chain's final document, a page's own location assignment),
        so an unmatched one is normal and is not counted.
        """
        if self.navigation_started_at is None:
            return None
        elapsed_ms = (time.monotonic() - self.navigation_started_at) * 1000
        self.navigation_started_at = None
        self.navigation_count += 1
        self.navigation_ms.add(elapsed_ms)
        return elapsed_ms

    def snapshot(self) -> MetricsSnapshot:
        return {
            "session_lifetime_seconds": round(time.monotonic() - self.created_at, 3),
            "navigation_count": self.navigation_count,
            "page_count": self.page_count,
            "rss_mb": self.rss_mb.snapshot(),
            "cpu_percent": self.cpu_percent.snapshot(),
            "navigation_ms": self.navigation_ms.snapshot(),
        }
