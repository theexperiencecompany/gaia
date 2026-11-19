"""A brief past its year of retention is deleted with its edition image; a younger one stays.

Real seams: Mongo (the briefings collection), a local-volume blob store and the edition encoders.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image
import pytest
import time_machine

from app.config.settings import settings
from app.constants.briefing import BRIEFING_RETENTION, BriefingKind
from app.constants.notifications import NotificationKind
from app.db.repositories.briefings import briefing_repository
from app.models.brief_document_models import BriefDelivery, BriefingModel, EditionRender
from app.services.briefing.edition_image import store_edition
from app.workers.tasks.briefing_retention_tasks import sweep_expired_briefings
from tests.factories import make_briefing_payload, make_user_id
from tests.helpers import captured_wide_event

USER_ID = make_user_id()


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
    briefing_id = await briefing_repository.briefing_id_for(USER_ID, date, BriefingKind.DAILY)
    edition = (
        EditionRender(key=await store_edition(USER_ID, briefing_id, _png()))
        if with_edition
        else None
    )
    stored = await briefing_repository.upsert_briefing(
        BriefingModel(
            id=briefing_id,
            user_id=USER_ID,
            date=date,
            kind=BriefingKind.DAILY,
            payload=make_briefing_payload(date=date),
            edition=edition,
            delivery=BriefDelivery(push=True, notification_kind=NotificationKind.BRIEFING_DAILY),
        )
    )
    await raw_collection.update_one(
        {"_id": stored.id}, {"$set": {"created_at": datetime.now(UTC) - age}}
    )
    return stored


def _images(tmp_path: Path) -> list[str]:
    owner = tmp_path / USER_ID
    return sorted(p.name for p in owner.iterdir()) if owner.exists() else []


async def test_an_expired_brief_goes_with_its_image_and_a_younger_one_stays(
    raw_collection, tmp_path: Path
) -> None:
    past = BRIEFING_RETENTION + timedelta(days=1)
    expired = await _brief("2025-10-01", with_edition=True, age=past, raw_collection=raw_collection)
    older = await _brief("2025-09-30", with_edition=True, age=past, raw_collection=raw_collection)
    note = await _brief("2025-10-02", with_edition=False, age=past, raw_collection=raw_collection)
    kept = await _brief(
        "2026-10-01", with_edition=True, age=timedelta(days=1), raw_collection=raw_collection
    )
    nearly = await _brief(
        "2025-10-03",
        with_edition=False,
        age=BRIEFING_RETENTION - timedelta(hours=2),
        raw_collection=raw_collection,
    )
    assert expired.edition is not None and kept.edition is not None

    async with captured_wide_event() as event:
        summary = await sweep_expired_briefings({})

    assert summary == "expired=3 images=2"
    assert event["briefing_retention"] == {"briefs_expired": 3, "edition_images_deleted": 2}
    assert await briefing_repository.get(older.id, user_id=USER_ID) is None
    assert await briefing_repository.get(expired.id, user_id=USER_ID) is None
    assert await briefing_repository.get(note.id, user_id=USER_ID) is None
    assert await briefing_repository.get(kept.id, user_id=USER_ID) is not None
    assert await briefing_repository.get(nearly.id, user_id=USER_ID) is not None
    assert _images(tmp_path) == [
        f"brief-edition-{kept.edition.key}.jpg",
        f"brief-edition-{kept.edition.key}.png",
    ]


async def test_the_cutoff_is_a_utc_instant_whatever_zone_the_worker_runs_in(
    raw_collection,
) -> None:
    with time_machine.travel(datetime(2026, 11, 19, 12, tzinfo=ZoneInfo("America/New_York"))):
        just_past = await _brief(
            "2025-11-18",
            with_edition=False,
            age=BRIEFING_RETENTION + timedelta(hours=1),
            raw_collection=raw_collection,
        )

        assert await sweep_expired_briefings({}) == "expired=1 images=0"

    assert await briefing_repository.get(just_past.id, user_id=USER_ID) is None
