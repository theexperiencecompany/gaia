"""Exit-code and path-guard behavior of the legacy mimetype migration."""

import argparse
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.scripts import migrate_file_type_field as migration

LEGACY = migration.LegacyFile(file_id="f1", filename="a.png", content_type="image/png")
CONFLICT = migration.Conflict(file_id="f2", filename="b.png", reason="neither field is set")


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {"restore": None, "apply": True, "backup": "backup.json"}
    values.update(overrides)
    return argparse.Namespace(**values)


class TestBackupPath:
    def test_accepts_a_file_name_in_the_working_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert migration._backup_path(Path("backup.json")) == tmp_path / "backup.json"

    def test_accepts_a_dot_prefixed_name(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert migration._backup_path(Path("./backup.json")) == tmp_path / "backup.json"

    @pytest.mark.parametrize(
        "raw",
        ["/tmp/backup.json", "sub/backup.json", "../backup.json", "..", "."],
    )
    def test_rejects_anything_outside_the_working_directory(self, raw):
        with pytest.raises(SystemExit):
            migration._backup_path(Path(raw))


class TestRunExitCode:
    async def test_returns_one_when_rows_remain_after_apply(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(migration, "plan", AsyncMock(return_value=([LEGACY], [])))
        monkeypatch.setattr(migration, "apply", AsyncMock(return_value=0))

        assert await migration._run(_args()) == 1

    async def test_returns_zero_when_the_end_state_is_clean(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(migration, "plan", AsyncMock(side_effect=[([LEGACY], []), ([], [])]))
        monkeypatch.setattr(migration, "apply", AsyncMock(return_value=1))

        assert await migration._run(_args()) == 0

    async def test_returns_one_when_a_conflict_appears_after_apply(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            migration, "plan", AsyncMock(side_effect=[([LEGACY], []), ([], [CONFLICT])])
        )
        monkeypatch.setattr(migration, "apply", AsyncMock(return_value=1))

        assert await migration._run(_args()) == 1

    async def test_nothing_to_migrate_writes_no_backup(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(migration, "plan", AsyncMock(return_value=([], [])))

        assert await migration._run(_args()) == 0
        assert not (tmp_path / "backup.json").exists()
