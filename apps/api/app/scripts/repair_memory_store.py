#!/usr/bin/env python3
"""Repair a user's memory store after the extraction/reconciliation fixes.

The fixes change what gets written from now on. They do not touch what is
already there, and what is already there is the problem:

- **Coexisting EXTENDS pairs.** EXTENDS used to write a child alongside its
  still-live parent, so both versions of one subject-attribute stayed in
  recall. In the production store 329 live rows (36%) were EXTENDS children of
  a live parent. This retires each such parent into its child's chain.
- **State rows that never expire.** The extractor almost never set an expiry
  (19 of 1,028 rows), so counts, balances, connection statuses and deployment
  states are still live months later. Rows already carrying
  ``shelf_life='state'`` are retired past the window; older rows all read as
  'durable' because the column post-dates them, so those fall back to a
  phrase heuristic ("as of", "currently", "is failing", "disconnected",
  "pending").
- **Documents written from a corrupted draft.** user.md and people.md are
  re-derived from every live durable fact once the rows above are gone, and
  agenda.md is re-rendered from its rows.

Usage::

    cd apps/api
    uv run python -m app.scripts.repair_memory_store --user <id>            # dry run
    uv run python -m app.scripts.repair_memory_store --user <id> --apply    # commit

Run ``--help`` for the flags: this docstring IS the parser's description, so a
second copy of them here renders twice and drifts from the one argparse builds.

``--retire-ids`` is the one that needs more than its one-liner: it forgets a
memory id outright, for rows a human has read and judged wrong.

Every mode prints the full plan first. Nothing is written without ``--apply``.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import re
import uuid

from app.constants.memory import (
    STATE_FACT_TTL_DAYS,
    MemoryRelationType,
    MemoryShelfLife,
)
from app.core.provider_registration import register_lazy_providers
from app.db.postgresql import close_postgresql_db
from app.memory import pg_store
from app.memory.consolidation import consolidate, render_agenda_document
from app.memory.management import forget_memory
from app.models.memory_db_models import MemoryRecord

# Phrases that mark a sentence as a snapshot rather than a standing truth.
# Word-bounded so "concurrency" is not read as "currently". Applied ONLY to
# rows old enough that a snapshot is certainly stale, and only when the row
# predates the shelf_life column.
_STATE_PHRASES = re.compile(
    r"\b(as of|currently|is failing|are failing|disconnected|not connected|pending)\b",
    re.IGNORECASE,
)

_EXTENDS_RETIRE_REASON = "superseded by its EXTENDS child (memory-store repair)"
_STATE_RETIRE_REASON = "stale state snapshot (memory-store repair)"
_MANUAL_RETIRE_REASON = "retired by hand (memory-store repair)"


def looks_like_state(content: str) -> bool:
    """Whether a fact reads as a value that was only true as of some moment."""
    return _STATE_PHRASES.search(content) is not None


def extends_parents_to_retire(
    rows: list[MemoryRecord],
) -> list[tuple[MemoryRecord, MemoryRecord]]:
    """``(parent, newest child)`` for every live parent of a live EXTENDS child.

    Only EXTENDS pairs qualify: an UPDATES child already flipped its parent out
    of the live set when it was written.
    """
    by_id = {row.id: row for row in rows}
    newest_child: dict[uuid.UUID, MemoryRecord] = {}
    for row in rows:
        if row.relation_type != MemoryRelationType.EXTENDS.value or row.parent_id is None:
            continue
        if row.parent_id not in by_id:
            continue
        current = newest_child.get(row.parent_id)
        if current is None or row.created_at > current.created_at:
            newest_child[row.parent_id] = row
    return [(by_id[parent_id], child) for parent_id, child in newest_child.items()]


def state_rows_to_forget(
    rows: list[MemoryRecord], *, now: datetime, age_days: int = STATE_FACT_TTL_DAYS
) -> list[MemoryRecord]:
    """Live rows old enough that their snapshot value is certainly stale.

    A row that already carries ``shelf_life='state'`` qualifies on age alone.
    Everything older than the column reads as 'durable', so those qualify only
    when the text itself reads as a snapshot.
    """
    cutoff = now - timedelta(days=age_days)
    stale: list[MemoryRecord] = []
    for row in rows:
        if row.created_at > cutoff:
            continue
        if row.shelf_life == MemoryShelfLife.STATE.value or looks_like_state(row.content):
            stale.append(row)
    return stale


async def _repair_user(user_id: str, args: argparse.Namespace) -> int:
    """Print (and optionally apply) the repair plan for one user."""
    now = datetime.now(UTC)
    rows = await pg_store.get_all_live_memories(user_id)
    print(f"\n{'=' * 78}\nUser {user_id}: {len(rows)} live memories\n{'=' * 78}")

    extends_pairs = extends_parents_to_retire(rows)
    print(f"\nEXTENDS parents still live alongside their child: {len(extends_pairs)}")
    for parent, child in extends_pairs:
        print(f"  - retire {parent.id}: {parent.content!r}")
        print(f"      kept  {child.id}: {child.content!r}")

    stale = state_rows_to_forget(rows, now=now, age_days=args.state_age_days)
    print(f"\nStale state snapshots older than {args.state_age_days}d: {len(stale)}")
    for row in stale:
        print(f"  - forget {row.id} ({row.created_at:%Y-%m-%d}): {row.content!r}")

    manual = [row for row in rows if str(row.id) in set(args.retire_ids or [])]
    if manual:
        print(f"\nExplicitly retired by --retire-ids: {len(manual)}")
        for row in manual:
            print(f"  - forget {row.id}: {row.content!r}")

    print(
        f"\nSummary: {len(extends_pairs)} EXTENDS parent(s), {len(stale)} stale snapshot(s), "
        f"{len(manual)} explicit — then user.md/people.md rebuilt and agenda.md re-rendered."
    )

    if not args.apply:
        print("\nDry run only. Re-run with --apply to commit.")
        return 0

    for parent, _child in extends_pairs:
        await forget_memory(user_id, str(parent.id), _EXTENDS_RETIRE_REASON)
    for row in stale:
        await forget_memory(user_id, str(row.id), _STATE_RETIRE_REASON)
    for row in manual:
        await forget_memory(user_id, str(row.id), _MANUAL_RETIRE_REASON)

    # Rebuild AFTER the retirements, so the documents are derived from the
    # repaired corpus rather than from the one that corrupted them.
    await render_agenda_document(user_id)
    rewritten = await consolidate(user_id)
    print(f"\nApplied. Rewrote: {', '.join(doc.value for doc in rewritten) or '(nothing)'}")
    return 0


async def _run(args: argparse.Namespace) -> int:
    """Bootstrap the providers a script has no lifespan to build, then repair.

    Mongo self-initialises on first collection access, but the memory store's
    Postgres engine is a lazy provider, and outside the API process nobody has
    registered it: every query raised ``Provider 'postgresql_engine' not found in
    registry``. Registration is bookkeeping only (no I/O); the engine itself is
    built on first use and disposed here so the script exits without a warning
    about an open pool.
    """
    register_lazy_providers("main_app")
    try:
        for user_id in args.user:
            await _repair_user(user_id, args)
    finally:
        await close_postgresql_db()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user", action="append", required=True, help="User id to repair (repeatable)."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Persist changes (otherwise dry run only)."
    )
    parser.add_argument(
        "--retire-ids", action="append", help="Forget this memory id outright (repeatable)."
    )
    parser.add_argument(
        "--state-age-days",
        type=int,
        default=STATE_FACT_TTL_DAYS,
        help="Age past which a state-like row is retired.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
