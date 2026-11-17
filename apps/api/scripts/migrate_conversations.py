#!/usr/bin/env python3
"""Bring every conversation into the shape this build reads, before it boots; exit 1 on any failure.

Runs each one-time migration only while its data is still in the old shape, then that
migration's verify: the entries migration while the boot check finds an unmarked array, a
message-shaped entry or a head with no source, then the approval vocabulary while any old
value is left. With nothing to do it is a few indexed reads, so it runs on every start.
Run it with the old build stopped: the self-host compose runs it as gaia-migrate, which the
API and the worker wait on.

Usage::

    cd apps/api
    uv run python -m scripts.migrate_conversations
"""

from __future__ import annotations

import asyncio

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.settings import settings
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME, MongoDB
from app.db.repositories.conversation_migration_guard import ConversationMigrationGuard
from scripts import migrate_approval_vocabulary as vocabulary
from scripts.migrate_conversation_entries import __main__ as entries


async def migrate_conversations(db: AsyncIOMotorDatabase) -> int:
    """Run the entries migration, then the vocabulary rewrite in db, each only when needed and each verified."""
    guard = ConversationMigrationGuard()
    if await guard.first_unmigrated() or await guard.first_sourceless():
        print("Moving conversations into the conversation log...")
        if failed := await entries.migrate_all(apply=True):
            return failed
        if failed := await entries.verify_all():
            return failed
    if (await vocabulary.verify(db)).left:
        print("Rewriting stored approvals...")
        await vocabulary.rewrite_all(db, apply=True)
        if failed := await vocabulary.verify_all(db):
            return failed
    print("Every conversation is in this build's shape.")
    return 0


if __name__ == "__main__":
    database = MongoDB(settings.MONGO_DB, MONGO_DATABASE_NAME).database
    raise SystemExit(asyncio.run(migrate_conversations(database)))
