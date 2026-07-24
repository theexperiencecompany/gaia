"""Contract tests for FilesRepository (user-scoped, addressed by ``file_id``)."""

from __future__ import annotations

from datetime import UTC, datetime
import uuid

import pytest

from app.db.repositories.files import FilesRepository
from app.models.files_models import FileDocument, FileUpdate

NOW = datetime.now(UTC)


def _file(**overrides: object) -> FileDocument:
    data: dict[str, object] = {
        "file_id": uuid.uuid4().hex,
        "user_id": "u1",
        "filename": "report.pdf",
        "type": "application/pdf",
        "size": 1024,
        "url": "https://cdn.example/report.pdf",
        "public_id": "file_abc",
        "description": "a report",
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return FileDocument.model_validate(data)


@pytest.fixture
def repo(raw_collection) -> FilesRepository:
    return FilesRepository()


class TestFilesRepository:
    async def test_create_preserves_objectid_id_and_file_id(self, repo):
        fid = uuid.uuid4().hex
        created = await repo.create(_file(file_id=fid, user_id="u"))
        # file_id is the business key; id is the incidental ObjectId (24 hex chars).
        assert created.file_id == fid
        assert isinstance(created.id, str) and len(created.id) == 24

        got = await repo.get_by_file_id(fid, "u")
        assert got is not None and got.id == created.id

    async def test_get_by_file_id_is_user_scoped(self, repo):
        fid = uuid.uuid4().hex
        await repo.create(_file(file_id=fid, user_id="owner"))
        assert await repo.get_by_file_id(fid, "intruder") is None

    async def test_find_by_ids_for_user_filters_and_scopes(self, repo):
        a, b, c = (uuid.uuid4().hex for _ in range(3))
        await repo.create(_file(file_id=a, user_id="u"))
        await repo.create(_file(file_id=b, user_id="u"))
        await repo.create(_file(file_id=c, user_id="other"))

        found = await repo.find_by_ids_for_user([a, b, c], "u")
        assert {d.file_id for d in found} == {a, b}  # c belongs to another user
        assert await repo.find_by_ids_for_user([], "u") == []

    async def test_apply_metadata_update_sets_fields_and_stamps(self, repo):
        fid = uuid.uuid4().hex
        created = await repo.create(_file(file_id=fid, user_id="u", filename="old.pdf"))

        updated = await repo.apply_metadata_update(
            fid, user_id="u", update=FileUpdate(filename="new.pdf")
        )
        assert updated is not None
        assert updated.filename == "new.pdf"
        assert updated.updated_at is not None and updated.updated_at >= created.updated_at

    async def test_apply_metadata_update_empty_still_bumps_updated_at(self, repo):
        fid = uuid.uuid4().hex
        created = await repo.create(_file(file_id=fid, user_id="u"))

        # An empty patch is a no-field update that still refreshes updated_at.
        updated = await repo.apply_metadata_update(fid, user_id="u", update=FileUpdate())
        assert updated is not None
        assert updated.filename == created.filename
        assert updated.updated_at is not None and updated.updated_at >= created.updated_at

    async def test_apply_metadata_update_missing_returns_none(self, repo):
        assert (
            await repo.apply_metadata_update("nope", user_id="u", update=FileUpdate(filename="x"))
            is None
        )

    async def test_delete_by_file_id_is_scoped(self, repo):
        fid = uuid.uuid4().hex
        await repo.create(_file(file_id=fid, user_id="u"))
        assert await repo.delete_by_file_id(fid, "other") is False
        assert await repo.delete_by_file_id(fid, "u") is True
        assert await repo.get_by_file_id(fid, "u") is None
