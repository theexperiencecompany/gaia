"""Contract tests for FilesRepository (user-scoped, addressed by file_id)."""

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

    async def test_find_mimetype_rows_reads_both_shapes(self, repo, raw_collection):
        await raw_collection.insert_many(
            [
                {"file_id": "legacy", "filename": "old.png", "content_type": "image/png"},
                {"file_id": "modern", "filename": "new.png", "type": "image/jpeg"},
                {
                    "file_id": "both",
                    "filename": "both.png",
                    "type": "image/png",
                    "content_type": "image/webp",
                },
            ]
        )

        rows = {row.file_id: row for row in await repo.find_mimetype_rows()}

        assert rows["legacy"].type is None
        assert rows["legacy"].content_type == "image/png"
        assert rows["modern"].type == "image/jpeg"
        assert rows["modern"].content_type is None
        assert rows["both"].type == "image/png"
        assert rows["both"].content_type == "image/webp"

    async def test_rename_legacy_mimetype_moves_the_field_once(self, repo, raw_collection):
        await raw_collection.insert_one(
            {"file_id": "legacy", "filename": "old.png", "content_type": "image/png"}
        )

        assert await repo.rename_legacy_mimetype("legacy", "image/png") is True
        row = await raw_collection.find_one({"file_id": "legacy"})
        assert row["type"] == "image/png"
        assert "content_type" not in row

        # The same command again must not count as a second migration.
        assert await repo.rename_legacy_mimetype("legacy", "image/png") is False

    async def test_rename_legacy_mimetype_refuses_a_changed_row(self, repo, raw_collection):
        await raw_collection.insert_one(
            {"file_id": "legacy", "filename": "old.png", "content_type": "image/jpeg"}
        )

        assert await repo.rename_legacy_mimetype("legacy", "image/png") is False
        row = await raw_collection.find_one({"file_id": "legacy"})
        assert row["content_type"] == "image/jpeg"
        assert "type" not in row

    async def test_rename_legacy_mimetype_leaves_a_row_that_already_has_type(
        self, repo, raw_collection
    ):
        await raw_collection.insert_one(
            {
                "file_id": "modern",
                "filename": "new.png",
                "type": "image/png",
                "content_type": "image/png",
            }
        )

        assert await repo.rename_legacy_mimetype("modern", "image/png") is False
        row = await raw_collection.find_one({"file_id": "modern"})
        assert row["type"] == "image/png"
        assert row["content_type"] == "image/png"

    async def test_restore_legacy_mimetype_leaves_a_row_that_still_has_content_type(
        self, repo, raw_collection
    ):
        await raw_collection.insert_one(
            {
                "file_id": "mixed",
                "filename": "mixed.png",
                "type": "image/png",
                "content_type": "image/jpeg",
            }
        )

        assert await repo.restore_legacy_mimetype("mixed", "image/png") is False
        row = await raw_collection.find_one({"file_id": "mixed"})
        assert row["type"] == "image/png"
        assert row["content_type"] == "image/jpeg"

    async def test_restore_legacy_mimetype_reverses_the_rename(self, repo, raw_collection):
        await raw_collection.insert_one(
            {"file_id": "legacy", "filename": "old.png", "content_type": "image/png"}
        )
        await repo.rename_legacy_mimetype("legacy", "image/png")

        assert await repo.restore_legacy_mimetype("legacy", "image/png") is True
        row = await raw_collection.find_one({"file_id": "legacy"})
        assert row["content_type"] == "image/png"
        assert "type" not in row
        assert await repo.restore_legacy_mimetype("legacy", "image/png") is False

    async def test_delete_by_file_id_is_scoped(self, repo):
        fid = uuid.uuid4().hex
        await repo.create(_file(file_id=fid, user_id="u"))
        assert await repo.delete_by_file_id(fid, "other") is False
        assert await repo.delete_by_file_id(fid, "u") is True
        assert await repo.get_by_file_id(fid, "u") is None
