#!/usr/bin/env python3
"""Backfill descriptions and prompts for public workflows.

Today every seeded explore workflow stores the same long string in both
``description`` (shown on cards) and ``prompt`` (sent to the agent), and the
three user-published community workflows have ``prompt = None`` and rely on
the legacy ``effective_prompt`` fallback. This script splits them apart:

- Explore workflows (37): replace ``description`` with a short marketing line
  and leave ``prompt`` alone.
- Community workflows (3): copy ``description`` into ``prompt`` so execution
  no longer depends on the runtime fallback.

Usage::

    cd apps/api
    uv run python -m app.scripts.backfill_public_workflow_descriptions          # dry run
    uv run python -m app.scripts.backfill_public_workflow_descriptions --apply  # commit

Flags::

    --apply         Persist changes to MongoDB (otherwise dry run only).
    --only <id>     Process a single workflow id (repeatable).
    --skip-orphans  Skip warning about public workflows missing from the
                    manifest.

The diff prints per-workflow before/after for both fields so the change is
easy to eyeball before committing.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from app.db.mongodb.collections import workflows_collection
from shared.py.wide_events import log

# ---------------------------------------------------------------------------
# Manifest of edits, keyed by workflow id (``_id`` in Mongo).
#
# - ``description``: new short marketing copy. ``None`` means leave as-is.
# - ``prompt``: new prompt text. ``None`` means leave as-is. The string
#   ``"<copy-description>"`` is a sentinel meaning "copy whatever description
#   the document has after this run into prompt"; used for the user-published
#   community workflows where prompt is currently null.
# ---------------------------------------------------------------------------

COPY_DESCRIPTION = "<copy-description>"


MANIFEST: dict[str, dict[str, str | None]] = {
    # --- Community (user-published) — copy desc → prompt -------------------
    "wf_fa50beaef986": {
        "description": None,
        "prompt": COPY_DESCRIPTION,
    },
    "wf_060d028851e6": {
        "description": None,
        "prompt": COPY_DESCRIPTION,
    },
    "wf_10b4f4751db5": {
        "description": None,
        "prompt": COPY_DESCRIPTION,
    },
    # --- Explore (seeded) — short desc, prompt untouched -------------------
    "wf_6bda2590e3e9": {
        "description": "Summarize papers and save organized notes to Notion",
        "prompt": None,
    },
    "wf_78d971a94207": {
        "description": "Build a focused study plan from your classes and deadlines",
        "prompt": None,
    },
    "wf_aa8198496b85": {
        "description": "Drop a link or topic, get a Notion summary back",
        "prompt": None,
    },
    "wf_d9f599cc3845": {
        "description": "Research a topic and get a clean writing outline",
        "prompt": None,
    },
    "wf_0d17b6e32b2a": {
        "description": "Boil long email threads down to action items",
        "prompt": None,
    },
    "wf_13deadd41840": {
        "description": "Pull context for every meeting before the day starts",
        "prompt": None,
    },
    "wf_85e49fd06218": {
        "description": "Auto-archive newsletters and promo email",
        "prompt": None,
    },
    "wf_479846c32922": {
        "description": "Turn your week of commits and PRs into standup notes",
        "prompt": None,
    },
    "wf_83efd6ae1c7f": {
        "description": "Plan posts around analytics and upcoming events",
        "prompt": None,
    },
    "wf_90c7cb800281": {
        "description": "Condense Notion lecture notes into key concepts",
        "prompt": None,
    },
    "wf_aa467e290930": {
        "description": "Turn unread emails into structured todos",
        "prompt": None,
    },
    "wf_202b8962082d": {
        "description": "Spin up a project board for any group assignment",
        "prompt": None,
    },
    "wf_56f90174b0ef": {
        "description": "Pack the week's notes into a revision set with practice questions",
        "prompt": None,
    },
    "wf_e7db2870b045": {
        "description": "Track new applicants and route them through hiring",
        "prompt": None,
    },
    "wf_4df9dcb8d3f2": {
        "description": "Pull deadlines and tasks out of professor emails",
        "prompt": None,
    },
    "wf_b71111bc72ac": {
        "description": "Turn a spec doc into Linear issues",
        "prompt": None,
    },
    "wf_c1e8c712b981": {
        "description": "A daily snapshot of every todo, deadline, and priority",
        "prompt": None,
    },
    "wf_6a455bb94dc2": {
        "description": "Auto-summarize long emails and extract todos",
        "prompt": None,
    },
    "wf_699c100a63de": {
        "description": "Turn loose ideas into structured Notion pages",
        "prompt": None,
    },
    "wf_0bfa0234317a": {
        "description": "Daily customer sentiment summary across email and social",
        "prompt": None,
    },
    "wf_f487d5cabcd3": {
        "description": "Surface the 3 things that matter most today",
        "prompt": None,
    },
    "wf_1422f3cd78be": {
        "description": "Roll Slack, GitHub, and Linear updates into one weekly brief",
        "prompt": None,
    },
    "wf_6f55865d65a3": {
        "description": "Weekly SEO content briefs from trending topics",
        "prompt": None,
    },
    "wf_f783fdaefc46": {
        "description": "Triage social mentions and draft replies",
        "prompt": None,
    },
    "wf_632fcb4fd697": {
        "description": "Weekly social analytics plus a draft LinkedIn post",
        "prompt": None,
    },
    "wf_320e85c001d1": {
        "description": "Auto-log investor emails into your CRM",
        "prompt": None,
    },
    "wf_bba01bbc172b": {
        "description": "Marketing metrics rolled up into a weekly report",
        "prompt": None,
    },
    "wf_375a5500b1ce": {
        "description": "Build a weekly work report from your completed todos",
        "prompt": None,
    },
    "wf_234d37200c6e": {
        "description": "Convert bug reports into properly labeled GitHub issues",
        "prompt": None,
    },
    "wf_3248bdc09214": {
        "description": "Weekly competitive intelligence from social and web",
        "prompt": None,
    },
    "wf_8bc58913faad": {
        "description": "Hourly Slack ping with the PRs that need attention",
        "prompt": None,
    },
    "wf_ed7678659900": {
        "description": "One feed of every issue, PR, and ticket waiting on you",
        "prompt": None,
    },
    "wf_4efa3dc5c586": {
        "description": "Triage email, draft replies, and flag what matters",
        "prompt": None,
    },
    "wf_f154136f8bea": {
        "description": "Prioritized PR queue with summaries and risk notes",
        "prompt": None,
    },
    "wf_15ffd20a34c8": {
        "description": "Find influencers and draft personalized outreach",
        "prompt": None,
    },
    "wf_e5ec46351ed1": {
        "description": "Track every upcoming assignment and deadline",
        "prompt": None,
    },
    "wf_75c46cd5bf6c": {
        "description": "Auto-post a summary of every new PR to Slack",
        "prompt": None,
    },
}


def _truncate(text: str, limit: int = 80) -> str:
    text = (text or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _resolve_prompt(target: str | None, next_description: str) -> str | None:
    if target is None:
        return None
    if target == COPY_DESCRIPTION:
        return next_description
    return target


def _select_manifest(only: set[str]) -> dict | None:
    if not only:
        return MANIFEST
    manifest = {k: v for k, v in MANIFEST.items() if k in only}
    if not manifest:
        print(f"No manifest entries matched {only}.")
        return None
    return manifest


def _report_discrepancies(docs: dict, manifest: dict, *, skip_orphans: bool) -> None:
    orphan_ids = sorted(set(docs) - set(MANIFEST))
    missing_ids = sorted(set(manifest) - set(docs))

    if orphan_ids and not skip_orphans:
        print()
        print("Public workflows with NO manifest entry (left untouched):")
        for wid in orphan_ids:
            doc = docs[wid]
            print(f"  - {wid}  {doc.get('title', '')!r}  slug={doc.get('slug')!r}")

    if missing_ids:
        print()
        print("Manifest entries that no longer exist in Mongo:")
        for wid in missing_ids:
            print(f"  - {wid}")


def _plan_for(wid: str, target: dict, doc: dict) -> tuple[dict[str, str], dict[str, str]] | None:
    current_desc = doc.get("description") or ""
    current_prompt = doc.get("prompt") or ""

    next_desc = target["description"] if target["description"] is not None else current_desc
    next_prompt = _resolve_prompt(target["prompt"], next_desc)
    if next_prompt is None:
        next_prompt = current_prompt

    if next_desc == current_desc and next_prompt == current_prompt:
        print(f"  [skip] {wid} {doc.get('title', '')!r} — already matches target")
        return None

    before = {"description": current_desc, "prompt": current_prompt}
    after = {"description": next_desc, "prompt": next_prompt}
    _print_edit(wid, doc.get("title", ""), before, after)
    return before, after


def _print_edit(wid: str, title: str, before: dict[str, str], after: dict[str, str]) -> None:
    print()
    print(f"  [edit] {wid}  {title!r}")
    if before["description"] != after["description"]:
        print(f"    description: {_truncate(before['description'])}")
        print(f"             ->  {_truncate(after['description'])}")
    if before["prompt"] != after["prompt"]:
        print(f"    prompt:      {_truncate(before['prompt'])}")
        print(f"             ->  {_truncate(after['prompt'])}")


def _build_plans(manifest: dict, docs: dict) -> list[tuple[str, dict[str, str], dict[str, str]]]:
    plans: list[tuple[str, dict[str, str], dict[str, str]]] = []
    for wid, target in manifest.items():
        doc = docs.get(wid)
        if doc is None:
            continue
        plan = _plan_for(wid, target, doc)
        if plan is not None:
            plans.append((wid, plan[0], plan[1]))
    return plans


async def _apply_plans(
    plans: list[tuple[str, dict[str, str], dict[str, str]]],
) -> None:
    now = datetime.now(UTC)
    confirmed = 0
    for wid, _before, after in plans:
        result = await workflows_collection.update_one(
            {"_id": wid, "is_public": True},
            {
                "$set": {
                    "description": after["description"],
                    "prompt": after["prompt"],
                    "updated_at": now,
                }
            },
        )
        if result.modified_count == 1:
            confirmed += 1
            log.info(
                "Backfilled public workflow",
                workflow_id=wid,
                description_len=len(after["description"]),
                prompt_len=len(after["prompt"]),
            )
        else:
            print(
                f"  WARN: update for {wid} matched={result.matched_count} "
                f"modified={result.modified_count}"
            )

    print()
    print(f"Applied {confirmed}/{len(plans)} updates.")


async def _run(args: argparse.Namespace) -> int:
    manifest = _select_manifest(set(args.only or []))
    if manifest is None:
        return 1

    cursor = workflows_collection.find({"is_public": True})
    docs = {doc["_id"]: doc async for doc in cursor}

    print(f"Found {len(docs)} public workflows in Mongo; manifest covers {len(manifest)}.")
    _report_discrepancies(docs, manifest, skip_orphans=args.skip_orphans)

    print()
    print("=" * 78)
    print("Per-workflow plan (DRY RUN)" if not args.apply else "Per-workflow plan")
    print("=" * 78)

    plans = _build_plans(manifest, docs)

    print()
    print("=" * 78)
    print(f"Summary: {len(plans)} workflow(s) need updating.")
    print("=" * 78)

    if not args.apply:
        print()
        print("Dry run only. Re-run with --apply to commit.")
        return 0

    if not plans:
        print("Nothing to apply.")
        return 0

    await _apply_plans(plans)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes (otherwise dry run only).",
    )
    parser.add_argument(
        "--only",
        action="append",
        help="Process only this workflow id (repeatable).",
    )
    parser.add_argument(
        "--skip-orphans",
        action="store_true",
        help="Suppress the orphan-workflow warning.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
