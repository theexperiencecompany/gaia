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
is reported REFUSED with why, and one whose pass crashed FAILED with the error; the run goes
on to the next, and the boot check refuses both until a later pass migrates them. All three
make the run exit 1. A head too full to take the log pointer beside its array (Mongo's 16 MB
limit) has the array moved to conversation_archived_messages in the same write; verify reads
it there. Every head with no source is given
one (a todo's chat background, a workflow's workflow_system, any other web), and --verify
fails while any head still has none.

Cutover, in this order:
  1. --apply, then --verify, while the old build serves; repeat until both exit 0.
  2. Stop the old build, so nothing writes an embedded array.
  3. python -m scripts.migrate_conversations: it migrates, then verifies, only the heads the
     old build wrote since their pass (and any recorded failure), then runs the boot check.
  4. Deploy the new build. It refuses to boot while any conversation has an embedded array
     the log does not match, message-shaped entries, a head with no source, or a failed pass
     or verify.

A pass copies and never deletes. The release step's contract (contract.py) then drops every
array the log matches; rollback is restoring the pre-deploy Atlas snapshot.

Usage::

    cd apps/api
    uv run python -m scripts.migrate_conversation_entries               # dry run
    uv run python -m scripts.migrate_conversation_entries --apply
    uv run python -m scripts.migrate_conversation_entries --verify
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass

from scripts.migrate_conversation_entries.migration import (
    NOT_KEPT_FIELDS,
    HeadRef,
    MigrationAction,
    MigrationOutcome,
    VerifyReport,
    conversation_entries_migration,
)
from scripts.migrate_conversation_entries.sources import conversation_source_backfill

_BATCH = 200
_Scan = Callable[[str | None], Awaitable[list[HeadRef]]]
_FAILED = (MigrationAction.RACED, MigrationAction.REFUSED, MigrationAction.FAILED)
#: Outcomes the boot check refuses until a later pass migrates the conversation; RACED only needs a re-run.
_RECORDED = (MigrationAction.REFUSED, MigrationAction.FAILED)
#: A mismatch can quote whole messages: the record keeps its start, the run's output keeps all of it.
_RECORDED_MISMATCH_CHARS = 500


@dataclass
class _Totals:
    written: int = 0
    rewritten: int = 0
    identified: int = 0
    folded: int = 0
    not_kept: int = 0


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


