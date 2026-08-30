#!/usr/bin/env python3
"""Reconstruct what OpenRouter *actually* charged, per user per UTC day.

GAIA prices every model call from a flat per-model table
(``app/config/model_pricing.py``), but OpenRouter routes the same model to
different providers at rates that differ by up to 10x. Measured over 1,486
calls, logged spend came out 44% below the real invoice — so the durable
history in ``usage_daily`` understates COGS by an amount nobody can see.

This rebuilds the real number from two sources that are already there:

- **Loki** holds one ``llm_call`` wide event per call (30-day retention) with
  the ``generation_id`` OpenRouter issued.
- **OpenRouter** answers ``GET /api/v1/generation?id=<id>`` with the true
  ``total_cost`` and the ``provider_name`` that served it.

A call with no generation id, or one OpenRouter has already dropped (404 —
unverifiable, not an error), keeps its logged cost and counts *against* that
user-day's coverage, so a low coverage number is visible rather than a
silently optimistic total.

Nothing overwrites ``cost``/``aux_cost``: budget enforcement already acted on
those, and rewriting them would retroactively change what a user was charged.
The actuals land beside them in ``cost_actual``/``aux_cost_actual``, with
``cost_actual_coverage``, ``cost_actual_provider_mix`` and ``cost_actual_at``.

Run from the api directory (or /app inside the container)::

    python scripts/backfill_true_cost.py --dry-run
    python scripts/backfill_true_cost.py --days 7 --dry-run
    python scripts/backfill_true_cost.py --apply

Environment: ``LOKI_URL`` (default ``http://loki:3100``) and
``OPENROUTER_API_KEY``. Generation lookups are cached per day under
``--cache-dir``, so a re-run only asks about ids it has not resolved yet — a
long backfill is resumable and an interrupted one costs nothing to restart.
"""

import argparse
import asyncio
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from pydantic import BaseModel, Field

from app.db.mongodb.mongodb import init_mongodb
from app.db.repositories.usage_daily import TrueCostActuals, usage_daily_repository
from shared.py.wide_events import log

_LOKI_SELECTOR = '{service=~"gaia-backend|arq_worker"} |= "\\"llm_event\\": \\"llm_call\\""'
_LOKI_PAGE = 5000
_LOKI_MAX_PAGES = 40
_OPENROUTER_URL = "https://openrouter.ai/api/v1/generation"
_LOOKUP_CONCURRENCY = 5
_LOOKUP_ATTEMPTS = 4
_MAX_DAYS = 30  # Loki's retention — asking for more silently returns less

#: Provider bucket for calls whose real cost could not be confirmed. Keeping
#: them in the mix means it always sums to the reported true total, instead of
#: quietly excluding the part we are least sure about.
UNVERIFIED = "unverified"


class LlmCall(BaseModel):
    """One ``llm_call`` wide event, reduced to what the cost rebuild needs."""

    user_id: str
    day: str
    background: bool
    logged_cost: float
    generation_id: str | None


class GenerationRecord(BaseModel):
    """OpenRouter's own billing record for one generation."""

    total_cost: float = 0.0
    provider_name: str = "unknown"


class UserDayTrueCost(BaseModel):
    """One user-day: what we logged, what was really charged, and by whom."""

    user_id: str
    date: str
    logged_cost: float
    logged_aux_cost: float
    cost_actual: float
    aux_cost_actual: float
    coverage: float
    provider_mix: dict[str, float]

    @property
    def gap(self) -> float:
        """Dollars the flat price table missed (positive = we under-counted)."""
        return (self.cost_actual + self.aux_cost_actual) - (self.logged_cost + self.logged_aux_cost)


class _Lookup(BaseModel):
    """A generation lookup outcome. ``resolved`` False means the answer is
    still unknown (network/5xx exhausted) and must NOT be cached — a 404 is a
    resolved ``None``, because OpenRouter will never know that id again."""

    resolved: bool
    record: GenerationRecord | None = None


class _Accum(BaseModel):
    """Running totals for one (user, day) while folding calls."""

    logged_cost: float = 0.0
    logged_aux_cost: float = 0.0
    cost_actual: float = 0.0
    aux_cost_actual: float = 0.0
    logged_total: float = 0.0
    verified_logged: float = 0.0
    provider_mix: dict[str, float] = Field(default_factory=dict)


