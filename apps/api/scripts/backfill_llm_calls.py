#!/usr/bin/env python3
"""Rebuild the ``llm_calls`` ledger from the log history that predates it.

The ledger starts empty on the day it ships, so every cost question about the
past still has to be answered by scraping logs — which is the problem it exists
to end. Loki holds one ``llm_call`` wide event per model call for 30 days, and
those events carry almost everything a ledger row needs, so the recent past can
be reconstructed instead of lost.

Sources, in the order a row's cost is trusted:

- **OpenRouter** ``GET /api/v1/generation?id=<id>`` — what was actually charged.
  The same lookup ``backfill_true_cost.py`` uses, cached per day so a re-run
  only asks about ids it has not resolved.
- **The event itself**, when it recorded ``cost_source="provider"`` — the
  provider's own figure, captured live.
- **The current price table** (``app/config/model_pricing.py``), recomputed from
  the event's token counts. Today's rates applied to old calls, which is a
  better estimate than the rate that was in the table at the time.
- **The logged cost**, for a model the table does not know. Kept rather than
  zeroed, and counted separately so the fallback's share is visible.

Reconstructed rows are stamped ``backfilled: true`` and carry a deterministic
``backfill_key``, so ``--apply`` is safe to re-run: the key is derived from the
event, a unique index enforces it, and a second run inserts nothing.

Dropped deliberately: events with neither tokens nor cost (heartbeat echoes that
would inflate the row count without adding spend), non-finite costs (``json``
parses ``NaN``/``Infinity`` happily and one poisons every sum), and exact
duplicate events. Doubled model ids (``a/b/a/b``, from a lane that stamped the
alias twice) are normalised back to one. Sticky-flip replays are recorded the
way the live path recorded them — ``background``, never charged.

Floors at 2026-08-10: before that the events lack the cost fields this depends
on, so older rows would be fiction.

Reference run, against real production Loki, 2026-08-10..08-31, no OpenRouter
lookups (so every cost is the event's own provider figure or the table)::

    30,364 raw -> 27,580 docs, $53.35

    zero-token echoes skipped                       2784
    doubled model ids normalised                    9209
    exact duplicates skipped                           0
    background rows (never charged)                18773
    unknown-model rows (kept at logged cost)           0

The doubled-id count is the whole story of this script's first version: those
9,209 rows matched no pricing entry, fell to "unknown model, keep logged cost",
and preserved dead pre-2026-08-24 table prices — reporting $136.27 for the same
window. Normalising the id first drops it to $53.35 and empties the
unknown-model bucket, which is how you can tell the fallback is now only used
for models the table genuinely does not know.

Run from the api directory (or /app inside the container)::

    python scripts/backfill_llm_calls.py --dry-run
    python scripts/backfill_llm_calls.py --days 7 --dry-run
    python scripts/backfill_llm_calls.py --apply

Environment: ``LOKI_URL`` (default ``http://loki:3100``) and
``OPENROUTER_API_KEY``. Generation lookups are cached per day under
``--cache-dir``, so an interrupted backfill costs nothing to restart.
"""

import argparse
import asyncio
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from pydantic import BaseModel

from app.config.model_pricing import MODEL_PRICING, calculate_token_cost
from app.db.mongodb.mongodb import init_mongodb
from app.db.repositories.llm_calls import LLMCallDocument, llm_calls_repository, split_lane_thread
from scripts._events import finite_cost
from scripts._loki import MAX_DAYS, fetch_day
from scripts._openrouter import GenerationRecord, default_cache_dir, resolve_generations

#: Before this the ``llm_call`` events carry no cost fields, so anything
#: reconstructed from them would be invented rather than recovered.
EARLIEST_DAY = "2026-08-10"
_BATCH = 1000


class LedgerEvent(BaseModel):
    """One ``llm_call`` log line, in the shape a ledger row is built from."""

    created_at: datetime
    day: str
    agent_name: str
    user_id: str | None = None
    model: str
    generation_id: str | None = None
    conversation_id: str | None = None
    thread_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    logged_cost: float = 0.0
    cost_source: str | None = None
    background: bool = False
    finish_reason: str | None = None
    channel: str | None = None
    #: Whether this event's model id arrived doubled and was collapsed. Counted
    #: rather than inferred later: after normalisation the id looks ordinary.
    model_was_doubled: bool = False

    @property
    def has_substance(self) -> bool:
        """Whether this event describes a call that actually did something.

        An event with no tokens AND no cost is an echo — a metering hook that
        fired on a call the provider never billed. Keeping them would inflate
        the ledger's row count with rows that answer no question.
        """
        return bool(
            self.input_tokens or self.output_tokens or self.cached_tokens or self.logged_cost
        )

    @property
    def backfill_key(self) -> str:
        """A deterministic identity for this event.

        Hashed from the fields that together identify one call — the instant, the
        lane, the user and either the generation id or the call's own token/cost
        fingerprint when the provider issued none. Deterministic so a re-run
        produces the same key and the unique index absorbs it; hashed so the key
        stays short and carries no user content.
        """
        fingerprint = "|".join(
            [
                self.created_at.isoformat(),
                self.agent_name,
                self.user_id or "",
                self.generation_id
                or f"{self.model}:{self.input_tokens}:{self.output_tokens}:{self.logged_cost}",
            ]
        )
        return hashlib.sha256(fingerprint.encode()).hexdigest()


