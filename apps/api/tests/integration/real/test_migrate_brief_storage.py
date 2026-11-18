"""The brief storage expand and contract migrations over real Mongo and a real local blob store."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
import io
from pathlib import Path
import uuid

import httpx
from motor.motor_asyncio import AsyncIOMotorCollection
from PIL import Image
import pytest
import respx

from app.config.settings import settings
from app.constants.briefing import EditionVariant
from app.db.repositories.briefings import briefing_repository
from app.services.blob_store import LocalVolumeBlobStore
from app.services.briefing import edition_image
from scripts import migrate_brief_storage as migration
from tests.factories import make_briefing_payload

OWNER = "owner-1"
_CREATED = datetime(2026, 11, 1, 2, 30, tzinfo=UTC)
_PUBLIC_ID = "gaia/briefings/b1"
_URL = f"https://res.cloudinary.com/gaia/image/upload/c_fit,w_1200/v1/{_PUBLIC_ID}"


@dataclass
class _Cloudinary:
    """Records the originals the migration destroys; Cloudinary is the third party here."""

    deleted: list[tuple[str, str]] = field(default_factory=list)

    async def delete(self, owner_id: str, public_id: str) -> None:
        self.deleted.append((owner_id, public_id))


@dataclass
class _Store:
    briefs: AsyncIOMotorCollection
    blobs: Path
    cloudinary: _Cloudinary


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (40, 30), (200, 30, 30, 255)).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
async def store(mongo_db, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncIterator[_Store]:
    """Point the migration and the brief repository at a fresh collection and a local blob dir."""
    s = _Store(
        briefs=mongo_db[f"briefings_storage_{uuid.uuid4().hex}"],
        blobs=tmp_path,
        cloudinary=_Cloudinary(),
    )
    monkeypatch.setattr(migration, "briefings_collection", s.briefs)
    monkeypatch.setattr("app.db.repositories.base.get_async_collection", lambda _name: s.briefs)
    # tmp_path is no mounted volume; the store refuses anything else in production.
    monkeypatch.setattr("app.services.blob_store._is_mountpoint", lambda _p: True)
    monkeypatch.setattr(edition_image, "link_content_store", lambda: LocalVolumeBlobStore(tmp_path))
    monkeypatch.setattr(settings, "INSTANCE_SECRET", "test-instance-secret")
    monkeypatch.setattr(migration, "CloudinaryBlobStore", lambda: s.cloudinary)
    yield s
    await s.briefs.drop()


def _brief(brief_id: str, **fields: object) -> dict[str, object]:
    return {
        "_id": brief_id,
        "user_id": OWNER,
        "date": "2026-11-01",
        "kind": "daily",
        "payload": make_briefing_payload().model_dump(mode="json"),
        "created_at": _CREATED,
        **fields,
    }


_LEGACY = {"edition_image_url": _URL, "edition_fold": 0.4, "edition_paper": None}


@respx.mock
async def test_expand_copies_the_edition_and_keeps_the_legacy_fields_and_the_original(
    store: _Store,
) -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, content=_png()))
    await store.briefs.insert_many(
        [_brief("b1", **_LEGACY), _brief("note", edition_image_url=None)]
    )

    await migration.migrate(apply=False)
    assert await store.briefs.count_documents({"edition": {"$exists": True}}) == 0

    await migration.migrate(apply=True)

    key = await edition_image.edition_key("b1")
    stored = await store.briefs.find_one({"_id": "b1"})
    assert stored is not None
    assert stored["edition"] == {"key": key, "fold": 0.4, "paper": None}
    assert stored["edition_image_url"] == _URL
    assert {p.name for p in (store.blobs / OWNER).iterdir()} == {
        f"brief-edition-{key}.{variant.value}" for variant in EditionVariant
    }
    assert store.cloudinary.deleted == []
    note = await store.briefs.find_one({"_id": "note"})
    assert note is not None and "edition" not in note and note["edition_image_url"] is None
    assert respx.calls.call_count == 1

    await migration.migrate(apply=True)
    assert respx.calls.call_count == 1


@respx.mock
async def test_contract_copies_what_was_stored_since_then_destroys_the_originals_and_the_fields(
    store: _Store,
) -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, content=_png()))
    await store.briefs.insert_one(_brief("note", edition_image_url=None))
    await migration.migrate(apply=True)
    await store.briefs.insert_one(_brief("b1", **_LEGACY))

    assert await migration.contract(apply=False) == 2
    assert store.cloudinary.deleted == []

    assert await migration.contract(apply=True) == 2

    assert store.cloudinary.deleted == [(OWNER, _PUBLIC_ID)]
    legacy = {"edition_image_url": {"$exists": True}}
    assert await store.briefs.count_documents(legacy) == 0
    brief = await briefing_repository.get("b1", user_id=OWNER)
    assert brief is not None and brief.edition is not None
    assert brief.edition.key == await edition_image.edition_key("b1")
    assert await migration.contract(apply=True) == 0
