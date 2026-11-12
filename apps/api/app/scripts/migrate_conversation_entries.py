#!/usr/bin/env python3
"""Move every conversation's embedded messages array into conversation_entries.

Element i becomes the entry at seq i+1; the array stays in place until
--drop-embedded. Safe to re-run: a migrated conversation the old build has not
written since is left alone, and one it has written is merged by message id.
emoji_ack messages are copied as ordinary entries (a later change folds them).

Usage::

    cd apps/api
    uv run python -m app.scripts.migrate_conversation_entries               # dry run
    uv run python -m app.scripts.migrate_conversation_entries --apply       # first pass
    uv run python -m app.scripts.migrate_conversation_entries --apply --since 2026-11-12T10:00:00+00:00
    uv run python -m app.scripts.migrate_conversation_entries --verify
    uv run python -m app.scripts.migrate_conversation_entries --drop-embedded --apply
    uv run python -m app.scripts.migrate_conversation_entries --rebuild-embedded --apply  # rollback
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime

from app.db.repositories.conversation_entries_migration import (
    HeadRef,
    MigrationAction,
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
        print(f"... {seen} conversations scanned (resume after _id {after})", flush=True)


async def _migrate(args: argparse.Namespace) -> int:
    actions: Counter[MigrationAction] = Counter()
    copied = 0
    async for ref in _heads(
        lambda after: conversation_entries_migration.heads_with_embedded(
            after_head_id=after, since=args.since, batch=_BATCH
        )
    ):
        outcome = await conversation_entries_migration.migrate(ref, apply=args.apply)
        actions[outcome.action] += 1
        copied += outcome.copied
        if outcome.action in {MigrationAction.REFUSED, MigrationAction.RACED}:
            print(f"  [{outcome.action}] {ref.conversation_id} {outcome.reason}")
        elif outcome.action is not MigrationAction.UNCHANGED:
            print(
                f"  [{outcome.action}] {ref.conversation_id}: "
                f"{outcome.copied} copied, {outcome.rewritten} rewritten"
            )
    print(
        "Summary: "
        + ", ".join(f"{n} {a}" for a, n in sorted(actions.items()))
        + f"; {copied} entries"
    )
    if not args.apply:
        print("Dry run only. Re-run with --apply to write.")
    return 1 if actions[MigrationAction.REFUSED] or actions[MigrationAction.RACED] else 0


async def _verify() -> int:
    checked = failed = 0
    async for ref in _heads(
        lambda after: conversation_entries_migration.heads_with_embedded(
            after_head_id=after, since=None, batch=_BATCH
        )
    ):
        report = await conversation_entries_migration.verify(ref)
        checked += 1
        if not report.ok:
            failed += 1
            for mismatch in report.mismatches:
                print(f"  MISMATCH {ref.conversation_id}: {mismatch}")
        elif report.entries != report.embedded:
            print(
                f"  {ref.conversation_id}: {report.entries - report.embedded} entries beyond the "
                "embedded array (trimmed by the old cap, or appended since)"
            )
    print(f"Verified {checked} conversations: {failed} with mismatches.")
    return 1 if failed else 0


async def _drop(args: argparse.Namespace) -> int:
    dropped = refused = 0
    async for ref in _heads(
        lambda after: conversation_entries_migration.heads_with_embedded(
            after_head_id=after, since=None, batch=_BATCH
        )
    ):
        if not args.apply:
            report = await conversation_entries_migration.verify(ref)
            refused += not report.ok
            dropped += report.ok
        elif await conversation_entries_migration.drop_embedded(ref):
            dropped += 1
        else:
            refused += 1
            print(f"  [refused] {ref.conversation_id}: --verify does not pass")
    verb = "dropped" if args.apply else "would drop"
    print(f"{dropped} embedded arrays {verb}; {refused} refused.")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write.")
    return 1 if refused else 0


async def _rebuild(args: argparse.Namespace) -> int:
    rebuilt = messages = 0
    async for ref in _heads(
        lambda after: conversation_entries_migration.heads_without_embedded(
            after_head_id=after, batch=_BATCH
        )
    ):
        messages += await conversation_entries_migration.rebuild_embedded(ref, apply=args.apply)
        rebuilt += 1
    verb = "rebuilt" if args.apply else "would rebuild"
    print(f"{rebuilt} embedded arrays {verb} from {messages} entries.")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write.")
    return 0


async def _run(args: argparse.Namespace) -> int:
    if args.verify:
        return await _verify()
    if args.drop_embedded:
        return await _drop(args)
    if args.rebuild_embedded:
        return await _rebuild(args)
    return await _migrate(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write (otherwise dry run).")
    parser.add_argument(
        "--since",
        type=datetime.fromisoformat,
        help="Second pass: only conversations whose updatedAt is at or after this ISO datetime.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--verify", action="store_true", help="Compare entries with each embedded array."
    )
    mode.add_argument(
        "--drop-embedded",
        action="store_true",
        help="Unset each embedded array that --verify passes.",
    )
    mode.add_argument(
        "--rebuild-embedded",
        action="store_true",
        help="Rollback: rebuild embedded arrays from entries.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_run(_parser().parse_args(argv))))


if __name__ == "__main__":
    main()
