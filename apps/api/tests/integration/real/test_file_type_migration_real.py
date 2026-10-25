"""Real-database tests for the content_type to type files migration.

The script is data-only: rename exactly the legacy rows, refuse ambiguous
documents, stay a no-op on a second run, and reverse cleanly from its backup.
"""

from __future__ import annotations

import json

import pytest

from app.scripts import migrate_file_type_field as migration


def _legacy(file_id: str = "legacy", content_type: str = "image/png") -> dict[str, object]:
    return {"file_id": file_id, "filename": f"{file_id}.png", "content_type": content_type}


@pytest.mark.service
class TestFileTypeMigrationReal:
    async def test_plan_separates_legacy_rows_from_blockers(self, mongo_db):
        files = mongo_db["files"]
        await files.delete_many({})
        await files.insert_many(
            [
                _legacy(),
                {"file_id": "modern", "filename": "modern.png", "type": "image/png"},
                {
                    "file_id": "conflict",
                    "filename": "conflict.png",
                    "type": "image/png",
                    "content_type": "image/jpeg",
                },
                {"file_id": "empty", "filename": "empty.png"},
            ]
        )

        legacy, conflicts = await migration.plan()

        assert [(row.file_id, row.content_type) for row in legacy] == [("legacy", "image/png")]
        assert {row.file_id for row in conflicts} == {"conflict", "empty"}

    async def test_apply_renames_and_second_run_is_a_no_op(self, mongo_db, tmp_path):
        files = mongo_db["files"]
        await files.delete_many({})
        await files.insert_many([_legacy(), _legacy("legacy-2", "image/jpeg")])
        backup = tmp_path / "backup.json"

        legacy, conflicts = await migration.plan()
        assert not conflicts
        assert await migration.apply(legacy, backup) == 2

        rows = await files.find({}).to_list(length=None)
        assert {row["type"] for row in rows} == {"image/png", "image/jpeg"}
        assert all("content_type" not in row for row in rows)

        # Idempotent: the same command a second time has nothing to do.
        assert (await migration.plan()) == ([], [])
        assert await migration.apply([], backup) == 0

        recorded = json.loads(backup.read_text())
        assert {entry["file_id"] for entry in recorded["files"]} == {"legacy", "legacy-2"}

    async def test_restore_reverses_the_apply_exactly(self, mongo_db, tmp_path):
        files = mongo_db["files"]
        await files.delete_many({})
        await files.insert_many([_legacy()])
        backup = tmp_path / "backup.json"

        legacy, _ = await migration.plan()
        await migration.apply(legacy, backup)

        assert await migration.restore(backup) == 1
        document = await files.find_one({"file_id": "legacy"})
        assert document["content_type"] == "image/png"
        assert "type" not in document
