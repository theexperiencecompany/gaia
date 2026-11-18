"""A brief past its year of retention is deleted with its edition image; a younger one stays.

Real seams: Mongo (the briefings collection), a local-volume blob store and the edition encoders.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
from pathlib import Path

from PIL import Image
import pytest

from app.config.settings import settings
from app.constants.briefing import BRIEFING_RETENTION, BriefingKind, EditionFamily
from app.db.repositories.briefings import briefing_repository
from app.models.brief_document_models import BriefDelivery, BriefingModel, EditionRender
from app.models.brief_payload_models import BriefingMood, BriefingPayload
from app.services.briefing.edition_image import store_edition
from app.workers.tasks.briefing_retention_tasks import sweep_expired_briefings

_USER = "64f1c0ffee0000000000abcd"


@pytest.fixture(autouse=True)
def _self_hosted(raw_collection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENV", "selfhost")
    monkeypatch.setattr(settings, "LOCAL_FILE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "INSTANCE_SECRET", "s" * 48)
    monkeypatch.setattr("app.services.blob_store._is_mountpoint", lambda _p: True)


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (40, 60), (240, 236, 228, 255)).save(out, format="PNG")
    return out.getvalue()


async def _brief(date: str, *, with_edition: bool, age: timedelta, raw_collection) -> BriefingModel:
    briefing_id = await briefing_repository.briefing_id_for(_USER, date, BriefingKind.DAILY)
    edition = (
        EditionRender(key=await store_edition(_USER, briefing_id, _png())) if with_edition else None
    )
    stored = await briefing_repository.upsert_briefing(
        BriefingModel(
            id=briefing_id,
            user_id=_USER,
            date=date,
            kind=BriefingKind.DAILY,
            payload=BriefingPayload(
                kicker="K",
                date=date,
                headline="h",
                lede="l",
                mood=BriefingMood.CLEAR,
                caption="c",
                template_family=EditionFamily.POSTAL,
            ),
            edition=edition,
            delivery=BriefDelivery(push=True, notification_kind="briefing_daily"),
        )
    )
    await raw_collection.update_one(
        {"_id": stored.id}, {"$set": {"created_at": datetime.now(UTC) - age}}
    )
    return stored


def _images(tmp_path: Path) -> list[str]:
    owner = tmp_path / _USER
    return sorted(p.name for p in owner.iterdir()) if owner.exists() else []


async def test_an_expired_brief_goes_with_its_image_and_a_younger_one_stays(
    raw_collection, tmp_path: Path
) -> None:
    past = BRIEFING_RETENTION + timedelta(days=1)
    expired = await _brief("2025-10-01", with_edition=True, age=past, raw_collection=raw_collection)
    note = await _brief("2025-10-02", with_edition=False, age=past, raw_collection=raw_collection)
    kept = await _brief(
        "2026-10-01", with_edition=True, age=timedelta(days=1), raw_collection=raw_collection
    )
    assert expired.edition is not None and kept.edition is not None

    summary = await sweep_expired_briefings({})

    assert summary == "expired=2 images=1"
    assert await briefing_repository.get(expired.id, user_id=_USER) is None
    assert await briefing_repository.get(note.id, user_id=_USER) is None
    assert await briefing_repository.get(kept.id, user_id=_USER) is not None
    assert _images(tmp_path) == [
        f"brief-edition-{kept.edition.key}.jpg",
        f"brief-edition-{kept.edition.key}.png",
    ]