def normalise_model(model: str) -> str:
    """Collapse a model id that was stamped twice back to one.

    A lane that applied its alias on top of an already-aliased id logged the
    name concatenated with itself. Verified on live Loki (2026-08-14):

        deepseek/deepseek-v4-flash-0731deepseek/deepseek-v4-flash-0731

    Note there is NO separator between the halves — the second copy runs
    straight into the first. A rule that split on ``/`` and compared path
    segments therefore never fired on the real data (the segment count is odd),
    which is how 9,209 rows fell through to the unknown-model branch and kept
    the dead pre-2026-08-24 table prices instead of being re-priced. So the
    comparison is on the raw string's two halves.

    Left un-normalised, the same model is two rows in every group-by AND matches
    no pricing entry, so it silently keeps whatever the table said at the time.
    """
    half, remainder = divmod(len(model), 2)
    if remainder == 0 and half > 0 and model[:half] == model[half:]:
        return model[:half]
    # The separator-joined form too, for cheap: the same alias applied twice can
    # land either way depending on which lane did the stamping, and a rule that
    # covers only the shape we happened to observe is the rule that misses the
    # next one.
    parts = model.split("/")
    segments, odd = divmod(len(parts), 2)
    if odd == 0 and segments > 0 and parts[:segments] == parts[segments:]:
        return "/".join(parts[:segments])
    return model


def parse_event(line: str) -> LedgerEvent | None:
    """One Loki line as a ledger event, or ``None`` if it is not usable."""
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict) or raw.get("llm_event") != "llm_call":
        return None
    timestamp = raw.get("time")
    if not isinstance(timestamp, str):
        return None
    cost = finite_cost(raw.get("cost_usd"))
    if cost is None:
        return None
    raw_model = str(raw.get("model") or "unknown")
    model = normalise_model(raw_model)
    # A sticky-flip replay predates the ``background`` flag on this event, so the
    # older marker is the only signal those rows carry.
    background = bool(raw.get("background") or raw.get("sticky_flip_discarded"))
    thread_id = raw.get("thread_id")
    user_id = raw.get("user_id")
    return LedgerEvent(
        created_at=datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
        day=timestamp[:10],
        agent_name=str(raw.get("agent_name") or "unknown"),
        user_id=str(user_id) if user_id else None,
        model=model,
        model_was_doubled=model != raw_model,
        generation_id=(str(raw["generation_id"]) if raw.get("generation_id") else None),
        conversation_id=None,
        thread_id=str(thread_id) if thread_id else None,
        input_tokens=int(raw.get("input_tokens") or 0),
        output_tokens=int(raw.get("output_tokens") or 0),
        cached_tokens=int(raw.get("cached_tokens") or 0),
        reasoning_tokens=int(raw.get("reasoning_tokens") or 0),
        logged_cost=cost,
        cost_source=(str(raw["cost_source"]) if raw.get("cost_source") else None),
        background=background,
        finish_reason=(str(raw["finish_reason"]) if raw.get("finish_reason") else None),
        channel=(str(raw["channel"]) if raw.get("channel") else None),
    )


class Priced(BaseModel):
    """A cost and the provenance that decided it."""

    cost: float
    source: str  # "generation" | "provider" | "table" | "logged"


def price_event(event: LedgerEvent, record: GenerationRecord | None) -> Priced:
    """What this call cost, from the most trustworthy source that can answer.

    The order is deliberate: what OpenRouter says it billed beats what the event
    recorded, which beats what today's table computes, which beats the logged
    number — and the logged number is kept rather than zeroed for a model the
    table has never heard of, because a missing rate is not a free call.
    """
    if record is not None:
        return Priced(cost=record.total_cost, source="generation")
    if event.cost_source == "provider":
        return Priced(cost=event.logged_cost, source="provider")
    if event.model not in MODEL_PRICING:
        # ``calculate_token_cost`` does not raise for an unknown model — it falls
        # back to DEFAULT_PRICING, which is ~10x the real input rate for most
        # models and would quietly overstate the whole month. Membership is
        # checked here so the fallback is the LOGGED cost, which at least came
        # from somewhere real.
        return Priced(cost=event.logged_cost, source="logged")
    computed = calculate_token_cost(
        model_name=event.model,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        cached_tokens=event.cached_tokens,
    )
    total = finite_cost(computed.get("total_cost"))
    if total is None:
        return Priced(cost=event.logged_cost, source="logged")
    return Priced(cost=total, source="table")


