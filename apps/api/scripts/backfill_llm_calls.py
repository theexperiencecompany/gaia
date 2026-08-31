#!/usr/bin/env python3
"""Rebuild the ``llm_calls`` ledger from the log history that predates it.

The ledger starts empty on the day it ships, so every cost question about the
past still has to be answered by scraping logs — which is the problem it exists
to end. Loki holds one ``llm_call`` wide event per model call for 30 days, and
those events carry almost everything a ledger row needs, so the recent past can
be reconstructed instead of lost.

The dollars, however, cannot be trusted to the events alone. The logged costs
came from a flat per-model table while the real rate depends on which upstream
served the call — a spread of more than 9x — and whole stretches of the window
have no events at all (log retention, the 2026-08-24 deploy). Reconciling the
events against OpenRouter's activity API showed request and token counts
matching within a few percent on stable days, and dollars off by a third. So
this backfill anchors on OpenRouter's own books:

- **The activity API** (``--or-activity`` snapshots and/or a live fetch with
  ``OPENROUTER_MANAGEMENT_KEY``) — per day and model: billed dollars, token
  counts, request counts. See ``scripts/_activity.py``. For every (day, model)
  it covers, the day's real dollars are distributed across that day's call rows
  in proportion to each call's best-known cost, scaled by how much of the day's
  tokens our events actually observed. What OpenRouter billed beyond what the
  events can attribute becomes one explicit *unattributed* row per (day, model)
  — visible as a gap, never smeared into other calls, never dropped. The
  ledger's total for an anchored day therefore equals OpenRouter's total for
  that day, exactly.
- **Per-generation lookups** (``GET /api/v1/generation?id=<id>``) and costs the
  event captured live with ``cost_source="provider"`` — used as allocation
  weights, since they carry the true per-call price shape.
- **The current price table**, recomputed from token counts, for calls on days
  the activity window does not reach (it is a rolling ~25 days) and for models
  that never went through OpenRouter.
- **The logged cost**, for a model the table does not know. Kept rather than
  zeroed, and counted separately so the fallback's share is visible.

Reconstructed rows are stamped ``backfilled: true`` and carry a deterministic
``backfill_key``, so ``--apply`` is safe to re-run: the key is derived from the
event, a unique index enforces it, and a second run inserts nothing. Events at
or after the instant the live ledger started writing are excluded (detected
from the collection itself on ``--apply``, or via ``--until``), because those
calls already have first-party rows.

Dropped deliberately: events with neither tokens nor cost (heartbeat echoes),
non-finite costs (``json`` parses ``NaN`` happily and one poisons every sum),
exact duplicates, and double-logged copies — during 2026-08-13..18 the metering
seam logged many calls twice, with the copies differing only in timestamp
microseconds, which is why identity here is the call's second + shape rather
than the raw line. Doubled model ids (``a/ba/b``, no separator) are normalised
back to one. Sticky-flip replays are recorded the way the live path recorded
them — ``background``, never charged.

Floors at 2026-08-10 for event reconstruction: before that the events lack the
cost fields this depends on. Activity-anchored *unattributed* rows are not
floored — OpenRouter billed 2026-08-06..09 and those dollars are accounted for
even though no per-call rows can be built for them.

Run from the api directory (or /app inside the container)::

    python scripts/backfill_llm_calls.py --dry-run --or-activity /tmp/or_activity.json
    python scripts/backfill_llm_calls.py --apply --or-activity /tmp/or_activity.json

Environment: ``LOKI_URL`` (default ``http://loki:3100``), ``OPENROUTER_API_KEY``
for generation lookups (cached per day under ``--cache-dir``), and optionally
``OPENROUTER_MANAGEMENT_KEY`` to fetch the activity window live.
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
from scripts._activity import ActivityPool, load_pools
from scripts._events import finite_cost
from scripts._loki import MAX_DAYS, fetch_day
from scripts._openrouter import GenerationRecord, default_cache_dir, resolve_generations

#: Before this the ``llm_call`` events carry no cost fields, so anything
#: reconstructed from them would be invented rather than recovered.
EARLIEST_DAY = "2026-08-10"
_BATCH = 1000
#: Below this an unattributed remainder is rounding noise, not a gap.
_REMAINDER_FLOOR_USD = 0.0005


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

    @property
    def call_shape(self) -> tuple:
        """The second-resolution identity that catches double-logged copies.

        During 2026-08-13..18 the metering seam logged many calls twice; the
        copies differ in timestamp microseconds (two sinks, two clock reads) and
        sometimes in which copy carries the generation id, so the exact
        ``backfill_key`` never matches them. The same user, model and token
        counts within the same second is one call: real traffic at 30k-token
        prompts does not produce two independent identical calls in a second.
        """
        return (
            int(self.created_at.timestamp()),
            self.user_id or "",
            self.model,
            self.input_tokens,
            self.output_tokens,
            self.cached_tokens,
        )


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

    On a day the activity window anchors, this figure becomes the call's
    *weight* and the absolute dollars come from the day's pool; elsewhere it is
    the cost itself.
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
        # The ledger's own vocabulary: a generation lookup is a provider figure,
        # both table paths are the table. Anchored days overwrite this with
        # "allocated" in the allocation pass.
        cost_source="provider" if priced.source in {"generation", "provider"} else "table",
        generation_id=event.generation_id,
        finish_reason=event.finish_reason,
        conversation_id=event.conversation_id or lane.conversation_id,
        lane_thread=lane.lane_thread,
        channel=event.channel,
        backfilled=True,
        backfill_key=event.backfill_key,
    )


def unattributed_document(
    day: str,
    model: str,
    cost: float,
    missing_prompt: int,
    missing_completion: int,
    missing_reasoning: int,
) -> LLMCallDocument:
    """The remainder row for spend OpenRouter billed but no event can carry.

    One per (day, model): background, never charged, no user — a visible gap in
    the ledger's own vocabulary rather than dollars smeared across unrelated
    calls or silently dropped. ``requests`` has no field of its own, so the gap
    is sized in tokens and dollars.
    """
    return LLMCallDocument(
        created_at=datetime.fromisoformat(day).replace(hour=12, tzinfo=UTC),
        user_id=None,
        agent_name="or_unattributed",
        background=True,
        charge_to_budget=False,
        model_requested=model,
        model_served=None,
        provider=None,
        input_tokens=missing_prompt,
        cached_tokens=0,
        output_tokens=missing_completion,
        reasoning_tokens=missing_reasoning,
        cost_usd=cost,
        cost_source="allocated",
        generation_id=None,
        finish_reason=None,
        conversation_id=None,
        lane_thread=None,
        channel=None,
        backfilled=True,
        backfill_key=hashlib.sha256(f"or-unattributed|{day}|{model}".encode()).hexdigest(),
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
    double_logged_skipped: int = 0
    doubled_ids_normalised: int = 0
    background_rows: int = 0
    generations_resolved: int = 0
    generations_missing: int = 0
    unknown_model_rows: int = 0
    allocated_rows: int = 0
    unattributed_rows: int = 0
    beyond_ledger_skipped: int = 0

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
            ("double-logged copies skipped", self.double_logged_skipped),
            ("exact duplicates skipped", self.duplicates_skipped),
            ("events after ledger go-live skipped", self.beyond_ledger_skipped),
            ("background rows (never charged)", self.background_rows),
            ("generation lookups resolved", self.generations_resolved),
            ("generation lookups missing", self.generations_missing),
            ("unknown-model rows (kept at logged cost)", self.unknown_model_rows),
            ("rows re-priced from OpenRouter's day total", self.allocated_rows),
            ("unattributed remainder rows", self.unattributed_rows),
        ]
        print("\nanomalies")
        print("-" * 52)
        for label, count in rows:
            print(f"{label:<44}{count:>8}")


def _prefer(candidate: LedgerEvent, held: LedgerEvent) -> bool:
    """Between two copies of one call, which carries more truth.

    The copy with a generation id can be audited against OpenRouter later; the
    copy with a provider-captured cost carries the real price. Either beats a
    copy with neither.
    """
    if bool(candidate.generation_id) != bool(held.generation_id):
        return bool(candidate.generation_id)
    if (candidate.cost_source == "provider") != (held.cost_source == "provider"):
        return candidate.cost_source == "provider"
    return False


def select_events(
    events: Iterable[LedgerEvent], anomalies: Anomalies | None = None
) -> list[LedgerEvent]:
    """Drop the events that must not become rows, order-stable.

    Echoes (no tokens, no cost), double-logged copies (same call, two log
    lines — see :meth:`LedgerEvent.call_shape`), and exact duplicates. All are
    counted into ``anomalies`` rather than silently discarded, and when a call
    was logged twice the copy that carries a generation id or a provider cost
    is the one kept.
    """
    tally = anomalies if anomalies is not None else Anomalies()
    groups: dict[tuple, list[LedgerEvent]] = {}
    order: list[LedgerEvent] = []
    for event in events:
        if not event.has_substance:
            tally.echoes_skipped += 1
            continue
        group = groups.setdefault(event.call_shape, [])
        held = next(
            (
                candidate
                for candidate in group
                # Two events with two DIFFERENT generation ids are two calls no
                # matter how alike they look — the provider issued both ids.
                if not (
                    candidate.generation_id
                    and event.generation_id
                    and candidate.generation_id != event.generation_id
                )
            ),
            None,
        )
        if held is None:
            group.append(event)
            order.append(event)
            continue
        tally.double_logged_skipped += 1
        if _prefer(event, held):
            group[group.index(held)] = event
            order[order.index(held)] = event
    seen: set[str] = set()
    kept: list[LedgerEvent] = []
    for event in order:
        if event.backfill_key in seen:
            tally.duplicates_skipped += 1
            continue
        seen.add(event.backfill_key)
        kept.append(event)
    return kept


class Entry(BaseModel):
    """One kept event with its document and pre-allocation price."""

    event: LedgerEvent
    doc: LLMCallDocument
    priced: Priced


def allocate_day(
    day: str,
    entries: Sequence[Entry],
    pools: Mapping[tuple[str, str], ActivityPool],
    consumed: set[tuple[str, str]],
    anomalies: Anomalies,
) -> tuple[list[LLMCallDocument], float, float]:
    """Anchor one day's rows to OpenRouter's billed total for that day.

    For each (day, model) the activity window covers: the pool's real dollars,
    scaled by the share of the day's tokens our events actually observed, are
    distributed across the rows in proportion to each row's best-known cost —
    so the *shape* of per-call pricing (cache discounts, output rates, the
    generation lookups that resolved) survives while the *level* becomes what
    OpenRouter actually charged. The unobserved share becomes one unattributed
    row. Days and models outside the window are left untouched.

    Returns the unattributed rows plus (anchored $, unattributed $) for the
    day's summary line.
    """
    by_model: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        by_model[entry.doc.model_requested].append(entry)
    remainder_docs: list[LLMCallDocument] = []
    anchored_usd = 0.0
    unattributed_usd = 0.0
    for model, group in by_model.items():
        pool = pools.get((day, model))
        if pool is None:
            continue
        consumed.add((day, model))
        our_prompt = sum(entry.event.input_tokens for entry in group)
        our_completion = sum(entry.event.output_tokens for entry in group)
        our_reasoning = sum(entry.event.reasoning_tokens for entry in group)
        our_tokens = our_prompt + our_completion + our_reasoning
        coverage = min(1.0, our_tokens / pool.tokens) if pool.tokens else 1.0
        attributable = pool.usd * coverage
        weights = [max(entry.priced.cost, 0.0) for entry in group]
        total_weight = sum(weights)
        for entry, weight in zip(group, weights, strict=True):
            share = weight / total_weight if total_weight else 1.0 / len(group)
            entry.doc.cost_usd = attributable * share
            entry.doc.cost_source = "allocated"
            anomalies.allocated_rows += 1
        anchored_usd += pool.usd
        leftover = pool.usd - attributable
        if leftover >= _REMAINDER_FLOOR_USD:
            remainder_docs.append(
                unattributed_document(
                    day,
                    model,
                    leftover,
                    max(0, pool.prompt_tokens - our_prompt),
                    max(0, pool.completion_tokens - our_completion),
                    max(0, pool.reasoning_tokens - our_reasoning),
                )
            )
            unattributed_usd += leftover
            anomalies.unattributed_rows += 1
    return remainder_docs, anchored_usd, unattributed_usd


def leftover_pools(
    pools: Mapping[tuple[str, str], ActivityPool],
    consumed: set[tuple[str, str]],
    today: str,
    anomalies: Anomalies,
) -> list[LLMCallDocument]:
    """Unattributed rows for spend with no events at all.

    Days before the event floor (2026-08-06..09), days log retention has
    already deleted, and models that never produced a wide event: OpenRouter
    billed them, so they are rows — fully unattributed. The current UTC day is
    excluded because its pool is still accumulating and would under-anchor.
    """
    docs: list[LLMCallDocument] = []
    for (day, model), pool in sorted(pools.items()):
        if (day, model) in consumed or day >= today:
            continue
        if pool.usd < _REMAINDER_FLOOR_USD:
            continue
        docs.append(
            unattributed_document(
                day,
                model,
                pool.usd,
                pool.prompt_tokens,
                pool.completion_tokens,
                pool.reasoning_tokens,
            )
        )
        anomalies.unattributed_rows += 1
    return docs


class DaySummary(BaseModel):
    """What one day contributed, for the dry-run table."""

    day: str
    raw: int
    docs: int
    dollars: float
    or_dollars: float | None = None
    or_requests: int | None = None
    unattributed: float = 0.0
    from_generation: int = 0
    from_table: int = 0
    from_logged: int = 0


def render(rows: Sequence[DaySummary]) -> None:
    """The per-day raw -> docs -> $ table the dry run reports.

    ``$`` is what the day's rows sum to; ``OR $`` is what OpenRouter billed for
    the day where the activity window reaches, and on those days the two are
    equal by construction — a day where they differ is a bug, not a rounding
    story. ``unattr $`` is the slice of ``$`` carried by remainder rows.
    """
    header = (
        f"{'date':<12}{'raw':>8}{'docs':>8}{'$':>12}{'OR $':>10}{'OR req':>8}"
        f"{'unattr $':>10}{'gen':>6}{'table':>7}{'logged':>7}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        or_usd = f"{row.or_dollars:>10.4f}" if row.or_dollars is not None else f"{'—':>10}"
        or_req = f"{row.or_requests:>8}" if row.or_requests is not None else f"{'—':>8}"
        print(
            f"{row.day:<12}{row.raw:>8}{row.docs:>8}{row.dollars:>12.4f}{or_usd}{or_req}"
            f"{row.unattributed:>10.4f}{row.from_generation:>6}{row.from_table:>7}{row.from_logged:>7}"
        )
    print("-" * len(header))
    total_or = sum(r.or_dollars for r in rows if r.or_dollars is not None)
    print(
        f"{'total':<12}{sum(r.raw for r in rows):>8}{sum(r.docs for r in rows):>8}"
        f"{sum(r.dollars for r in rows):>12.4f}{total_or:>10.4f}{'':>8}"
        f"{sum(r.unattributed for r in rows):>10.4f}"
    )


def wanted_days(days: int) -> list[str]:
    """The trailing window, floored at :data:`EARLIEST_DAY`."""
    today = datetime.now(UTC).date()
    floor = date.fromisoformat(EARLIEST_DAY)
    candidates = [today - timedelta(days=offset) for offset in reversed(range(days))]
    return [day.isoformat() for day in candidates if day >= floor]


async def ledger_live_floor(until: datetime | None, apply: bool) -> datetime | None:
    """The instant the live ledger started writing, before which backfill owns.

    Live rows and backfilled rows for the same call would double every sum, so
    events at or after this instant are skipped. On ``--apply`` the collection
    itself answers (the earliest non-backfilled row); ``--until`` overrides for
    dry runs without a database.
    """
    if until is not None:
        return until
    if not apply:
        return None
    return await llm_calls_repository.first_live_call_at()


async def backfill(
    days: int,
    cache_dir: Path,
    apply: bool,
    activity_paths: list[Path],
    until: datetime | None,
) -> None:
    loki_url = os.environ.get("LOKI_URL", "http://loki:3100")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    management_key = os.environ.get("OPENROUTER_MANAGEMENT_KEY")
    if not api_key and apply:
        raise SystemExit("OPENROUTER_API_KEY is not set — run through `infisical run --`.")
    if not api_key:
        # A dry run is a read-only preview and must not require a paid-API
        # credential to answer "how many rows, and roughly what do they cost".
        # Without the key the generation lookups are skipped: rows the event
        # already priced from the provider keep that figure, the rest are priced
        # from the table or the day pool, and per-call figures are unverified.
        print("NO OPENROUTER_API_KEY — generation lookups skipped\n")

    pools = await load_pools(activity_paths, management_key)
    if pools:
        pool_days = sorted({day for day, _ in pools})
        print(
            f"activity anchor: {len(pools)} (day, model) pools, "
            f"{pool_days[0]}..{pool_days[-1]}, ${sum(p.usd for p in pools.values()):.4f} billed\n"
        )
    else:
        print(
            "NO ACTIVITY ANCHOR — pass --or-activity or set OPENROUTER_MANAGEMENT_KEY; "
            "costs will NOT reconcile to OpenRouter's billed totals\n"
        )

    if apply:
        init_mongodb()
    live_floor = await ledger_live_floor(until, apply)
    if live_floor is not None:
        print(f"ledger go-live floor: events at/after {live_floor.isoformat()} are skipped\n")

    today = datetime.now(UTC).date().isoformat()
    summaries: list[DaySummary] = []
    anomalies = Anomalies()
    consumed: set[tuple[str, str]] = set()
    written = 0

    async def write(docs: Sequence[LLMCallDocument]) -> int:
        count = 0
        for start in range(0, len(docs), _BATCH):
            count += await llm_calls_repository.insert_backfilled(docs[start : start + _BATCH])
        return count

    async with httpx.AsyncClient(timeout=60.0) as client:
        for day in wanted_days(days):
            events = await fetch_day(client, loki_url, day, parse_event)
            kept = select_events(events, anomalies)
            if live_floor is not None:
                before = len(kept)
                kept = [event for event in kept if event.created_at < live_floor]
                anomalies.beyond_ledger_skipped += before - len(kept)
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
            entries: list[Entry] = []
            for event in kept:
                record = generations.get(event.generation_id) if event.generation_id else None
                priced = price_event(event, record)
                sources[priced.source] += 1
                anomalies.observe(event, priced)
                entries.append(Entry(event=event, doc=build_document(event, record), priced=priced))
            # Today's pool is still accumulating on OpenRouter's side; anchoring
            # to it would scale a full day of events down to a partial total.
            remainder_docs, anchored_usd, unattributed_usd = allocate_day(
                day, entries, pools if day < today else {}, consumed, anomalies
            )
            docs = [entry.doc for entry in entries] + remainder_docs
            day_requests = sum(
                pool.requests for (pool_day, _), pool in pools.items() if pool_day == day
            )
            summaries.append(
                DaySummary(
                    day=day,
                    raw=len(events),
                    docs=len(docs),
                    dollars=sum(doc.cost_usd for doc in docs),
                    or_dollars=(
                        sum(p.usd for (d, _), p in pools.items() if d == day)
                        if any(d == day for d, _ in pools)
                        else None
                    ),
                    or_requests=day_requests if any(d == day for d, _ in pools) else None,
                    unattributed=unattributed_usd,
                    from_generation=sources.get("generation", 0),
                    from_table=sources.get("table", 0) + sources.get("provider", 0),
                    from_logged=sources.get("logged", 0),
                )
            )
            print(f"{day}: {len(events)} raw -> {len(docs)} docs")
            if apply:
                written += await write(docs)

    orphan_docs = leftover_pools(pools, consumed, today, anomalies)
    if orphan_docs:
        print("\nOpenRouter billed, no events at all (fully unattributed rows):")
        for doc in orphan_docs:
            print(
                f"  {doc.created_at.date()}  {doc.model_requested:<40}"
                f"  {doc.input_tokens + doc.output_tokens + doc.reasoning_tokens:>12,} tok"
                f"  ${doc.cost_usd:.4f}"
            )
        if apply:
            written += await write(orphan_docs)

    print()
    render(summaries)
    anomalies.render()
    ledger_total = sum(row.dollars for row in summaries) + sum(d.cost_usd for d in orphan_docs)
    anchored_total = sum(pool.usd for key, pool in pools.items() if key[0] < today)
    print(
        f"\nledger total ${ledger_total:.4f} = OpenRouter-anchored ${anchored_total:.4f}"
        f" + non-OpenRouter/table ${ledger_total - anchored_total:.4f}"
    )
    if apply:
        print(f"APPLIED — {written} rows created (re-runs insert nothing)")
    else:
        print("DRY RUN — nothing was written (pass --apply to write)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write the rows to llm_calls")
    mode.add_argument("--dry-run", action="store_true", help="report only (default)")
    parser.add_argument(
        "--days", type=int, default=MAX_DAYS, help=f"trailing window (max {MAX_DAYS})"
    )
    parser.add_argument(
        "--or-activity",
        type=Path,
        action="append",
        default=[],
        help="OpenRouter /api/v1/activity snapshot JSON; repeatable, merged with any live fetch",
    )
    parser.add_argument(
        "--until",
        type=datetime.fromisoformat,
        default=None,
        help="skip events at/after this instant (default on --apply: first live ledger row)",
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
    until = args.until
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    asyncio.run(
        backfill(min(args.days, MAX_DAYS), args.cache_dir, args.apply, args.or_activity, until)
    )


if __name__ == "__main__":
    main()
