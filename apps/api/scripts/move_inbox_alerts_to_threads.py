#!/usr/bin/env python3
"""One-time migration: new mail stops waking the Inbox desk; its thread todos alert instead.

Every desk opened before this change holds the system watch GAIA installed: any
person's new mail in the Primary inbox woke it, at most once an hour, and its
thread todos stayed silent, reporting only through the desk. Now the desk runs only
on its schedule and each thread todo tells the user what cannot wait. For every
open desk this:

1. removes exactly that watch, through unregister_subscription so the shared Composio
   trigger is released when nothing else uses it. A watch the user asked the desk for
   has other conditions and is left alone;
2. turns delivery on for each of its open thread todos that was still silent, the way
   a thread todo opened under the desk now starts, and records it in the todo's activity.

Run from the api directory (or /app inside the container):

    python scripts/move_inbox_alerts_to_threads.py --dry-run
    python scripts/move_inbox_alerts_to_threads.py --execute

Flags:
--dry-run  Report what would change. Default.
--execute  Make the changes. Required to write anything.

Safely re-runnable: a desk without the watch and a thread todo that already delivers no
longer match.
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.todos import INBOX_DESK_AUTOMATED_SENDERS
from app.constants.triggers import GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.db.repositories.todos import todo_repository
from app.models.todo_models import ExternalRefSource, TodoDocument, TodoUpdate
from app.models.trigger_subscription_models import (
    ConditionOperator,
    SubscriptionCondition,
    TriggerSubscription,
)
from app.services.todo_activity import record_field_changes
from app.services.triggers.subscription_service import unregister_subscription

# The watch as provisioning installed it, condition for condition.
LEGACY_DESK_WATCH_CONDITIONS = frozenset(
    (
        *(
            SubscriptionCondition(
                field_name="label_ids", operator=ConditionOperator.CONTAINS, value=label
            )
            for label in ("INBOX", "CATEGORY_PERSONAL")
        ),
        *(
            SubscriptionCondition(
                field_name="sender", operator=ConditionOperator.NOT_CONTAINS, value=sender
            )
            for sender in INBOX_DESK_AUTOMATED_SENDERS
        ),
    )
)

SPEAKING_THREAD = TodoUpdate(notify_on_run=True)
_MIGRATED_BY = "GAIA, moving inbox alerts from the desk to its thread todos"


@dataclass
class MigrationResult:
    dry_run: bool
    #: desk id -> the legacy watches it still holds.
    watched: dict[str, list[TriggerSubscription]]
    #: The desks' open thread todos that are still silent.
    silent_threads: list[TodoDocument]
    watches_removed: int = 0
    threads_speaking: int = 0
    #: todo id -> the error that stopped it; a re-run retries anything still unchanged.
    failures: dict[str, str] = field(default_factory=dict)


def legacy_watches(desk: TodoDocument) -> list[TriggerSubscription]:
    """Return the desk's system mail watches; any other watch is the user's and stays."""
    return [
        sub
        for sub in desk.trigger_subscriptions
        if sub.trigger_name == GMAIL_NEW_MESSAGE_TRIGGER_NAME
        and frozenset(sub.conditions) == LEGACY_DESK_WATCH_CONDITIONS
    ]


async def run_migration(*, dry_run: bool) -> MigrationResult:
    desks = await todo_repository.list_open_by_external_ref_source(ExternalRefSource.INBOX_DESK)
    threads = await todo_repository.list_open_by_external_ref_source(ExternalRefSource.GMAIL_THREAD)
    desk_ids = {desk.id for desk in desks}
    result = MigrationResult(
        dry_run=dry_run,
        watched={desk.id: subs for desk in desks if (subs := legacy_watches(desk))},
        silent_threads=[t for t in threads if t.parent_todo_id in desk_ids and not t.notify_on_run],
    )
    if dry_run:
        return result

    owners = {desk.id: desk.user_id for desk in desks}
    for desk_id, subscriptions in result.watched.items():
        for subscription in subscriptions:
            # One todo's failure must not end the run for every todo behind it; it is
            # reported, and a re-run retries whatever is still unchanged.
            try:
                await unregister_subscription(desk_id, owners[desk_id], subscription.id)
            except Exception as e:
                result.failures[desk_id] = f"{type(e).__name__}: {e}"
                break
            result.watches_removed += 1
    for thread in result.silent_threads:
        try:
            await _let_speak(thread)
        except Exception as e:
            result.failures[thread.id] = f"{type(e).__name__}: {e}"
            continue
        result.threads_speaking += 1
    return result


async def _let_speak(thread: TodoDocument) -> None:
    if (
        await todo_repository.update(thread.id, user_id=thread.user_id, update=SPEAKING_THREAD)
        is None
    ):
        raise LookupError(f"Thread todo {thread.id} vanished before its delivery was turned on")
    await record_field_changes(thread.id, thread.user_id, SPEAKING_THREAD, by=_MIGRATED_BY)


def _render(result: MigrationResult) -> None:
    mode = "DRY RUN — nothing was written" if result.dry_run else "EXECUTED"
    print(f"\n{mode}")
    print(f"desks still woken by new mail:   {len(result.watched)}")
    print(f"silent thread todos under desks: {len(result.silent_threads)}")
    if not result.dry_run:
        print(f"watches removed:                 {result.watches_removed}")
        print(f"thread todos now delivering:     {result.threads_speaking}")
        if result.failures:
            print(f"failed (re-run retries):         {len(result.failures)}")
            for todo_id, error in result.failures.items():
                print(f"  {todo_id}: {error}")
    if not result.watched and not result.silent_threads:
        print("\nNothing to do.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mutually exclusive so an ambiguous invocation fails loud instead of guessing.
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="make the changes")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    args = parser.parse_args()

    result = await run_migration(dry_run=not args.execute)
    _render(result)

    if not args.execute:
        print("\nRe-run with --execute to make these changes.")


if __name__ == "__main__":
    asyncio.run(main())
