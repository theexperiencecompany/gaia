"""Per-session browser metrics: resource samples, navigation timing, counts.

Every session on the host gets one :class:`SessionMetrics`. It is pure
bookkeeping — the host feeds it samples at the three moments that already
happen (session create, navigation complete, session dispose) and the CDP proxy
feeds it navigation/page events, so nothing here polls or busy-loops.

The resource numbers come from the Chromium *process tree* (browser + renderers
+ GPU), which is shared by every session on this host: they answer "what did the
browser cost while this session was open", not "what did this session alone
cost". Attributing them per session is only meaningful when comparing runs that
each own the host — which is exactly the engine/profile A-B comparison this
exists for.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import time
from typing import TypedDict

import psutil

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

_BYTES_PER_MB = 1024 * 1024


class AggregateSnapshot(TypedDict):
    """Readable form of an :class:`Aggregate` — omitted entirely when empty."""

    count: int
    min: float
    max: float
    avg: float


class MetricsSnapshot(TypedDict):
    """The ``metrics`` block a caller reads off ``GET /sessions/{id}``."""

    session_lifetime_seconds: float
    navigation_count: int
    context_count: int
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
        """``None`` while nothing has been sampled — an absent number, not a zero."""
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
    context_count: int = 0
    page_count: int = 0
    navigation_started_at: float | None = None

    def add_resource_sample(self, rss_mb: float, cpu_percent: float) -> None:
        self.rss_mb.add(rss_mb)
        self.cpu_percent.add(cpu_percent)

    def start_navigation(self) -> None:
        """A ``Page.navigate`` left the client. A second one supersedes the first:
        the earlier load event is never observed, so keeping the old start would
        bill the abandoned navigation's wait to the new one."""
        self.navigation_started_at = time.monotonic()

    def finish_navigation(self) -> float | None:
        """A load event arrived; returns the elapsed ms, or ``None`` if unsolicited.

        Load events also fire for navigations the client never asked for (a
        redirect chain's final document, a page's own ``location`` assignment),
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
            "context_count": self.context_count,
            "page_count": self.page_count,
            "rss_mb": self.rss_mb.snapshot(),
            "cpu_percent": self.cpu_percent.snapshot(),
            "navigation_ms": self.navigation_ms.snapshot(),
        }


class ProcessSampler:
    """Samples the Chromium process tree's RSS and CPU%.

    ``cpu_percent()`` is used in its non-blocking form: the first call on a
    process seeds the counter and reports 0.0, every later call reports the
    average since the previous one. That makes a sample a couple of syscalls
    with no sleep, which is what lets the host sample on events.
    """

    def __init__(self, pid: int) -> None:
        self._pid = pid
        self._root = psutil.Process(pid)
        self._root.cpu_percent()

    @classmethod
    def for_pid(cls, pid: int) -> ProcessSampler | None:
        """A sampler for ``pid``, or ``None`` — losing metrics must not fail a launch."""
        try:
            return cls(pid)
        # TypeError covers a pid that is not a usable process id at all; psutil
        # rejects it before it ever raises one of its own errors.
        except (psutil.Error, OSError, TypeError) as exc:
            log.warning(
                f"{LogTag.BROWSER} browser host resource sampler unavailable",
                error_type=type(exc).__name__,
                browser={"pid": pid},
            )
            return None

    def sample(self) -> tuple[float, float] | None:
        """``(rss_mb, cpu_percent)`` for the tree, or ``None`` if it cannot be read.

        A process that died (or a permission the host does not have) must not
        take a session down with it — the metric is missing, the session is not.
        """
        try:
            procs = [self._root, *self._root.children(recursive=True)]
            rss = 0
            cpu = 0.0
            for proc in procs:
                # Children come and go constantly (a renderer per page); one that
                # exited mid-walk is expected, not a sampling failure.
                with contextlib.suppress(psutil.NoSuchProcess):
                    rss += proc.memory_info().rss
                    cpu += proc.cpu_percent()
            return rss / _BYTES_PER_MB, cpu
        except (psutil.Error, OSError) as exc:
            log.warning(
                f"{LogTag.BROWSER} browser host resource sample failed",
                error_type=type(exc).__name__,
                browser={"pid": self._pid},
            )
            return None