def aggregate_true_cost(
    calls: Iterable[LlmCall], generations: Mapping[str, GenerationRecord | None]
) -> list[UserDayTrueCost]:
    """Fold raw calls plus their resolved generations into per-user-day rows.

    Pure — no network, no database. ``generations`` maps a generation id to its
    OpenRouter record, or to ``None`` for an id OpenRouter has dropped; an id
    absent from the mapping is treated the same as ``None``. Coverage is the
    share of that user-day's logged dollars whose real cost we confirmed, so a
    day of cheap unverifiable calls does not drag it down as hard as a day of
    expensive ones. A user-day with no logged spend at all has nothing left to
    verify and reports full coverage.
    """
    accums: dict[tuple[str, str], _Accum] = defaultdict(_Accum)
    for call in calls:
        acc = accums[(call.user_id, call.day)]
        record = generations.get(call.generation_id) if call.generation_id else None
        actual = record.total_cost if record is not None else call.logged_cost
        provider = record.provider_name if record is not None else UNVERIFIED

        acc.logged_total += call.logged_cost
        if record is not None:
            acc.verified_logged += call.logged_cost
        if call.background:
            acc.logged_aux_cost += call.logged_cost
            acc.aux_cost_actual += actual
        else:
            acc.logged_cost += call.logged_cost
            acc.cost_actual += actual
        acc.provider_mix[provider] = acc.provider_mix.get(provider, 0.0) + actual

    return [
        UserDayTrueCost(
            user_id=user_id,
            date=day,
            logged_cost=acc.logged_cost,
            logged_aux_cost=acc.logged_aux_cost,
            cost_actual=acc.cost_actual,
            aux_cost_actual=acc.aux_cost_actual,
            coverage=(acc.verified_logged / acc.logged_total) if acc.logged_total else 1.0,
            provider_mix=acc.provider_mix,
        )
        for (user_id, day), acc in sorted(accums.items())
    ]


def _parse_event(line: str) -> LlmCall | None:
    """Parse one Loki log line into a call, or ``None`` if it isn't one."""
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict) or raw.get("llm_event") != "llm_call":
        return None
    user_id = str(raw.get("user_id") or "")
    timestamp = str(raw.get("time") or "")
    if not user_id or not timestamp:
        return None
    # json.loads accepts NaN/Infinity, and one of those would poison every sum
    # this day feeds — including what --apply writes to cost_actual. A line whose
    # own cost is not a real number is not evidence of anything: drop it.
    logged_cost = _finite_cost(raw.get("cost_usd"))
    if logged_cost is None:
        return None
    generation_id = raw.get("generation_id")
    return LlmCall(
        user_id=user_id,
        day=timestamp[:10],
        background=_is_background(raw),
        logged_cost=logged_cost,
        generation_id=str(generation_id) if generation_id else None,
    )


def _finite_cost(value: object) -> float | None:
    """A cost we are willing to add up: a real, non-negative number. ``None`` for
    anything else — missing, unparseable, negative, NaN or infinite."""
    if value is None:
        return 0.0
    try:
        cost = float(value)  # type: ignore[arg-type]  # guarded by the except below
    except (TypeError, ValueError):
        return None
    return cost if math.isfinite(cost) and cost >= 0.0 else None


def _is_background(raw: Mapping[str, object]) -> bool:
    """Whether this event's spend belongs in the auxiliary bucket, not the
    user's foreground costs.

    A sticky-flip replay counts as background *regardless of the ``background``
    flag*. That is the whole point of this branch: the replay is a cache-warming
    re-send GAIA chose to make and whose answer the user never received, so its
    dollars are COGS, not the user's foreground spend. The events already in
    Loki were emitted before that fix shipped — they carry
    ``sticky_flip_discarded=true`` but no ``background=true``, because the old
    code booked them as foreground. Keying off ``background`` alone would carry
    exactly the mistake this branch removes into ``cost_actual``, so the
    30-day history would be split by the old rule and everything after the
    deploy by the new one.
    """
    return raw.get("background") is True or raw.get("sticky_flip_discarded") is True


