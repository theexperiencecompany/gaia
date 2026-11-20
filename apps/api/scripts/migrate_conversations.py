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
    uv run python -m scripts.migrate_conversations
"""

from __future__ import annotations

import asyncio

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.settings import settings
from app.constants.chat import CONVERSATION_ENTRIES_MIGRATION_SCRIPT
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME, MongoDB
from app.db.repositories.conversation_migration_guard import first_refusal
from scripts import migrate_approval_vocabulary as vocabulary
from scripts.migrate_conversation_entries import __main__ as entries


async def migrate_conversations(db: AsyncIOMotorDatabase) -> int:
    """Run the entries migration, then the vocabulary rewrite in db, each only when needed and verified; 0 only when the build will boot."""
    failed = 0
    refusal = await first_refusal()
    if refusal is not None and refusal.script == CONVERSATION_ENTRIES_MIGRATION_SCRIPT:
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
    print("Every conversation is in this build's shape.")
    return 0


if __name__ == "__main__":
    database = MongoDB(settings.MONGO_DB, MONGO_DATABASE_NAME).database
    raise SystemExit(asyncio.run(migrate_conversations(database)))
