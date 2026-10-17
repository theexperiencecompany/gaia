"""Backfill deterministic tool-grounded content for top community MCPs.

Duplicate-copy problem: published custom integrations whose LLM content
generation failed (or that were published before it shipped) serve the
frontend's generic per-category templates — N same-category pages that differ
only by name in meta, FAQs, and use-cases.

This script writes deterministic content built from each integration's real
tool names/descriptions plus its category and auth type (see
``integration_content_fallback``), so same-category pages differ by more than
the name and the FAQPage/HowTo schemas stay unique per page.

Demand proxy: there is no per-page analytics, so targets are the top
``--limit`` public custom integrations by ``clone_count`` descending — the same
signal the marketplace "popular" sort uses. Tool counts print in dry-run
output as a secondary relevance signal.

Idempotent: docs whose stored content already satisfies the 5/3/4 contract
are skipped unless ``--regenerate`` is passed, so re-runs only touch new
gaps. Dry-run by default; pass ``--apply`` to write.

Run from repo root:

    cd apps/api && uv run python scripts/seed_community_content.py
    cd apps/api && uv run python scripts/seed_community_content.py --apply
    cd apps/api && uv run python scripts/seed_community_content.py --apply --limit 30
    cd apps/api && uv run python scripts/seed_community_content.py --apply --slugs foo-mcp-other,bar-mcp-developer
    cd apps/api && uv run python scripts/seed_community_content.py --apply --regenerate --limit 5
"""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.integrations import FAQ_COUNT, HOW_IT_WORKS_COUNT, USE_CASES_COUNT
from app.db.mongodb.collections import get_async_collection
from app.db.redis import delete_cache_by_pattern
from app.models.integration_models import StoredIntegrationTool
from app.services.integrations.integration_content_fallback import (
    build_fallback_content,
    build_fallback_description,
)

integrations_collection = get_async_collection("integrations")

MARKETPLACE_CACHE_PATTERN = "marketplace:community:*"

# Descriptions at or under this length carry no SEO weight; they get replaced
# with tool-grounded copy alongside the content backfill.
THIN_DESCRIPTION_MAX_LEN = 40

DEFAULT_LIMIT = 15


def _is_complete(content: object) -> bool:
    """Whether stored content already satisfies the 5/3/4 cardinality contract."""
    if not isinstance(content, dict):
        return False
    use_cases = content.get("use_cases")
    how_it_works = content.get("how_it_works")
    faqs = content.get("faqs")
    return (
        isinstance(use_cases, list)
        and len(use_cases) == USE_CASES_COUNT
        and isinstance(how_it_works, list)
        and len(how_it_works) == HOW_IT_WORKS_COUNT
        and isinstance(faqs, list)
        and len(faqs) == FAQ_COUNT
    )


def _content_word_count(content: dict[str, Any]) -> int:
    """Total words across use-cases, how-it-works bodies, and FAQ text."""
    words = 0
    for uc in content.get("use_cases", []):
        words += len(str(uc).split())
    for step in content.get("how_it_works", []):
        words += len(str(step.get("title", "")).split())
        words += len(str(step.get("body", "")).split())
    for faq in content.get("faqs", []):
        words += len(str(faq.get("question", "")).split())
        words += len(str(faq.get("answer", "")).split())
    return words


def _coerce_tools(raw: object) -> list[StoredIntegrationTool]:
    """Stored tool dicts -> models, skipping nameless entries."""
    if not isinstance(raw, list):
        return []
    tools: list[StoredIntegrationTool] = []
    for item in raw:
        if isinstance(item, dict) and item.get("name"):
            tools.append(
                StoredIntegrationTool(name=item["name"], description=item.get("description"))
            )
    return tools


def _auth_type(doc: dict[str, Any]) -> str | None:
    """mcp_config is authoritative; the legacy top-level mirror covers old docs."""
    mcp_config = doc.get("mcp_config") or {}
    return mcp_config.get("auth_type") or doc.get("auth_type")


