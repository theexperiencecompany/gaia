#!/usr/bin/env python3
"""Seed a local dev user with a founder's real memories + todos for E2E verification.

Input: a JSON file produced on prod (see openspec change daily-briefing-self-
executing-todos, tasks 7.0) of the shape:

    {"memories": ["...content...", ...], "todos": [{...todo doc sans _id...}, ...]}

Memories are REPLAYED through the local memory engine (retain_single), so
embeddings and graph state are regenerated locally — no cross-environment
vector copying. Todos are inserted with the target user_id.

Run: uv run python -m scripts.seed_founder_e2e <target_user_id> <dump.json>
"""

import asyncio
from pathlib import Path
import sys

from bson import json_util

from app.constants.memory import MemorySourceType
from app.core.provider_registration import unified_startup
from app.db.mongodb.collections import get_async_collection
from app.memory.engine import memory_engine

todos_collection = get_async_collection("todos")


async def seed(user_id: str, dump_path: str) -> None:
    await unified_startup("arq_worker")
    dump_file = await asyncio.to_thread(Path(dump_path).resolve)
    if dump_file.suffix != ".json" or not await asyncio.to_thread(dump_file.is_file):
        raise SystemExit(f"dump must be an existing .json file, got: {dump_file}")
    data = json_util.loads(await asyncio.to_thread(dump_file.read_text))
    memories: list[str] = data.get("memories", [])
    todos: list[dict] = data.get("todos", [])

    for i, content in enumerate(memories, 1):
        await memory_engine.retain_single(user_id, content, source_type=MemorySourceType.MANUAL)
        print(f"memory {i}/{len(memories)} retained")

    for doc in todos:
        doc.pop("_id", None)
        doc["user_id"] = user_id
        await todos_collection.insert_one(doc)
    print(f"seeded {len(memories)} memories, {len(todos)} todos for {user_id}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    asyncio.run(seed(sys.argv[1], sys.argv[2]))
