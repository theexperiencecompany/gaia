#!/usr/bin/env python3
"""Rewrite every conversation's old message shape as conversation log entries.

Sources: each head's embedded messages array, and message-shaped entries an earlier build
of this stack copied into conversation_entries. A user message becomes a UserMessage and a
bot message a Reply at its position, with the bot message's ReplySettled appended at the
tail; an emoji_ack folds into a reaction on its message. An element with no message_id, or
one repeating an earlier element's, first gets a fresh id written back into the array. Safe
to re-run: a pass visits only conversations whose array changed since (any append, trim or
in-place edit) and sets only the fields whose source changed. A head written meanwhile is
reported RACED and changes nothing; re-run until 0 raced. A conversation the log cannot hold
is reported REFUSED with why. Both make the run exit 1.

Cutover, in this order:
  1. --apply while the old build serves; repeat until it reports 0 raced and 0 refused.
  2. Stop the old build, so nothing writes an embedded array.
  3. --apply again, then --verify; both must exit 0.
  4. Deploy the new build. It refuses to boot while any conversation has an embedded array
     no pass marked, or message-shaped entries.
  5. Later, --drop-embedded --apply: it verifies every conversation first and drops nothing
     unless all pass, then unsets each array only while it is exactly the one verified.

Rollback before step 5: redeploy the old build; the arrays are untouched. After step 5
there is no rollback but a database restore.

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
    NOT_KEPT_FIELDS,
    HeadRef,
    MigrationAction,
    VerifyReport,
    conversation_entries_migration,
)

_BATCH = 200
_Scan = Callable[[str | None], Awaitable[list[HeadRef]]]
_FAILED = (MigrationAction.RACED, MigrationAction.REFUSED)


async def _heads(scan: _Scan) -> AsyncIterator[HeadRef]:
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


def _scans(*, every_embedded: bool) -> tuple[_Scan, _Scan]:
    """Return the two sources' scans: embedded arrays (all, or the ones the log lags) and message entries."""
    migration = conversation_entries_migration
    embedded = migration.heads_with_embedded if every_embedded else migration.heads_to_migrate
    return (
        lambda after: embedded(after_head_id=after, batch=_BATCH),
        lambda after: migration.heads_with_message_entries(after_head_id=after, batch=_BATCH),
    )


async def _migrate(args: argparse.Namespace) -> int:
    actions: Counter[MigrationAction] = Counter()
    totals: Counter[str] = Counter()
    for scan in _scans(every_embedded=False):
        async for ref in _heads(scan):
            outcome = await conversation_entries_migration.migrate(ref, apply=args.apply)
            actions[outcome.action] += 1
            totals.update(
                written=outcome.written,
                rewritten=outcome.rewritten,
                identified=outcome.identified,
                folded=outcome.folded,
                not_kept=outcome.not_kept,
            )
            if outcome.action in _FAILED:
                print(f"  [{outcome.action}] {ref.conversation_id}: {outcome.reason or 're-run'}")
            elif outcome.action is not MigrationAction.UNCHANGED:
                print(
                    f"  [{outcome.action}] {ref.conversation_id}: {outcome.written} written, "
                    f"{outcome.rewritten} rewritten, {outcome.identified} given an id"
                )
    counts = ", ".join(f"{n} {a}" for a, n in sorted(actions.items())) or "nothing to migrate"
    print(
        f"Summary: {counts}; {totals['written']} entries written, {totals['rewritten']} "
        f"rewritten; {totals['identified']} messages given an id; {totals['folded']} "
        "emoji_ack messages folded into reactions."
    )
    if totals["not_kept"]:
        print(
            f"  {totals['not_kept']} messages carry fields the log does not keep "
            f"({', '.join(NOT_KEPT_FIELDS)})."
        )
    if not args.apply:
        print("Dry run only. Re-run with --apply to write.")
    return 1 if any(actions[action] for action in _FAILED) else 0


async def _verify_all() -> tuple[list[tuple[HeadRef, VerifyReport]], int]:
    """Verify every head with an embedded array or message entries, printing each mismatch."""
    reports: list[tuple[HeadRef, VerifyReport]] = []
    failed = 0
    for scan in _scans(every_embedded=True):
        async for ref in _heads(scan):
            report = await conversation_entries_migration.verify(ref)
            reports.append((ref, report))
            if not report.ok:
                failed += 1
                for mismatch in report.mismatches:
                    print(f"  MISMATCH {ref.conversation_id}: {mismatch}")
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
    droppable = [(ref, report.fingerprint) for ref, report in reports if report.fingerprint]
    if not args.apply:
        print(f"{len(droppable)} embedded arrays would drop. Dry run only. Re-run with --apply.")
        return 0
    dropped = refused = 0
    for ref, fingerprint in droppable:
        if await conversation_entries_migration.drop_embedded(ref, verified=fingerprint):
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
    parser = argparse.ArgumentParser(
        description=__doc__,  # pragma: no mutate — help text only
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
        help="Check what clients read back against each old array.",  # pragma: no mutate — help text only
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