def _crash(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


async def migrate_one(ref: HeadRef, *, apply: bool) -> MigrationOutcome:
    """Migrate one conversation, a crash reported as its own failure; an applied pass records it for the boot check."""
    migration = conversation_entries_migration
    try:
        outcome = await migration.migrate(ref, apply=apply)
    except Exception as exc:  # one conversation's crash must not stop the others
        outcome = MigrationOutcome(ref.conversation_id, MigrationAction.FAILED, reason=_crash(exc))
    if apply and outcome.action in _RECORDED:
        await migration.mark_failed(ref, outcome.reason)
    elif apply and outcome.action is not MigrationAction.RACED:
        await migration.clear_failed(ref)
    return outcome


async def _walk(*, every_embedded: bool) -> AsyncIterator[HeadRef]:
    """Walk both sources' heads: every embedded array, or only the ones the log lags."""
    for scan in _scans(every_embedded=every_embedded):
        async for ref in _heads(scan):
            yield ref


async def _listed(refs: Iterable[HeadRef]) -> AsyncIterator[HeadRef]:
    for ref in refs:
        yield ref


async def migrate_all(*, apply: bool) -> int:
    """Migrate every head the log lags; 1 while any conversation raced or was refused."""
    return await _migrate(_walk(every_embedded=False), apply=apply)


async def _migrate(refs: AsyncIterator[HeadRef], *, apply: bool) -> int:
    """Migrate each head, then give every sourceless head its source; 1 while any raced or was refused."""
    actions: Counter[MigrationAction] = Counter()
    totals = _Totals()
    async for ref in refs:
        outcome = await migrate_one(ref, apply=apply)
        actions[outcome.action] += 1
        totals.written += outcome.written
        totals.rewritten += outcome.rewritten
        totals.identified += outcome.identified
        totals.folded += outcome.folded
        totals.not_kept += outcome.not_kept
        if outcome.action in _FAILED:
            print(f"  [{outcome.action}] {ref.conversation_id}: {outcome.reason or 're-run'}")
        elif outcome.action is not MigrationAction.UNCHANGED:
            moved = "; array moved to the archive" if outcome.relocated else ""
            print(
                f"  [{outcome.action}] {ref.conversation_id}: {outcome.written} written, "
                f"{outcome.rewritten} rewritten, {outcome.identified} given an id{moved}"
            )
    counts = ", ".join(f"{n} {a}" for a, n in sorted(actions.items())) or "nothing to migrate"
    print(
        f"Summary: {counts}; {totals.written} entries written, {totals.rewritten} "
        f"rewritten; {totals.identified} messages given an id; {totals.folded} "
        "emoji_ack messages folded into reactions."
    )
    if totals.not_kept:
        print(
            f"  {totals.not_kept} messages carry fields the log does not keep "
            f"({', '.join(NOT_KEPT_FIELDS)})."
        )
    given = await conversation_source_backfill.backfill(apply=apply)
    print(
        "Sources: "
        + ", ".join(f"{count} given {source.value}" for source, count in given.items())
        + "."
    )
    if not apply:
        print("Dry run only. Re-run with --apply to write.")
    return 1 if any(actions[action] for action in _FAILED) else 0


async def verify_one(ref: HeadRef) -> VerifyReport:
    """Verify one conversation, a crash reported as its mismatch; a mismatch is recorded for the boot check."""
    migration = conversation_entries_migration
    try:
        report = await migration.verify(ref)
    except Exception as exc:  # one conversation's crash must not stop the others
        report = VerifyReport(ref.conversation_id, mismatches=[f"crashed: {_crash(exc)}"])
    if report.ok:
        await migration.clear_failed(ref)
    else:
        first = report.mismatches[0][:_RECORDED_MISMATCH_CHARS]
        await migration.mark_failed(
            ref, f"verify: {len(report.mismatches)} mismatches, first {first}"
        )
    return report


async def verify_all() -> int:
    """Verify every head with an embedded array or message entries, printing and recording each mismatch."""
    return await _verify(_walk(every_embedded=True))


async def catch_up() -> int:
    """Migrate, then verify, only what the boot check refuses: heads written since their pass, message-shaped entries and recorded failures."""
    refused = {ref.head_id: ref async for ref in _walk(every_embedded=False)}
    refused.update(
        (ref.head_id, ref) for ref in await conversation_entries_migration.failed_heads()
    )
    heads = sorted(refused.values(), key=lambda ref: ref.head_id)
    return await _migrate(_listed(heads), apply=True) or await _verify(_listed(heads))


async def _verify(refs: AsyncIterator[HeadRef]) -> int:
    """Verify each head, printing and recording each mismatch; 1 while any mismatched or a head has no source."""
    verified = failed = 0
    async for ref in refs:
        report = await verify_one(ref)
        verified += 1
        if not report.ok:
            failed += 1
            for mismatch in report.mismatches:
                print(f"  MISMATCH {ref.conversation_id}: {mismatch}")
    print(f"Verified {verified} conversations: {failed} with mismatches.")
    sourceless = await conversation_source_backfill.count_sourceless()
    print(f"{sourceless} conversations have no source.")
    return 1 if failed or sourceless else 0


async def _run(args: argparse.Namespace) -> int:
    if args.verify:
        return await verify_all()
    return await migrate_all(apply=args.apply)


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
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Check what clients read back against each old array.",  # pragma: no mutate — help text only
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_run(_parser().parse_args(argv))))


if __name__ == "__main__":
    main()
