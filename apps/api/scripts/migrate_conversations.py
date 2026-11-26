#!/usr/bin/env python3
"""Bring every conversation into the shape this build reads, before it boots; exit 1 on any failure.

Runs each one-time migration only while its data is still in the old shape, then that
migration's verify: the entries migration while the boot check names it (an array the log does
not match, a message-shaped entry, a head with no source, or a recorded failed pass or verify),
migrating and verifying only the conversations it names, then the approval vocabulary while any
old value is left. It ends with the boot check itself, so it exits 0 exactly when the build will
boot. With nothing to do it is the boot check's reads, so it runs on every start, and after a
full pass it is the cutover's catch-up. Run it with the old build stopped: the self-host compose
runs it as gaia-migrate, which the API and the worker wait on.

Usage::

    cd apps/api
    uv run python -m scripts.migrate_conversations [--check]
"""

from __future__ import annotations

import argparse
import asyncio

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.settings import settings
from app.constants.chat import CONVERSATION_ENTRIES_MIGRATION_SCRIPT
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME, MongoDB
from app.db.repositories.conversation_migration_guard import first_refusal
from scripts import migrate_approval_vocabulary as vocabulary
from scripts.migrate_conversation_entries import __main__ as entries
from scripts.migrate_conversation_entries.contract import contract as drop_embedded_arrays

#: The exit status of --check while a catch-up has work to do; deploy.sh migrate reads the same value.
CATCH_UP_NEEDED_EXIT = 3


async def pending_catch_up(db: AsyncIOMotorDatabase) -> str | None:
    """Name what a catch-up run would still rewrite in db, or None when it has nothing to do; reads only."""
    if refusal := await first_refusal():
        return refusal.error().message
    if left := (await vocabulary.verify(db)).left:
        return f"{left} stored approval values in the old vocabulary"
    return None


async def migrate_conversations(db: AsyncIOMotorDatabase) -> int:
    """Run the entries migration, then the vocabulary rewrite in db, each only when needed and verified; 0 only when the build will boot."""
    failed = 0
    refusal = await first_refusal()
    caught_up = refusal is not None and refusal.script == CONVERSATION_ENTRIES_MIGRATION_SCRIPT
    if caught_up:
        print("Moving conversations into the conversation log...")
        failed = await entries.catch_up()
    if not failed and (await vocabulary.verify(db)).left:
        print("Rewriting stored approvals...")
        await vocabulary.rewrite_all(db, apply=True)
        failed = await vocabulary.verify_all(db)
    if refusal := await first_refusal():
        print(f"The build will refuse to boot: {refusal.error().message}")
        return 1
    if failed:
        return failed
    if caught_up:
        # The release step's contract ran before this catch-up, so it kept the arrays just migrated.
        await drop_embedded_arrays(apply=True)
    print("Every conversation is in this build's shape.")
    return 0


async def check(db: AsyncIOMotorDatabase) -> int:
    """Report whether a catch-up run has work to do, writing nothing: CATCH_UP_NEEDED_EXIT when it has."""
    if pending := await pending_catch_up(db):
        print(f"A catch-up is needed: {pending}")
        return CATCH_UP_NEEDED_EXIT
    print("Every conversation is in this build's shape.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="write nothing; say whether a catch-up is needed"
    )
    args = parser.parse_args()
    database = MongoDB(settings.MONGO_DB, MONGO_DATABASE_NAME).database
    return asyncio.run(check(database) if args.check else migrate_conversations(database))


if __name__ == "__main__":
    raise SystemExit(main())