def build_document(event: LedgerEvent, record: GenerationRecord | None) -> LLMCallDocument:
    """One reconstructed ledger row.

    The context ids are only as good as the event carried — the wide event never
    logged ``workflow_execution_id``, ``job_id`` or latency, so those stay unset
    rather than being invented. That is exactly why rows are marked
    ``backfilled``: an analysis needing first-party precision can exclude them.
    """
    priced = price_event(event, record)
    lane = split_lane_thread(event.thread_id)
    return LLMCallDocument(
        created_at=event.created_at,
        user_id=event.user_id,
        agent_name=event.agent_name,
        background=event.background,
        # A replay, and every background lane, was never charged to the user.
        charge_to_budget=not event.background,
        model_requested=event.model,
        model_served=event.model,
        provider=record.provider_name if record is not None else None,
        input_tokens=event.input_tokens,
        cached_tokens=event.cached_tokens,
        output_tokens=event.output_tokens,
        reasoning_tokens=event.reasoning_tokens,
        cost_usd=priced.cost,
        # The ledger's own vocabulary has two values; a generation lookup is a
        # provider figure, and both table paths are the table.
        cost_source="provider" if priced.source in {"generation", "provider"} else "table",
        generation_id=event.generation_id,
        finish_reason=event.finish_reason,
        conversation_id=event.conversation_id or lane.conversation_id,
        lane_thread=lane.lane_thread,
        channel=event.channel,
        backfilled=True,
        backfill_key=event.backfill_key,
    )


class Anomalies(BaseModel):
    """Every judgement the run made on the operator's behalf, counted.

    A single "N dropped" total says nothing about whether a run is trustworthy:
    dropping echoes is routine, dropping thousands of rows to an unknown model
    is a mis-pricing hiding behind a plausible number. These are the buckets
    that distinguish the two, so they are reported rather than summed away —
    the doubled-id count is exactly the signal that would have surfaced 9,209
    mis-priced rows before they were written.
    """

    echoes_skipped: int = 0
    duplicates_skipped: int = 0
    doubled_ids_normalised: int = 0
    background_rows: int = 0
    generations_resolved: int = 0
    generations_missing: int = 0
    unknown_model_rows: int = 0

    def observe(self, event: LedgerEvent, priced: Priced) -> None:
        """Count what this kept event tells us about the run."""
        if event.model_was_doubled:
            self.doubled_ids_normalised += 1
        if event.background:
            self.background_rows += 1
        if priced.source == "logged":
            self.unknown_model_rows += 1

    def count_lookups(self, generations: Mapping[str, GenerationRecord | None]) -> None:
        """Split the generation lookups into answered and dropped.

        A 404 is OpenRouter having aged the generation out — unverifiable, not
        an error — but a run where everything 404s is priced from the table
        throughout, and that is worth seeing.
        """
        for record in generations.values():
            if record is None:
                self.generations_missing += 1
            else:
                self.generations_resolved += 1

    def render(self) -> None:
        rows = [
            ("zero-token echoes skipped", self.echoes_skipped),
            ("doubled model ids normalised", self.doubled_ids_normalised),
            ("exact duplicates skipped", self.duplicates_skipped),
            ("background rows (never charged)", self.background_rows),
            ("generation lookups resolved", self.generations_resolved),
            ("generation lookups missing", self.generations_missing),
            ("unknown-model rows (kept at logged cost)", self.unknown_model_rows),
        ]
        print("\nanomalies")
        print("-" * 52)
        for label, count in rows:
            print(f"{label:<44}{count:>8}")


def select_events(
    events: Iterable[LedgerEvent], anomalies: Anomalies | None = None
) -> list[LedgerEvent]:
    """Drop the events that must not become rows, newest-safe and order-stable.

    Echoes (no tokens, no cost) and exact duplicates — the same call logged
    twice, which the ledger would otherwise count twice. Both are counted into
    ``anomalies`` rather than silently discarded.
    """
    tally = anomalies if anomalies is not None else Anomalies()
    seen: set[str] = set()
    kept: list[LedgerEvent] = []
    for event in events:
        if not event.has_substance:
            tally.echoes_skipped += 1
            continue
        key = event.backfill_key
        if key in seen:
            tally.duplicates_skipped += 1
            continue
        seen.add(key)
        kept.append(event)
    return kept


