"""Reading a whole day of ``llm_call`` events out of Loki, exactly once.

Shared by the backfill scripts. Loki caps a response at ``limit`` lines and
offers no cursor, so reading a busy day whole is the fiddly part: the page must
re-open AT the last nanosecond seen and skip precisely the lines already taken
from it. Starting one nanosecond later silently drops the rest of that group;
starting any coarser double-counts the busiest days — which are exactly the ones
whose numbers matter.

That logic lives here rather than in either script because there is only one
correct version of it, and a copy would drift. Callers supply the parser for
their own row shape; the stream selector is shared because both scripts read the
same ``llm_call`` events.

Loki keeps 30 days, so nothing older can be read at all.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import httpx

# The stream selector both backfills use: the JSON line filter is a literal
# fragment of the emitted event, so Loki narrows before we parse anything.
LOKI_SELECTOR = '{service=~"gaia-backend|arq_worker"} |= "\\"llm_event\\": \\"llm_call\\""'
LOKI_PAGE = 5000
LOKI_MAX_PAGES = 40
#: Loki's retention — asking for more silently returns less.
MAX_DAYS = 30

_T = TypeVar("_T")


def nanos(moment: datetime) -> int:
    """``moment`` as whole nanoseconds — Loki's own timestamp resolution.

    Integer nanoseconds end to end, deliberately. Rounding the page cursor to
    a whole second (or round-tripping it through a ``datetime``, whose float
    seconds cannot hold a nanosecond) makes the next page restart *inside* a
    second already returned, and every event in that second is folded twice —
    inflating the totals for exactly the busiest days.
    """
    return int(moment.timestamp() * 1_000_000_000)


class PageBudgetExhaustedError(RuntimeError):
    """A day needed more than ``LOKI_MAX_PAGES`` pages, so what was read is a
    prefix, not the day — it must not be written."""

    def __init__(self, day: str) -> None:
        super().__init__(
            f"{day}: more than {LOKI_MAX_PAGES * LOKI_PAGE} llm_call lines; "
            "raise LOKI_MAX_PAGES rather than backfilling a prefix of the day"
        )
        self.day = day


class UndrainableTimestampError(RuntimeError):
    """More log lines share one nanosecond than fit in a Loki page, so the day
    cannot be read completely and must not be written."""

    def __init__(self, day: str, at_nanos: int) -> None:
        super().__init__(
            f"{day}: more than {LOKI_PAGE} llm_call lines share timestamp {at_nanos}ns; "
            "Loki cannot page inside one timestamp, so this day cannot be backfilled completely"
        )
        self.day = day
        self.nanos = at_nanos


async def fetch_day(
    client: httpx.AsyncClient,
    loki_url: str,
    day: str,
    parse: Callable[[str], _T | None],
) -> list[_T]:
    """Every ``llm_call`` event Loki holds for one UTC day, parsed by ``parse``.

    Pages forward — Loki caps a single response at ``limit`` lines and gives
    no cursor of its own, so a busy day needs several passes. ``start`` is
    inclusive, and several lines can share one nanosecond, so the next page
    re-opens AT the last timestamp seen and the lines already taken from that
    timestamp are skipped by identity. Starting one nanosecond later would drop
    the rest of that group; starting any coarser would double-count.

    ``parse`` returns ``None`` for a line the caller wants dropped.
    """
    start = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    end_nanos = nanos(min(start + timedelta(days=1), datetime.now(UTC)))
    rows: list[_T] = []
    cursor_nanos = nanos(start)
    # Lines already taken at exactly ``cursor_nanos``, counted — the overlap
    # between pages. Identical lines can repeat within one nanosecond, so the
    # count matters: skipping by identity alone would drop the repeats.
    taken_at_cursor: Counter[str] = Counter()
    scan_complete = False
    for _ in range(LOKI_MAX_PAGES):
        streams = await query(client, loki_url, cursor_nanos, end_nanos, LOKI_PAGE)
        page = _fold_page(streams, cursor_nanos, taken_at_cursor, rows, parse)
        if page.seen < LOKI_PAGE:
            scan_complete = True
            break
        if page.fresh == 0:
            # The page held nothing but the overlap, so it cannot say whether the
            # group at this nanosecond is finished or runs past a page. Read that
            # one nanosecond on its own to find out.
            if not await _drain_timestamp(
                client, loki_url, cursor_nanos, taken_at_cursor, rows, parse
            ):
                raise UndrainableTimestampError(day, cursor_nanos)
            cursor_nanos, taken_at_cursor = cursor_nanos + 1, Counter()
        elif page.latest == cursor_nanos:
            taken_at_cursor += page.at_latest
        else:
            cursor_nanos, taken_at_cursor = page.latest, Counter(page.at_latest)
        if cursor_nanos >= end_nanos:
            scan_complete = True
            break
    if not scan_complete:
        raise PageBudgetExhaustedError(day)
    return rows


async def query(
    client: httpx.AsyncClient, loki_url: str, start: int, end: int, limit: int
) -> list[dict[str, Any]]:
    """One Loki range query, forward, over [start, end) nanoseconds."""
    response = await client.get(
        f"{loki_url.rstrip('/')}/loki/api/v1/query_range",
        params={
            "query": LOKI_SELECTOR,
            "start": start,
            "end": end,
            "limit": limit,
            "direction": "forward",
        },
        headers={"accept": "application/json"},
    )
    response.raise_for_status()
    streams: list[dict[str, Any]] = response.json()["data"]["result"]
    return streams


async def _drain_timestamp(
    client: httpx.AsyncClient,
    loki_url: str,
    at_nanos: int,
    taken: Counter[str],
    rows: list[_T],
    parse: Callable[[str], _T | None],
) -> bool:
    """Read everything logged at exactly ``at_nanos``, keeping whatever was not
    taken on an earlier page. False means the group is larger than one page, so
    Loki cannot serve it whole and the day cannot be read completely.
    """
    streams = await query(client, loki_url, at_nanos, at_nanos + 1, LOKI_PAGE + 1)
    lines = Counter(line for _, line in page_values(streams))
    if sum(lines.values()) > LOKI_PAGE:
        return False
    for line in (lines - taken).elements():
        row = parse(line)
        if row is not None:
            rows.append(row)
    return True


@dataclass(frozen=True)
class _PageScan:
    """What one Loki page contributed: how many lines it held, how many were new,
    and the lines at its last nanosecond WITH their multiplicity — two identical
    lines can share a timestamp, and the next page must skip exactly the ones
    already taken, not every line that looks like them."""

    seen: int
    fresh: int
    latest: int
    at_latest: Counter[str]


def _fold_page(
    streams: list[dict[str, Any]],
    cursor_nanos: int,
    taken_at_cursor: Counter[str],
    rows: list[_T],
    parse: Callable[[str], _T | None],
) -> _PageScan:
    seen = 0
    fresh = 0
    latest = 0
    at_latest: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    for at, line in page_values(streams):
        seen += 1
        if at == cursor_nanos and skipped[line] < taken_at_cursor[line]:
            skipped[line] += 1
            continue
        fresh += 1
        if at > latest:
            latest, at_latest = at, Counter()
        if at == latest:
            at_latest[line] += 1
        row = parse(line)
        if row is not None:
            rows.append(row)
    return _PageScan(seen=seen, fresh=fresh, latest=latest, at_latest=at_latest)


def page_values(streams: list[dict[str, Any]]) -> Iterator[tuple[int, str]]:
    """Every (nanosecond, line) in a Loki page, across its streams."""
    for stream in streams:
        for at_nanos, line in stream["values"]:
            yield int(at_nanos), line
