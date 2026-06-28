#!/usr/bin/env python3
"""
Backfill LLM-generated marketplace content for published custom integrations.

Native (platform) integrations ship curated content from `app/config/oauth_content.py`.
Custom integrations only get content generated at publish time (see
`integration_inference_service`). Integrations published before that feature shipped have no
content and fall back to the frontend's generic copy. This script generates content for
them using the exact same service the publish flow uses.

Scope: integrations with `is_public=True` and `source="custom"`. By default only those
WITHOUT existing content are processed; pass --regenerate to overwrite existing content.

IMPORTANT: Run from the api directory (so `app` is importable):

    cd /path/to/gaia/apps/api
    python scripts/backfill_integration_content.py --dry-run --limit 3

Usage flags:
--dry-run:     Generate and print content, write NOTHING to the database
--limit N:     Process at most N integrations (use with --dry-run to sample)
--regenerate:  Also (re)generate content for integrations that already have it
--force:       Skip the confirmation prompt before writing
--backup:      Write a JSON backup of affected docs' current content before writing
"""

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

# Add the backend directory to Python path so we can import from app
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Import app modules after path setup  # noqa: E402
from app.db.mongodb.collections import integrations_collection  # noqa: E402
from app.db.redis import delete_cache_by_pattern  # noqa: E402
from app.models.oauth_models import IntegrationContent  # noqa: E402
from app.services.integrations.integration_inference_service import (  # noqa: E402
    infer_integration_content,
)

# Cache pattern invalidated by the publish flow when marketplace content changes.
MARKETPLACE_CACHE_PATTERN = "marketplace:community:*"


def build_query(regenerate: bool) -> dict[str, Any]:
    """Public custom integrations, optionally only those missing content."""
    query: dict[str, Any] = {"is_public": True, "source": "custom"}
    if not regenerate:
        query["$or"] = [{"content": {"$exists": False}}, {"content": None}]
    return query


def print_content(name: str, content: IntegrationContent) -> None:
    """Pretty-print generated content for human review during a dry run."""
    print(f"\n{'=' * 70}\n  {name}\n{'=' * 70}")
    print("  Use cases:")
    for uc in content.use_cases:
        print(f"    - {uc}")
    print("  How it works:")
    for step in content.how_it_works:
        print(f"    • {step.title}")
        print(f"      {step.body}")
    print("  FAQs:")
    for faq in content.faqs:
        print(f"    Q: {faq.question}")
        print(f"    A: {faq.answer}")


async def create_backup(docs: list[dict[str, Any]]) -> str:
    """Back up the current `content` field of affected docs before overwriting."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_file = f"integration_content_backup_{timestamp}.json"
    snapshot = [
        {"integration_id": d["integration_id"], "name": d.get("name"), "content": d.get("content")}
        for d in docs
    ]
    with open(backup_file, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)
    print(f"✅ Backup created: {backup_file}")
    return backup_file


async def backfill(
    dry_run: bool, limit: int | None, regenerate: bool, force: bool, backup: bool
) -> None:
    print("🔄 Backfilling marketplace content for published custom integrations...")

    query = build_query(regenerate)
    cursor = integrations_collection.find(query)
    if limit is not None:
        cursor = cursor.limit(limit)
    docs = await cursor.to_list(length=limit if limit is not None else None)

    print(
        f"\n📊 Matched {len(docs)} integration(s) "
        f"({'including' if regenerate else 'excluding'} those with existing content)"
        f"{f', limited to {limit}' if limit is not None else ''}."
    )

    if not docs:
        print("✅ Nothing to do.")
        return

    if not dry_run and not force:
        response = input(f"\n❓ Generate + write content for {len(docs)} integration(s)? (y/N): ")
        if response.lower() != "y":
            print("❌ Operation cancelled.")
            return

    if not dry_run and backup:
        await create_backup(docs)

    generated = 0
    skipped = 0
    written = 0

    for doc in docs:
        name = doc.get("name", "")
        content = await infer_integration_content(
            name=name,
            description=doc.get("description", ""),
            tools=doc.get("tools", []),
            server_url=(doc.get("mcp_config") or {}).get("server_url", ""),
            category=doc.get("category", "other"),
        )

        if content is None:
            print(f"⚠️  Skipped (generation failed): {name} ({doc['integration_id']})")
            skipped += 1
            continue

        generated += 1
        print_content(name, content)

        if dry_run:
            continue

        # Target the exact document we read by its Mongo _id, not integration_id,
        # so a concurrent write (e.g. content added after this read) is never
        # clobbered and we never rely on integration_id uniqueness.
        result = await integrations_collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {"content": content.model_dump(), "updated_at": datetime.now(UTC)}},
        )
        written += result.modified_count

    print(f"\n{'=' * 70}")
    if dry_run:
        print(f"🔍 DRY RUN — generated {generated}, skipped {skipped}, wrote 0.")
        print("   Run without --dry-run to persist these changes.")
        return

    print(f"✅ Generated {generated}, skipped {skipped}, wrote {written}.")
    print("\n🧹 Clearing marketplace cache...")
    await delete_cache_by_pattern(MARKETPLACE_CACHE_PATTERN)
    print("✅ Cache cleared.")


def positive_int(value: str) -> int:
    """argparse type: accept only integers >= 1."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value}")
    return parsed


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill LLM-generated marketplace content for custom integrations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/backfill_integration_content.py --dry-run --limit 3   # sample 3, no writes
  python scripts/backfill_integration_content.py --backup              # write missing, with backup
  python scripts/backfill_integration_content.py --regenerate --force  # overwrite all, no prompt
        """,
    )
    parser.add_argument("--dry-run", action="store_true", help="Generate and print, write nothing")
    parser.add_argument(
        "--limit", type=positive_int, default=None, help="Process at most N integrations (>= 1)"
    )
    parser.add_argument(
        "--regenerate", action="store_true", help="Overwrite content that already exists"
    )
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    parser.add_argument(
        "--backup", action="store_true", help="Back up current content before writing"
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_arguments()
    try:
        await backfill(
            dry_run=args.dry_run,
            limit=args.limit,
            regenerate=args.regenerate,
            force=args.force,
            backup=args.backup,
        )
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