class DaySummary(BaseModel):
    """What one day contributed, for the dry-run table."""

    day: str
    raw: int
    docs: int
    dollars: float
    from_generation: int
    from_table: int
    from_logged: int


def summarise(
    day: str, raw: int, docs: Sequence[LLMCallDocument], sources: Mapping[str, int]
) -> DaySummary:
    return DaySummary(
        day=day,
        raw=raw,
        docs=len(docs),
        dollars=sum(doc.cost_usd for doc in docs),
        from_generation=sources.get("generation", 0),
        from_table=sources.get("table", 0) + sources.get("provider", 0),
        from_logged=sources.get("logged", 0),
    )


def render(rows: Sequence[DaySummary]) -> None:
    """The per-day raw -> docs -> $ table the dry run reports."""
    header = f"{'date':<12}{'raw':>8}{'docs':>8}{'$':>12}{'gen':>8}{'table':>8}{'logged':>8}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row.day:<12}{row.raw:>8}{row.docs:>8}{row.dollars:>12.4f}"
            f"{row.from_generation:>8}{row.from_table:>8}{row.from_logged:>8}"
        )
    print("-" * len(header))
    print(
        f"{'total':<12}{sum(r.raw for r in rows):>8}{sum(r.docs for r in rows):>8}"
        f"{sum(r.dollars for r in rows):>12.4f}"
    )


def wanted_days(days: int) -> list[str]:
    """The trailing window, floored at :data:`EARLIEST_DAY`."""
    today = datetime.now(UTC).date()
    floor = date.fromisoformat(EARLIEST_DAY)
    candidates = [today - timedelta(days=offset) for offset in reversed(range(days))]
    return [day.isoformat() for day in candidates if day >= floor]


async def backfill(days: int, cache_dir: Path, apply: bool) -> None:
    loki_url = os.environ.get("LOKI_URL", "http://loki:3100")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key and apply:
        raise SystemExit("OPENROUTER_API_KEY is not set — run through `infisical run --`.")
    if not api_key:
        # A dry run is a read-only preview and must not require a paid-API
        # credential to answer "how many rows, and roughly what do they cost".
        # Without the key the generation lookups are skipped: rows the event
        # already priced from the provider keep that figure, the rest are priced
        # from the table, and NOTHING is verified against OpenRouter. Loud,
        # because it changes what the dollar column means.
        print("NO OPENROUTER_API_KEY — generation lookups skipped; costs are unverified\n")

    if apply:
        init_mongodb()

    summaries: list[DaySummary] = []
    anomalies = Anomalies()
    written = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        for day in wanted_days(days):
            events = await fetch_day(client, loki_url, day, parse_event)
            kept = select_events(events, anomalies)
            generations = (
                await resolve_generations(
                    client,
                    api_key,
                    (event.generation_id for event in kept if event.generation_id),
                    cache_dir / f"{day}.json",
                )
                if api_key
                else {}
            )
            anomalies.count_lookups(generations)
            sources: dict[str, int] = defaultdict(int)
            docs: list[LLMCallDocument] = []
            for event in kept:
                record = generations.get(event.generation_id) if event.generation_id else None
                priced = price_event(event, record)
                sources[priced.source] += 1
                anomalies.observe(event, priced)
                docs.append(build_document(event, record))
            summaries.append(summarise(day, len(events), docs, sources))
            print(f"{day}: {len(events)} raw -> {len(docs)} docs")
            if apply:
                for start in range(0, len(docs), _BATCH):
                    written += await llm_calls_repository.insert_backfilled(
                        docs[start : start + _BATCH]
                    )

    print()
    render(summaries)
    anomalies.render()
    if apply:
        print(f"\nAPPLIED — {written} rows created (re-runs insert nothing)")
    else:
        print("\nDRY RUN — nothing was written (pass --apply to write)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the rows to llm_calls")
    mode.add_argument("--dry-run", action="store_true", help="report only (default)")
    parser.add_argument(
        "--days", type=int, default=MAX_DAYS, help=f"trailing window (max {MAX_DAYS})"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=default_cache_dir(),
        help="where per-day generation lookups are cached",
    )
    args = parser.parse_args()
    if args.days < 1:
        raise SystemExit("--days must be at least 1")
    asyncio.run(backfill(min(args.days, MAX_DAYS), args.cache_dir, args.apply))


if __name__ == "__main__":
    main()