def _build_update(doc: dict[str, Any]) -> dict[str, Any]:
    """Content + thin-description $set document for one integration."""
    name = doc.get("name", "")
    tools = _coerce_tools(doc.get("tools"))
    category = doc.get("category") or "other"
    content = build_fallback_content(
        name=name,
        description=doc.get("description"),
        tools=tools,
        category=category,
        auth_type=_auth_type(doc),
    )
    update: dict[str, Any] = {
        "content": content.model_dump(),
        "updated_at": datetime.now(UTC),
    }
    if len((doc.get("description") or "").strip()) <= THIN_DESCRIPTION_MAX_LEN:
        update["description"] = build_fallback_description(
            name=name, tools=tools, category=category
        )
    return update


def _report_doc(update: dict[str, Any]) -> None:
    """Print what a doc's planned write carries (word count, FAQ sample)."""
    content = update["content"]
    words = _content_word_count(content)
    faqs = content.get("faqs", [])
    sample = faqs[2].get("question", "") if len(faqs) > 2 else ""
    print(
        f"  content: {words} words, "
        f"{len(content.get('use_cases', []))} use-cases, "
        f"{len(content.get('how_it_works', []))} steps, "
        f"{len(faqs)} FAQs"
    )
    print(f'    sample FAQ: "{sample}"')
    if "description" in update:
        print("  description: thin -> backfilled")
    else:
        print("  description: kept")
    if words < 150:
        print("  WARNING: content under 150 words — review before applying.")


async def _fetch_targets(slugs: list[str] | None, limit: int) -> list[dict[str, Any]]:
    """Top public custom integrations by clone_count (the popular-sort signal)."""
    query: dict[str, Any] = {"is_public": True, "source": "custom"}
    if slugs:
        query["slug"] = {"$in": slugs}
    return (
        await integrations_collection.find(query)
        .sort([("clone_count", -1), ("published_at", -1)])
        .limit(limit)
        .to_list(length=limit)
    )


async def run(apply: bool, limit: int, slugs: list[str] | None, regenerate: bool) -> None:
    docs = await _fetch_targets(slugs, limit)
    print(f"Matched {len(docs)} public custom integration(s) (limit {limit}).")
    if not docs:
        print("Nothing to do.")
        return

    written = skipped = 0
    for doc in docs:
        tools = _coerce_tools(doc.get("tools"))
        print(
            f"\n• {doc.get('name', '')} [{doc.get('slug', '')}] "
            f"(clones={doc.get('clone_count', 0)}, tools={len(tools)}, "
            f"category={doc.get('category')}, auth={_auth_type(doc)})"
        )
        if not tools:
            print("  SKIP: no stored tools — nothing tool-grounded to write.")
            skipped += 1
            continue
        if _is_complete(doc.get("content")) and not regenerate:
            print("  SKIP: content already complete (pass --regenerate to overwrite).")
            skipped += 1
            continue

        update = _build_update(doc)
        _report_doc(update)
        if not apply:
            print("  -> would write (dry-run)")
            continue
        await integrations_collection.update_one(
            {"integration_id": doc["integration_id"]}, {"$set": update}
        )
        written += 1

    print(f"\n{'Applied' if apply else 'Dry-run'} — wrote {written}, skipped {skipped}.")
    if not apply:
        print("Re-run with --apply to write these changes.")
        return
    if written:
        print("Clearing marketplace cache...")
        await delete_cache_by_pattern(MARKETPLACE_CACHE_PATTERN)
        print("Cache cleared.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write the changes (default: dry-run)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Process at most N integrations by clone_count (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--slugs",
        type=str,
        default=None,
        help="Comma-separated marketplace slugs to restrict the run to.",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Overwrite content that already satisfies the 5/3/4 contract.",
    )
    args = parser.parse_args()
    slugs = [s.strip() for s in args.slugs.split(",") if s.strip()] if args.slugs else None
    asyncio.run(run(args.apply, args.limit, slugs, args.regenerate))
