"""python -m scripts.analytics_ops <command>: PostHog e2e, reconciliation and backfills.

Every backfill is a dry run that prints its plan unless --apply is given, and
reads before it writes, so a re-run after an apply plans nothing. Reads need a
personal API key (POSTHOG_PERSONAL_API_KEY for prod, POSTHOG_E2E_PERSONAL_API_KEY
for gaia-test); writes need that project's token. Mongo is read through
ANALYTICS_MONGO_URI. Order the backfills merge-email-persons, then
backfill-paid-status, then backfill-history.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
import sys

from . import backfill_history, backfill_paid_status, e2e, merge_email_persons, reconcile
from .mongo import ground_truth_db
from .posthog_api import TARGETS, Sender, TargetName, reader

SAMPLE_SIZE = 5
MERGE_HELP = (
    "Merge email-keyed PostHog persons into their GAIA user's person. PostHog merges are "
    "IRREVERSIBLE: a merged person cannot be split again. Dry run by default; --pilot N merges "
    "the N oldest, --apply merges all. Every send first writes a JSONL snapshot of the persons."
)


def _target(args: argparse.Namespace) -> TargetName:
    target: TargetName = args.project
    return target


def cmd_reconcile(args: argparse.Namespace) -> int:
    """Print the reconciliation table; exit 1 when any row disagrees."""
    db = ground_truth_db()
    read = reader(TARGETS[_target(args)])
    window = reconcile.Window.last_days(args.days, datetime.now(UTC))
    print(f"window {window.start:%Y-%m-%d} to {window.end:%Y-%m-%d} (UTC, end exclusive)")
    rows = reconcile.reconcile(read, db, window)
    print(reconcile.render(rows))
    return 0 if all(row.matches for row in rows) else 1


def cmd_paid_status(args: argparse.Namespace) -> int:
    """Plan, and with --apply send, the paid-state person properties."""
    target = TARGETS[_target(args)]
    states = backfill_paid_status.latest_states(ground_truth_db().subscriptions.find({}))
    print(f"Mongo: {backfill_paid_status.summarize(states)}")
    read = reader(target)
    stale = backfill_paid_status.stale_states(read, states)
    print(f"PostHog differs for {backfill_paid_status.summarize(stale)}")
    print(f"sample: {[state.user_id.distinct_id for state in stale[:SAMPLE_SIZE]]}")
    if not args.apply:
        print("dry run; --apply sends one $set per differing user")
        return 0
    sender = Sender.open(target, read)
    backfill_paid_status.apply(sender, stale)
    sender.close()
    print(f"sent {len(stale)} $set")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Plan, and with --pilot or --apply perform, the email-person merges."""
    target = TARGETS[_target(args)]
    db = ground_truth_db()
    read = reader(target)
    merge_plan = merge_email_persons.plan(read, db)
    print(merge_plan.summary())
    print(f"sample person ids: {[m.person_id for m in merge_plan.merges[:SAMPLE_SIZE]]}")
    if args.pilot is None and not args.apply:
        print("dry run; --pilot N merges the N oldest, --apply merges all (IRREVERSIBLE)")
        return 0
    merges = merge_plan.merges if args.apply else merge_plan.merges[: args.pilot]
    snapshot = merge_email_persons.write_snapshot(merges, args.snapshot_dir)
    print(f"snapshot of {len(merges)} persons: {snapshot}")
    sender = Sender.open(target, read)
    restored = merge_email_persons.apply(read, sender, merges)
    sender.close()
    print(f"merged {len(merges)}; restored first-touch properties on {restored}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    """Plan, and with --apply send, the historical signups and activations."""
    target = TARGETS[_target(args)]
    db = ground_truth_db()
    read = reader(target)
    pending_merges = merge_email_persons.plan(read, db).merges
    history = backfill_history.plan(read, db)
    print(history.summary())
    for problem in history.unbuildable:
        print(f"  cannot build: {problem}")
    if not args.apply:
        print("dry run; --apply sends them at their records' own timestamps")
        return 0
    if pending_merges:
        print(
            f"{len(pending_merges)} email persons are not merged yet; run merge-email-persons "
            "first, or their existing events are invisible to this plan and get duplicated",
            file=sys.stderr,
        )
        return 1
    sender = Sender.open(target, read)
    backfill_history.apply(sender, history.signups + history.activations)
    sender.close()
    print(f"sent {len(history.signups) + len(history.activations)} historical events")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="analytics_ops", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(
        name: str, run: Callable[[argparse.Namespace], int], text: str
    ) -> argparse.ArgumentParser:
        command = sub.add_parser(name, help=text, description=text)
        command.add_argument(
            "--project",
            type=TargetName,
            choices=list(TargetName),
            default=TargetName.PROD,
            help="which PostHog project to read and write (default prod)",
        )
        command.set_defaults(run=run)
        return command

    rec = add("reconcile", cmd_reconcile, "PostHog against Mongo for every dashboard signal.")
    rec.add_argument(
        "--days",
        type=int,
        choices=range(1, reconcile.MAX_WINDOW_DAYS + 1),
        default=reconcile.MAX_WINDOW_DAYS,
        metavar=f"1..{reconcile.MAX_WINDOW_DAYS}",
        help="whole UTC days up to today (at most 29: processed_webhooks keeps 30)",
    )
    paid = add("backfill-paid-status", cmd_paid_status, backfill_paid_status.__doc__ or "")
    paid.add_argument("--apply", action="store_true", help="send the $set calls")
    merge = add("merge-email-persons", cmd_merge, MERGE_HELP)
    mode = merge.add_mutually_exclusive_group()
    mode.add_argument("--pilot", type=int, metavar="N", help="merge only the N oldest persons")
    mode.add_argument("--apply", action="store_true", help="merge every matched person")
    merge.add_argument(
        "--snapshot-dir",
        type=Path,
        default=merge_email_persons.DEFAULT_SNAPSHOT_DIR,
        help="where the pre-merge JSONL snapshot is written",
    )
    history = add("backfill-history", cmd_history, backfill_history.__doc__ or "")
    history.add_argument("--apply", action="store_true", help="send the historical events")
    e2e.add_parser(sub)
    return parser


def main() -> int:
    """Run the chosen command."""
    args = _parser().parse_args()
    run: Callable[[argparse.Namespace], int] = args.run
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
