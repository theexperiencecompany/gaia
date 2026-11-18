"""Idempotent migration: bring every stored brief to the edition and delivery shape briefs now use.

1. Editions: a brief stored before editions moved kept a public Cloudinary delivery URL in
   edition_image_url, beside edition_fold and edition_paper. Its image is downloaded, stored as the
   brief's edition variants under its edition key, recorded as edition {key, fold, paper}, and the
   Cloudinary original is destroyed; a brief with no image (a quiet note) only loses the old fields.
2. Deliveries: a brief that reached a channel before deliveries were planned is recorded as
   delivered (every step done, completed when it was created), so a run today neither resends it
   nor drops its stamp.

Re-running skips every brief already moved. Run it in the post-deploy step, before the first
brief runs on the new code.

    cd apps/api && uv run python scripts/migrate_brief_storage.py [--apply]
"""

import asyncio
from pathlib import Path
import sys
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.briefing import (
    BriefingKind,
)
from app.constants.files import BLOB_DOWNLOAD_TIMEOUT_SECONDS
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.db.mongodb.collections import get_async_collection
from app.models.briefing_models import BriefDelivery, DeliveryStep, EditionRender
from app.services.blob_store import CloudinaryBlobStore
from app.services.briefing.edition_image import store_edition

#: Everything after this in a Cloudinary delivery URL is the transformation, then v1/<public id>.
_UPLOAD_SEGMENT = "/image/upload/"
_LEGACY_FIELDS = {"edition_image_url": "", "edition_fold": "", "edition_paper": ""}

briefings_collection = get_async_collection("briefings")


def _public_id(delivery_url: str) -> str:
    """Return the Cloudinary public id a delivery URL serves: the path after its version segment."""
    path = urlsplit(delivery_url).path.split(_UPLOAD_SEGMENT, 1)[1]
    return path.split("/v1/", 1)[1]


async def _move_editions(apply: bool, mode: str) -> None:
    """Move each legacy edition image into the private store and record its key."""
    print(f"[{mode}] Moving brief edition images off Cloudinary\n")
    query = {"edition_image_url": {"$exists": True}}
    moved = cleared = 0
    async with httpx.AsyncClient(timeout=BLOB_DOWNLOAD_TIMEOUT_SECONDS) as client:
        async for doc in briefings_collection.find(query):
            url = doc.get("edition_image_url")
            if url is None:
                cleared += 1
                if apply:
                    await briefings_collection.update_one(
                        {"_id": doc["_id"]}, {"$unset": _LEGACY_FIELDS}
                    )
                continue
            moved += 1
            print(f"  {doc['_id']}: {url}")
            if not apply:
                continue
            response = await client.get(url, headers={"Accept": "image/png"})
            response.raise_for_status()
            key = await store_edition(doc["user_id"], doc["_id"], response.content)
            edition = EditionRender(
                key=key, fold=doc.get("edition_fold"), paper=doc.get("edition_paper")
            )
            await briefings_collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {"edition": edition.model_dump()}, "$unset": _LEGACY_FIELDS},
            )
            await CloudinaryBlobStore().delete(doc["user_id"], _public_id(url))

    print(f"\n[{mode}] Editions done. moved={moved} notes_cleared={cleared}")


async def _complete_deliveries(apply: bool, mode: str) -> None:
    """Record every brief that reached a channel before deliveries were planned as delivered."""
    print(f"\n[{mode}] Recording legacy deliveries\n")
    query = {"delivery": {"$exists": False}, "delivered_channels.0": {"$exists": True}}
    completed = 0
    async for doc in briefings_collection.find(query, {"kind": 1, "created_at": 1}):
        completed += 1
        if not apply:
            continue
        delivered = BriefDelivery(
            push=True,
            notification_kind=NOTIFICATION_KIND_BRIEFING_DAILY
            if doc.get("kind", BriefingKind.DAILY) == BriefingKind.DAILY
            else NOTIFICATION_KIND_BRIEFING_WEEKLY,
            done=list(DeliveryStep),
            completed_at=doc["created_at"],
        )
        await briefings_collection.update_one(
            {"_id": doc["_id"], "delivery": {"$exists": False}},
            {"$set": {"delivery": delivered.model_dump()}},
        )
    print(f"[{mode}] Deliveries done. completed={completed}")


async def migrate(apply: bool) -> None:
    """Run both moves; each skips what an earlier run already moved."""
    mode = "APPLY" if apply else "DRY RUN"
    await _move_editions(apply, mode)
    await _complete_deliveries(apply, mode)
    if not apply:
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
