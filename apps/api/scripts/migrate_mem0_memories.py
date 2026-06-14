"""
One-time, idempotent migration: import mem0 memories into the GAIA memory engine.

Pages every user's memories out of the mem0 v2 API over plain HTTP (the
``mem0ai`` dependency is removed from this codebase) and feeds each fact
through ``memory_engine.retain_single``, which categorizes, deduplicates,
embeds, and files it. mem0 entries are already atomic facts, so no transcript
extraction runs — only the lightweight categorize path.

Credentials are read straight from the environment (NOT app settings, which
no longer define them):
    MEM0_API_KEY, MEM0_ORG_ID, MEM0_PROJECT_ID

Idempotent: facts whose exact content already exists for the user are skipped.

Run from repo root:
    cd apps/api && uv run python scripts/migrate_mem0_memories.py [--user-id ID] [--dry-run]
"""

import argparse
import asyncio
import os
from pathlib import Path
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx  # noqa: E402

from app.agents.llm.client import register_llm_providers  # noqa: E402
from app.constants.memory import MemorySourceType  # noqa: E402
from app.db.chroma.chromadb import init_chroma  # noqa: E402
from app.db.mongodb.collections import users_collection  # noqa: E402
from app.db.postgresql import init_postgresql_engine  # noqa: E402
from app.memory import pg_store  # noqa: E402
from app.memory.engine import memory_engine  # noqa: E402

MEM0_API_BASE = "https://api.mem0.ai"
MEM0_PAGE_SIZE = 100
RETAIN_CONCURRENCY = 5


def _mem0_credentials() -> tuple[str, dict[str, str]]:
    """Read mem0 credentials from the environment; exit if the key is missing."""
    api_key = os.environ.get("MEM0_API_KEY")
    if not api_key:
        sys.exit("MEM0_API_KEY is not set — export the old mem0 credentials to migrate.")
    params = {}
    if org_id := os.environ.get("MEM0_ORG_ID"):
        params["org_id"] = org_id
    if project_id := os.environ.get("MEM0_PROJECT_ID"):
        params["project_id"] = project_id
    return api_key, params


async def fetch_mem0_memories(
    client: httpx.AsyncClient, user_id: str, base_params: dict[str, str]
) -> list[str]:
    """Page through every mem0 memory for one user, returning fact contents."""
    contents: list[str] = []
    page = 1
    while True:
        response = await client.post(
            f"{MEM0_API_BASE}/v2/memories/",
            params={**base_params, "page": page, "page_size": MEM0_PAGE_SIZE},
            json={"filters": {"AND": [{"user_id": user_id}]}},
        )
        response.raise_for_status()
        payload = response.json()

        results = payload.get("results", payload) if isinstance(payload, dict) else payload
        if not isinstance(results, list) or not results:
            break

        contents.extend(
            content
            for item in results
            if isinstance(item, dict) and (content := item.get("memory"))
        )

        has_next = isinstance(payload, dict) and payload.get("next")
        if not has_next or len(results) < MEM0_PAGE_SIZE:
            break
        page += 1
    return contents


async def migrate_user(
    client: httpx.AsyncClient,
    user_id: str,
    base_params: dict[str, str],
    dry_run: bool,
) -> tuple[int, int]:
    """Migrate one user's mem0 memories. Returns (imported, skipped)."""
    try:
        facts = await fetch_mem0_memories(client, user_id, base_params)
    except httpx.HTTPStatusError as e:
        print(f"  ! mem0 fetch failed for {user_id}: {e.response.status_code}")
        return 0, 0

    if not facts:
        return 0, 0

    existing = {row.content for row in await pg_store.get_all_live_memories(user_id)}
    pending = [fact for fact in facts if fact not in existing]
    skipped = len(facts) - len(pending)

    if dry_run:
        print(f"  {user_id}: would import {len(pending)}, skip {skipped} (already present)")
        return len(pending), skipped

    semaphore = asyncio.Semaphore(RETAIN_CONCURRENCY)

    async def _retain(content: str) -> bool:
        async with semaphore:
            try:
                await memory_engine.retain_single(
                    user_id,
                    content,
                    category_path=None,
                    source_type=MemorySourceType.MIGRATION,
                )
                return True
            except Exception as e:
                print(f"  ! retain failed for {user_id}: {e}")
                return False

    results = await asyncio.gather(*(_retain(content) for content in pending))
    imported = sum(results)
    print(f"  {user_id}: imported {imported}/{len(pending)}, skipped {skipped}")
    return imported, skipped


async def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate mem0 memories into the memory engine.")
    parser.add_argument("--user-id", help="Migrate a single user instead of all users")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be imported without writing"
    )
    args = parser.parse_args()

    api_key, base_params = _mem0_credentials()

    # Register the lazy providers the engine needs (initialized on first use).
    init_postgresql_engine()
    init_chroma()
    register_llm_providers()

    if args.user_id:
        user_ids = [args.user_id]
    else:
        user_ids = [str(doc["_id"]) async for doc in users_collection.find({}, {"_id": 1})]
    print(
        f"Migrating mem0 memories for {len(user_ids)} user(s){' (dry run)' if args.dry_run else ''}..."
    )

    total_imported = total_skipped = 0
    async with httpx.AsyncClient(
        headers={"Authorization": f"Token {api_key}"}, timeout=60.0
    ) as client:
        for user_id in user_ids:
            imported, skipped = await migrate_user(client, user_id, base_params, args.dry_run)
            total_imported += imported
            total_skipped += skipped

    print(f"Done. Imported {total_imported}, skipped {total_skipped} duplicate(s).")


if __name__ == "__main__":
    asyncio.run(main())