def _nanos(moment: datetime) -> int:
    """``moment`` as whole nanoseconds — Loki's own timestamp resolution.

    Integer nanoseconds end to end, deliberately. Rounding the page cursor to
    a whole second (or round-tripping it through a ``datetime``, whose float
    seconds cannot hold a nanosecond) makes the next page restart *inside* a
    second already returned, and every event in that second is folded twice —
    inflating ``cost_actual`` for exactly the busiest user-days.
    """
    return int(moment.timestamp() * 1_000_000_000)


class PageBudgetExhaustedError(RuntimeError):
    """A day needed more than ``_LOKI_MAX_PAGES`` pages, so what was read is a
    prefix, not the day — it must not be written."""

    def __init__(self, day: str) -> None:
        super().__init__(
            f"{day}: more than {_LOKI_MAX_PAGES * _LOKI_PAGE} llm_call lines; "
            "raise _LOKI_MAX_PAGES rather than backfilling a prefix of the day"
        )
        self.day = day


class UndrainableTimestampError(RuntimeError):
    """More log lines share one nanosecond than fit in a Loki page, so the day
    cannot be read completely and must not be written."""

    def __init__(self, day: str, nanos: int) -> None:
        super().__init__(
            f"{day}: more than {_LOKI_PAGE} llm_call lines share timestamp {nanos}ns; "
            "Loki cannot page inside one timestamp, so this day cannot be backfilled completely"
        )
        self.day = day
        self.nanos = nanos


async def _fetch_day(client: httpx.AsyncClient, loki_url: str, day: str) -> list[LlmCall]:
    """Every ``llm_call`` event Loki holds for one UTC day.

    Pages forward — Loki caps a single response at ``limit`` lines and gives
    no cursor of its own, so a busy day needs several passes. ``start`` is
    inclusive, and several lines can share one nanosecond, so the next page
    re-opens AT the last timestamp seen and the lines already taken from that
    timestamp are skipped by identity. Starting one nanosecond later would drop
    the rest of that group; starting any coarser would double-count.
    """
    start = datetime.fromisoformat(f"{day}T00:00:00+00:00")
    end_nanos = _nanos(min(start + timedelta(days=1), datetime.now(UTC)))
    calls: list[LlmCall] = []
    cursor_nanos = _nanos(start)
    # Lines already taken at exactly ``cursor_nanos``, counted — the overlap
    # between pages. Identical lines can repeat within one nanosecond, so the
    # count matters: skipping by identity alone would drop the repeats.
    taken_at_cursor: Counter[str] = Counter()
    scan_complete = False
    for _ in range(_LOKI_MAX_PAGES):
        streams = await _query(client, loki_url, cursor_nanos, end_nanos, _LOKI_PAGE)
        page = _fold_page(streams, cursor_nanos, taken_at_cursor, calls)
        if page.seen < _LOKI_PAGE:
            scan_complete = True
            break
        if page.fresh == 0:
            # The page held nothing but the overlap, so it cannot say whether the
            # group at this nanosecond is finished or runs past a page. Read that
            # one nanosecond on its own to find out.
            if not await _drain_timestamp(client, loki_url, cursor_nanos, taken_at_cursor, calls):
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
    return calls


async def _query(
    client: httpx.AsyncClient, loki_url: str, start: int, end: int, limit: int
) -> list[dict[str, Any]]:
    """One Loki range query, forward, over [start, end) nanoseconds."""
    response = await client.get(
        f"{loki_url.rstrip('/')}/loki/api/v1/query_range",
        params={
            "query": _LOKI_SELECTOR,
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
    nanos: int,
    taken: Counter[str],
    calls: list[LlmCall],
) -> bool:
    """Read everything logged at exactly ``nanos``, keeping whatever was not taken
    on an earlier page. False means the group is larger than one page, so Loki
    cannot serve it whole and the day cannot be read completely.
    """
    streams = await _query(client, loki_url, nanos, nanos + 1, _LOKI_PAGE + 1)
    lines = Counter(line for _, line in _page_values(streams))
    if sum(lines.values()) > _LOKI_PAGE:
        return False
    for line in (lines - taken).elements():
        call = _parse_event(line)
        if call is not None:
            calls.append(call)
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
    calls: list[LlmCall],
) -> _PageScan:
    seen = 0
    fresh = 0
    latest = 0
    at_latest: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    for at, line in _page_values(streams):
        seen += 1
        if at == cursor_nanos and skipped[line] < taken_at_cursor[line]:
            skipped[line] += 1
            continue
        fresh += 1
        if at > latest:
            latest, at_latest = at, Counter()
        if at == latest:
            at_latest[line] += 1
        call = _parse_event(line)
        if call is not None:
            calls.append(call)
    return _PageScan(seen=seen, fresh=fresh, latest=latest, at_latest=at_latest)


