"""Exit-code, output, and path-guard behavior of the legacy mimetype migration."""

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

    @pytest.mark.parametrize("name", ["backup.tar.gz", "./backup.tar.gz", "XX.XX", "XXXX"])
    def test_accepts_any_bare_file_name(self, tmp_path, monkeypatch, name):
        monkeypatch.chdir(tmp_path)
        expected = Path(name).name
        assert migration._backup_path(Path(name)) == tmp_path / expected

    @pytest.mark.parametrize(
        "raw",
        ["/tmp/backup.json", "sub/backup.json", "../backup.json", "..", "."],
    )
    def test_rejects_anything_outside_the_working_directory(self, raw):
        with pytest.raises(SystemExit) as raised:
            migration._backup_path(Path(raw))

        assert (
            str(raised.value) == f"backup path must be a file name in the current directory: {raw}"
        )


class TestRunRestore:
    async def test_restores_from_the_named_backup(self, monkeypatch, tmp_path, capsys):
        monkeypatch.chdir(tmp_path)
        restore = AsyncMock(return_value=2)
        monkeypatch.setattr(migration, "restore", restore)

        assert await migration._run(_args(restore=Path("backup.json"))) == 0

        restore.assert_awaited_once_with(tmp_path / "backup.json")
        out = capsys.readouterr().out
        assert "restored 2 document(s) from" in out
        assert "XX" not in out


class TestRunReport:
    async def test_dry_run_reports_the_plan_and_writes_nothing(self, monkeypatch, tmp_path, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(migration, "plan", AsyncMock(return_value=([LEGACY], [])))
        apply = AsyncMock()
        monkeypatch.setattr(migration, "apply", apply)

        assert await migration._run(_args(apply=False)) == 0

        out = capsys.readouterr().out
        assert "legacy documents to rename: 1" in out
        assert "f1" in out and "image/png" in out and "a.png" in out
        assert "dry run: nothing written. Re-run with --apply." in out
        assert "XX" not in out
        apply.assert_not_awaited()
        assert not (tmp_path / "backup.json").exists()

    async def test_blocking_documents_stop_the_run(self, monkeypatch, tmp_path, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(migration, "plan", AsyncMock(return_value=([], [CONFLICT])))
        apply = AsyncMock()
        monkeypatch.setattr(migration, "apply", apply)

        assert await migration._run(_args()) == 1

        captured = capsys.readouterr()
        assert "blocking documents: 1" in captured.err
        assert "f2" in captured.err and "neither field is set" in captured.err
        assert "refusing to run" in captured.err
        assert "XX" not in captured.err
        apply.assert_not_awaited()

    async def test_nothing_to_migrate_writes_no_backup(self, monkeypatch, tmp_path, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(migration, "plan", AsyncMock(return_value=([], [])))
        apply = AsyncMock()
        monkeypatch.setattr(migration, "apply", apply)

        assert await migration._run(_args()) == 0

        out = capsys.readouterr().out
        assert "nothing to migrate." in out
        assert "XX" not in out
        apply.assert_not_awaited()
        assert not (tmp_path / "backup.json").exists()


class TestRunApplyExitCode:
    async def test_returns_zero_and_reports_the_rename(self, monkeypatch, tmp_path, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(migration, "plan", AsyncMock(side_effect=[([LEGACY], []), ([], [])]))
        monkeypatch.setattr(migration, "apply", AsyncMock(return_value=1))

        assert await migration._run(_args()) == 0

        out = capsys.readouterr().out
        assert "migrated 1 of 1 document(s); rollback at" in out
        assert "XX" not in out
        migration.apply.assert_awaited_once_with([LEGACY], tmp_path / "backup.json")

    async def test_returns_one_when_rows_remain_after_apply(self, monkeypatch, tmp_path, capsys):
        monkeypatch.chdir(tmp_path)
        second = migration.LegacyFile(file_id="f2", filename="b.png", content_type="image/png")
        monkeypatch.setattr(
            migration,
            "plan",
            AsyncMock(side_effect=[([LEGACY, second], []), ([LEGACY, second], [])]),
        )
        monkeypatch.setattr(migration, "apply", AsyncMock(return_value=0))

        assert await migration._run(_args()) == 1

        captured = capsys.readouterr()
        assert "migrated 0 of 2 document(s)" in captured.out
        assert "2 document(s) still need migration: f1, f2" in captured.err
        assert "XX" not in captured.err

    async def test_returns_one_when_a_conflict_appears_after_apply(
        self, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            migration, "plan", AsyncMock(side_effect=[([LEGACY], []), ([], [CONFLICT])])
        )
        monkeypatch.setattr(migration, "apply", AsyncMock(return_value=1))

        assert await migration._run(_args()) == 1

        err = capsys.readouterr().err
        assert "1 document(s) are in a conflicting state" in err
        assert "XX" not in err
