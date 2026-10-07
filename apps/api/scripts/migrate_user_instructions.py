"""Idempotent migration: move both legacy instruction stores into user_instructions.

users.onboarding.preferences.custom_instructions becomes the "global" scope, and every
integration_instructions document becomes the scope named by its integration_id. A
scope that already exists in user_instructions is left alone, so re-running never
overwrites an edit made after the first run. With --apply the legacy field is unset
and the legacy collection dropped once every row has been copied.

Run right after deploying the code that reads user_instructions: until then the agent
and the settings page see no instructions.

    cd apps/api && uv run python scripts/migrate_user_instructions.py [--apply]
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from pymongo.errors import DuplicateKeyError

from app.db.mongodb.collections import get_async_collection
from app.db.mongodb.indexes import create_user_instructions_indexes
from app.models.user_instructions_models import GLOBAL_INSTRUCTIONS_SCOPE, InstructionsEditor

users_collection = get_async_collection("users")
legacy_collection = get_async_collection("integration_instructions")
target_collection = get_async_collection("user_instructions")

LEGACY_GLOBAL_FIELD = "onboarding.preferences.custom_instructions"


async def _copy(user_id: str, scope: str, content: str, updated_by: str, apply: bool) -> bool:
    """Insert one scope at revision 1; False when that scope already exists."""
    if not apply:
        exists = await target_collection.count_documents({"user_id": user_id, "scope": scope})
        return exists == 0
    try:
        await target_collection.insert_one(
            {
                "user_id": user_id,
                "scope": scope,
                "content": content,
                "revision": 1,
                "updated_by": updated_by,
                "updated_at": datetime.now(UTC),
            }
        )
    except DuplicateKeyError:
        return False
    return True


async def migrate(apply: bool) -> None:
    if apply:
        # The unique (user_id, scope) index is what makes a re-run skip instead of duplicate.
        await create_user_instructions_indexes()
    counts = {
        "global_copied": 0,
        "global_skipped": 0,
        "integration_copied": 0,
        "integration_skipped": 0,
    }

    async for user in users_collection.find(
        {LEGACY_GLOBAL_FIELD: {"$nin": [None, ""]}},
        {"_id": 1, LEGACY_GLOBAL_FIELD: 1},
    ):
        content = user["onboarding"]["preferences"]["custom_instructions"].strip()
        if not content:
            continue
        copied = await _copy(
            str(user["_id"]), GLOBAL_INSTRUCTIONS_SCOPE, content, InstructionsEditor.USER, apply
        )
        counts["global_copied" if copied else "global_skipped"] += 1

    async for doc in legacy_collection.find({"content": {"$nin": [None, ""]}}):
        copied = await _copy(
            doc["user_id"],
            doc["integration_id"],
            doc["content"],
            doc.get("updated_by") or InstructionsEditor.USER,
            apply,
        )
        counts["integration_copied" if copied else "integration_skipped"] += 1

    print(f"{'Applied' if apply else 'Dry run'}: {counts}")
    if not apply:
        print("Re-run with --apply to write.")
        return

    unset = await users_collection.update_many(
        {LEGACY_GLOBAL_FIELD: {"$exists": True}}, {"$unset": {LEGACY_GLOBAL_FIELD: ""}}
    )
    await legacy_collection.drop()
    print(
        f"Unset the legacy field on {unset.modified_count} users; dropped integration_instructions."
    )


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