def _page_values(streams: list[dict[str, Any]]) -> Iterator[tuple[int, str]]:
    """Every (nanosecond, line) in a Loki page, across its streams."""
    for stream in streams:
        for nanos, line in stream["values"]:
            yield int(nanos), line


async def _lookup_generation(
    client: httpx.AsyncClient, api_key: str, generation_id: str, gate: asyncio.Semaphore
) -> _Lookup:
    """Ask OpenRouter what one generation really cost, with backoff on 429/5xx."""
    async with gate:
        for attempt in range(_LOOKUP_ATTEMPTS):
            try:
                response = await client.get(
                    _OPENROUTER_URL,
                    params={"id": generation_id},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            except httpx.HTTPError:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                await asyncio.sleep(1.2 * (attempt + 1))
                continue
            if response.status_code == 404:
                # OpenRouter drops old generations; unverifiable, not a failure.
                return _Lookup(resolved=True, record=None)
            response.raise_for_status()
            data = response.json().get("data")
            record = GenerationRecord.model_validate(data) if data else None
            return _Lookup(resolved=True, record=record)
    log.warning(
        "[backfill_true_cost] generation lookup exhausted its retries",
        error_type="openrouter_unreachable",
        generation_id=generation_id,
    )
    return _Lookup(resolved=False)


def _read_cache(path: Path) -> dict[str, GenerationRecord | None]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {
        key: GenerationRecord.model_validate(value) if value else None for key, value in raw.items()
    }


def _default_cache_dir() -> Path:
    """Where resolved generations are cached between runs.

    Under the invoking user's cache home, never a shared temp directory: the
    cache is written and read back as the script's own input, so a world-
    writable path lets anyone on the box pre-create it and decide what this
    backfill believes each call cost — and that number is written to
    ``usage_daily``. Ephemeral either way; it only makes a re-run cheaper.
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".cache") / "gaia-true-cost"


def _write_cache(path: Path, known: Mapping[str, GenerationRecord | None]) -> None:
    # 0o700: same reason as _default_cache_dir — nobody else gets to write what
    # this run reads back as the real cost of a call.
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps({k: (v.model_dump() if v else None) for k, v in known.items()}))


async def _resolve_generations(
    client: httpx.AsyncClient, api_key: str, calls: Sequence[LlmCall], cache_path: Path
) -> dict[str, GenerationRecord | None]:
    """Resolve every generation id in ``calls``, reusing the day's cache file."""
    known = _read_cache(cache_path)
    todo = sorted({c.generation_id for c in calls if c.generation_id} - set(known))
    if not todo:
        return known
    gate = asyncio.Semaphore(_LOOKUP_CONCURRENCY)
    lookups = await asyncio.gather(
        *(_lookup_generation(client, api_key, gen_id, gate) for gen_id in todo)
    )
    for gen_id, lookup in zip(todo, lookups, strict=True):
        if lookup.resolved:
            known[gen_id] = lookup.record
    _write_cache(cache_path, known)
    return known


def _render(rows: Sequence[UserDayTrueCost]) -> None:
    by_day: dict[str, list[UserDayTrueCost]] = defaultdict(list)
    for row in rows:
        by_day[row.date].append(row)

    header = (
        f"{'date':<12}{'users':>7}{'logged $':>12}{'true $':>12}"
        f"{'logged bg':>12}{'true bg':>12}{'delta %':>10}{'cover %':>10}"
    )
    print(f"\n{header}")
    print("-" * len(header))
    for day in sorted(by_day):
        day_rows = by_day[day]
        logged = sum(r.logged_cost for r in day_rows)
        actual = sum(r.cost_actual for r in day_rows)
        logged_bg = sum(r.logged_aux_cost for r in day_rows)
        actual_bg = sum(r.aux_cost_actual for r in day_rows)
        logged_all = logged + logged_bg
        delta = ((actual + actual_bg) / logged_all - 1) * 100 if logged_all else 0.0
        # Coverage is dollar-weighted across the day, not a mean of per-user
        # ratios — otherwise a user with one cheap unverifiable call would
        # weigh as much as the user who spent the day's actual money.
        covered = sum(r.coverage * (r.logged_cost + r.logged_aux_cost) for r in day_rows)
        coverage = (covered / logged_all * 100) if logged_all else 100.0
        print(
            f"{day:<12}{len(day_rows):>7}{logged:>12.4f}{actual:>12.4f}"
            f"{logged_bg:>12.4f}{actual_bg:>12.4f}{delta:>9.1f}%{coverage:>9.1f}%"
        )

    gaps: dict[str, float] = defaultdict(float)
    for row in rows:
        gaps[row.user_id] += row.gap
    print(f"\n{'user_id':<28}{'dollar gap':>14}")
    for user_id, gap in sorted(gaps.items(), key=lambda item: -item[1])[:10]:
        print(f"{user_id:<28}{gap:>14.4f}")


async def _apply(rows: Sequence[UserDayTrueCost]) -> tuple[int, int]:
    """Write the actuals onto existing rollup rows. Returns (written, missing)."""
    stamped_at = datetime.now(UTC)
    written = 0
    for row in rows:
        matched = await usage_daily_repository.apply_true_cost(
            row.user_id,
            row.date,
            TrueCostActuals(
                cost_actual=row.cost_actual,
                aux_cost_actual=row.aux_cost_actual,
                coverage=row.coverage,
                provider_mix=row.provider_mix,
                at=stamped_at,
            ),
        )
        written += int(matched)
    return written, len(rows) - written


async def backfill(days: int, cache_dir: Path, apply: bool) -> None:
    loki_url = os.environ.get("LOKI_URL", "http://loki:3100")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is not set — run through `infisical run --`.")

    today = datetime.now(UTC).date()
    wanted = [(today - timedelta(days=offset)).isoformat() for offset in reversed(range(days))]

    calls: list[LlmCall] = []
    generations: dict[str, GenerationRecord | None] = {}
    async with httpx.AsyncClient(timeout=60.0) as client:
        for day in wanted:
            day_calls = await _fetch_day(client, loki_url, day)
            day_generations = await _resolve_generations(
                client, api_key, day_calls, cache_dir / f"{day}.json"
            )
            unresolved = sum(
                1 for c in day_calls if c.generation_id and c.generation_id not in day_generations
            )
            print(
                f"{day}: {len(day_calls)} calls, "
                f"{len(day_generations)} generations on file, {unresolved} unresolved"
            )
            calls.extend(day_calls)
            generations.update(day_generations)

    rows = aggregate_true_cost(calls, generations)
    print(f"\n{len(calls)} calls -> {len(rows)} user-days across {days}d")
    _render(rows)

    if not apply:
        print("\nDRY RUN — nothing was written (pass --apply to write)")
        return
    init_mongodb()
    written, missing = await _apply(rows)
    print(f"\nAPPLIED — {written} rollup rows stamped, {missing} had no usage_daily row")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the actuals to usage_daily")
    mode.add_argument("--dry-run", action="store_true", help="report only (default)")
    parser.add_argument(
        "--days", type=int, default=_MAX_DAYS, help=f"trailing window (max {_MAX_DAYS})"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=_default_cache_dir(),
        help="where per-day generation lookups are cached",
    )
    args = parser.parse_args()
    if args.days < 1:
        raise SystemExit("--days must be at least 1")
    asyncio.run(backfill(min(args.days, _MAX_DAYS), args.cache_dir, args.apply))


if __name__ == "__main__":
    main()
