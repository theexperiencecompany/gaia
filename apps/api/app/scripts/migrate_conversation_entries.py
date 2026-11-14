#!/usr/bin/env python3
"""Move every conversation's embedded messages array into conversation_entries.

Element i becomes the entry at seq i+1; the array stays in place until
--drop-embedded. An element with no message_id, or one repeating an earlier
element's, first gets a fresh id written back into the array. Safe to re-run:
each pass visits only the conversations whose array changed since it was
copied (any append, trim or in-place edit), and merges them by message id.

Cutover, in this order:
  1. --apply while the old build serves (repeat until it reports 0 raced).
  2. Fence: stop the old build, so nothing writes an embedded array.
  3. --apply again (the final full pass), then --verify; both must exit 0.
  4. Deploy the new build.
  5. Later, --drop-embedded --apply: it verifies every conversation first and
     drops nothing unless all pass, then unsets each array only while it is
     exactly the one verified.

Rollback before step 5: redeploy the old build. The arrays are untouched, so it
reads every message written before the cutover; what the new build wrote in
between stays in conversation_entries, and the next cutover (steps 1-4) merges
the old build's later writes after it. After step 5 there is no rollback but a
database restore.

Usage::

    cd apps/api
    uv run python -m app.scripts.migrate_conversation_entries               # dry run
    uv run python -m app.scripts.migrate_conversation_entries --apply
    uv run python -m app.scripts.migrate_conversation_entries --verify
    uv run python -m app.scripts.migrate_conversation_entries --drop-embedded --apply
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

from app.db.repositories.conversation_entries_migration import (
    HeadRef,
    MigrationAction,
    VerifyReport,
    conversation_entries_migration,
)

_BATCH = 200


async def _heads(
    scan: Callable[[str | None], Awaitable[list[HeadRef]]],
) -> AsyncIterator[HeadRef]:
    """Walk heads in _id order one batch at a time, never holding more than a batch."""
    after: str | None = None
    seen = 0
    while batch := await scan(after):
        for ref in batch:
            yield ref
        seen += len(batch)
        after = batch[-1].head_id
        # pragma: no mutate start — flush only paces the progress output
        print(f"... {seen} conversations scanned (resume after _id {after})", flush=True)
        # pragma: no mutate end


def _embedded(after: str | None) -> Awaitable[list[HeadRef]]:
    return conversation_entries_migration.heads_with_embedded(after_head_id=after, batch=_BATCH)


async def _migrate(args: argparse.Namespace) -> int:
    actions: Counter[MigrationAction] = Counter()
    copied = identified = 0
    async for ref in _heads(
        lambda after: conversation_entries_migration.heads_to_migrate(
            after_head_id=after, batch=_BATCH
        )
    ):
        outcome = await conversation_entries_migration.migrate(ref, apply=args.apply)
        actions[outcome.action] += 1
        copied += outcome.copied
        identified += outcome.identified
        if outcome.action is MigrationAction.RACED:
            print(f"  [{outcome.action}] {ref.conversation_id}: written meanwhile, re-run")
        elif outcome.action is not MigrationAction.UNCHANGED:
            print(
                f"  [{outcome.action}] {ref.conversation_id}: {outcome.copied} copied, "
                f"{outcome.rewritten} rewritten, {outcome.identified} given an id"
            )
    if actions:
        counts = ", ".join(f"{n} {a}" for a, n in sorted(actions.items()))
        print(f"Summary: {counts}; {copied} entries; {identified} elements given an id")
    else:
        print("Summary: nothing to migrate")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write.")
    return 1 if actions[MigrationAction.RACED] else 0


async def _verify_all() -> tuple[list[tuple[HeadRef, VerifyReport]], int]:
    """Verify every head still holding an array, printing each mismatch; returns the reports and failures."""
    reports: list[tuple[HeadRef, VerifyReport]] = []
    failed = 0
    async for ref in _heads(_embedded):
        report = await conversation_entries_migration.verify(ref)
        reports.append((ref, report))
        if not report.ok:
            failed += 1
            for mismatch in report.mismatches:
                print(f"  MISMATCH {ref.conversation_id}: {mismatch}")
        elif report.entries != report.embedded:
            print(
                f"  {ref.conversation_id}: {report.entries - report.embedded} entries beyond the "
                "embedded array (trimmed by the old cap, or appended since)"
            )
    print(f"Verified {len(reports)} conversations: {failed} with mismatches.")
    return reports, failed


async def _verify() -> int:
    _, failed = await _verify_all()
    return 1 if failed else 0


async def _drop(args: argparse.Namespace) -> int:
    reports, failed = await _verify_all()
    if failed:
        print("Nothing dropped: every conversation must verify first. Run --apply, then retry.")
        return 1
    if not args.apply:
        print(f"{len(reports)} embedded arrays would drop. Dry run only. Re-run with --apply.")
        return 0
    dropped = refused = 0
    for ref, report in reports:
        if report.fingerprint is not None and await conversation_entries_migration.drop_embedded(
            ref, verified=report.fingerprint
        ):
            dropped += 1
        else:
            refused += 1
            print(f"  [refused] {ref.conversation_id}: written since its verify")
    print(f"{dropped} embedded arrays dropped; {refused} refused.")
    return 1 if refused else 0


async def _run(args: argparse.Namespace) -> int:
    if args.verify:
        return await _verify()
    if args.drop_embedded:
        return await _drop(args)
    return await _migrate(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(  # pragma: no mutate — help text and its layout only
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write (otherwise dry run).",  # pragma: no mutate — help text only
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--verify",
        action="store_true",
        help="Compare entries with each embedded array.",  # pragma: no mutate — help text only
    )
    mode.add_argument(
        "--drop-embedded",
        action="store_true",
        help="Verify every conversation, then unset the arrays if all pass.",  # pragma: no mutate
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_run(_parser().parse_args(argv))))


if __name__ == "__main__":
    main()
