#!/usr/bin/env python3
"""
Sync explore/use-case workflows from production into the local database.

The use-cases pages read GET /api/v1/workflows/explore, which serves every
document in the `workflows` collection with ``is_explore: True``. This script
pulls the ACTUAL explore workflows from the production API
(https://api.heygaia.io) and writes them into the local MongoDB so local dev
shows exactly the same use cases as prod.

Usage:
  cd apps/api
  uv run python scripts/sync_explore_workflows_from_prod.py              # upsert prod workflows
  uv run python scripts/sync_explore_workflows_from_prod.py --prune      # also delete local explore docs missing from prod
  uv run python scripts/sync_explore_workflows_from_prod.py --dry-run    # report only, no writes
"""

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

import httpx

# Add the backend directory to Python path so we can import from app
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.db.mongodb.collections import get_async_collection  # noqa: E402
from app.models.workflow_models import TriggerConfig, TriggerType  # noqa: E402

PROD_EXPLORE_URL = "https://api.heygaia.io/api/v1/workflows/explore"
PAGE_SIZE = 50
SYSTEM_USER = "system"

workflows_collection = get_async_collection("workflows")


def build_document(w: dict[str, Any]) -> dict[str, Any]:
    """Shape one production explore workflow into a local DB document.

    Mirrors seed_explore_workflows.create_workflow_document so the documents
    are indistinguishable from the curated seed's, but keeps the production
    id/slug so identity and URLs match prod exactly.
    """
    workflow_id = w["id"]
    now = datetime.now(UTC)
    created_at = w.get("created_at") or now.isoformat()
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    steps = [
        {
            "id": step.get("id") or f"step_{i + 1}",
            "title": step["title"],
            "description": step.get("description", ""),
            "category": step.get("category", "general"),
        }
        for i, step in enumerate(w.get("steps", []))
    ]
    return {
        "_id": workflow_id,
        "id": workflow_id,
        "user_id": SYSTEM_USER,
        "title": w["title"],
        "description": w.get("description", ""),
        "prompt": w.get("prompt", ""),
        "slug": w["slug"],
        "steps": steps,
        "trigger_config": TriggerConfig(type=TriggerType.MANUAL, enabled=True).model_dump(
            mode="json"
        ),
        "activated": True,
        "is_public": True,
        "is_explore": True,
        "use_case_categories": w.get("categories", ["featured"]),
        "created_by": SYSTEM_USER,
        "total_executions": w.get("total_executions", 0),
        "successful_executions": 0,
        "current_step_index": 0,
        "execution_logs": [],
        "created_at": created_at,
        "updated_at": now,
    }


async def fetch_prod_explore() -> list[dict[str, Any]]:
    """Fetch every explore workflow from production (paginated)."""
    workflows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        offset = 0
        while True:
            resp = await client.get(
                PROD_EXPLORE_URL,
                params={"limit": PAGE_SIZE, "offset": offset},
            )
            resp.raise_for_status()
            data = resp.json()
            page = data.get("workflows", [])
            workflows.extend(page)
            total = data.get("total", len(page))
            offset += len(page)
            if offset >= total or not page:
                break
    return workflows


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prune",
        action="store_true",
        help="delete local explore workflows whose slug is not in production",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without writing anything",
    )
    args = parser.parse_args()

    print(f"Fetching explore workflows from {PROD_EXPLORE_URL} ...")
    prod = await fetch_prod_explore()
    print(f"✅ Production has {len(prod)} explore workflows")

    prod_slugs = {w["slug"] for w in prod}
    docs = [build_document(w) for w in prod]

    existing = await workflows_collection.count_documents(
        {"is_explore": True, "slug": {"$in": list(prod_slugs)}}
    )
    print(f"Local DB already has {existing} of those slugs")

    if args.dry_run:
        print("DRY RUN — no writes performed")
        print(f"  would upsert {len(docs)} workflows")
        if args.prune:
            stale = await workflows_collection.count_documents(
                {"is_explore": True, "slug": {"$nin": list(prod_slugs)}}
            )
            print(f"  would prune {stale} local explore workflows missing from prod")
        return

    # Replace the synced slugs wholesale (delete + insert) so ids stay
    # consistent with prod; docs with other slugs are left untouched.
    await workflows_collection.delete_many({"is_explore": True, "slug": {"$in": list(prod_slugs)}})
    if docs:
        await workflows_collection.insert_many(docs)
    print(f"✅ Upserted {len(docs)} workflows")

    if args.prune:
        pruned = await workflows_collection.delete_many(
            {"is_explore": True, "slug": {"$nin": list(prod_slugs)}}
        )
        print(f"🧹 Pruned {pruned.deleted_count} local explore workflows missing from prod")

    local_total = await workflows_collection.count_documents({"is_explore": True})
    print(f"Local explore total now: {local_total} (prod: {len(prod)})")

    # Also surface a slug diff for verification.
    local = await workflows_collection.distinct("slug", {"is_explore": True})
    missing = sorted(prod_slugs - set(local))
    extra = sorted(set(local) - prod_slugs)
    print(f"Missing vs prod: {missing or 'none'}")
    print(f"Extra vs prod: {extra or 'none'}")
    Path("/tmp/local_explore_slugs.json").write_text(
        json.dumps(sorted(local), indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
