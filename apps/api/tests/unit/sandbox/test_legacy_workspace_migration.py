"""The shared-volume migration on a real filesystem; only the owner lookup is faked."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.helpers import captured_wide_event

from app.config.settings import settings
from app.services.sandbox import legacy_workspace_migration as migration


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    legacy = tmp_path / "legacy"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(workspace))
    monkeypatch.setattr("app.services.storage.juicefs._is_mounted", lambda: True)
    owners = {"convA": "userA", "convB": "userB"}

    async def owners_of(ids: list[str]) -> dict[str, str]:
        return {cid: owners[cid] for cid in ids if cid in owners}

    monkeypatch.setattr(migration.conversation_repository, "owners_of", owners_of)
    return legacy, workspace


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


async def test_each_session_lands_only_in_its_owners_workspace(roots: tuple[Path, Path]) -> None:
    legacy, workspace = roots
    _write(legacy / "sessions/convA/artifacts/a.txt", "A")
    _write(legacy / "sessions/convB/scratch/b.txt", "B")

    report = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert report is not None
    assert report.migrated_sessions == {"convA": "userA", "convB": "userB"}
    assert (workspace / "users/userA/sessions/convA/artifacts/a.txt").read_text() == "A"
    assert (workspace / "users/userB/sessions/convB/scratch/b.txt").read_text() == "B"
    assert report.copied_files == 2
    assert not (workspace / "users/userA/sessions/convB").exists()
    assert not (workspace / "users/userB/sessions/convA").exists()


async def test_files_without_a_provable_owner_are_reported_and_never_copied(
    roots: tuple[Path, Path],
) -> None:
    legacy, workspace = roots
    _write(legacy / "notes.md", "whose?")
    _write(legacy / "sessions/unknownConv/x.txt", "orphan")
    _write(legacy / "sessions/stray-file", "not a session dir")

    report = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert report is not None
    assert sorted(report.unresolved) == [
        "notes.md",
        "sessions/stray-file",
        "sessions/unknownConv",
    ]
    assert report.copied_files == 0
    assert not (workspace / "users").exists() or not any((workspace / "users").rglob("*.txt"))
    assert (legacy / "notes.md").exists()


async def test_existing_workspace_files_are_never_overwritten_and_nothing_is_deleted(
    roots: tuple[Path, Path],
) -> None:
    legacy, workspace = roots
    _write(legacy / "sessions/convA/a.txt", "legacy")
    _write(workspace / "users/userA/sessions/convA/a.txt", "newer")

    report = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert report is not None
    assert report.skipped_existing == 1
    assert (workspace / "users/userA/sessions/convA/a.txt").read_text() == "newer"
    assert (legacy / "sessions/convA/a.txt").read_text() == "legacy"


async def test_symlinks_are_copied_as_links_never_followed(roots: tuple[Path, Path]) -> None:
    legacy, workspace = roots
    (legacy / "sessions/convA").mkdir(parents=True)
    (legacy / "sessions/convA/leak").symlink_to("/etc/passwd")

    await migration.migrate_legacy_sandbox_workspace(legacy)

    copied = workspace / "users/userA/sessions/convA/leak"
    assert copied.is_symlink()
    assert str(copied.readlink()) == "/etc/passwd"


async def test_a_file_swapped_for_a_symlink_mid_copy_is_never_followed(
    roots: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy, workspace = roots
    secret = tmp_path / "secret.txt"
    secret.write_text("host secret")
    decoy = tmp_path / "decoy.txt"
    decoy.write_text("regular")
    swapped = legacy / "sessions/convA/swapped"
    swapped.parent.mkdir(parents=True)
    swapped.symlink_to(secret)
    real_lstat = Path.lstat

    def lstat_before_the_swap(path: Path) -> os.stat_result:
        # The regular file the migration saw, replaced by a link before the copy.
        return real_lstat(decoy if path == swapped else path)

    monkeypatch.setattr(Path, "lstat", lstat_before_the_swap)

    await migration.migrate_legacy_sandbox_workspace(legacy)

    copied = workspace / "users/userA/sessions/convA/swapped"
    assert copied.is_symlink()
    assert copied.readlink() == secret


async def test_a_second_run_is_a_no_op_once_the_report_exists(roots: tuple[Path, Path]) -> None:
    legacy, workspace = roots
    _write(legacy / "sessions/convA/a.txt", "A")

    first = await migration.migrate_legacy_sandbox_workspace(legacy)
    (workspace / "users/userA/sessions/convA/a.txt").unlink()
    second = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert first is not None
    assert second is None
    assert not (workspace / "users/userA/sessions/convA/a.txt").exists()
    saved = json.loads((workspace / migration.MIGRATION_REPORT_RELPATH).read_text())
    assert saved["migrated_sessions"] == {"convA": "userA"}


async def test_every_existing_file_is_counted_as_skipped(roots: tuple[Path, Path]) -> None:
    legacy, workspace = roots
    for name in ("a.txt", "b.txt"):
        _write(legacy / "sessions/convA" / name, "legacy")
        _write(workspace / "users/userA/sessions/convA" / name, "newer")
    _write(legacy / "sessions/convA/nested/c.txt", "C")

    report = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert report is not None
    assert (report.skipped_existing, report.copied_files) == (2, 1)
    assert (workspace / "users/userA/sessions/convA/nested/c.txt").read_text() == "C"


async def test_a_symlinked_directory_is_copied_as_a_link_and_never_descended(
    roots: tuple[Path, Path], tmp_path: Path
) -> None:
    legacy, workspace = roots
    outside = tmp_path / "outside"
    _write(outside / "secret.txt", "not the session's")
    (legacy / "sessions/convA").mkdir(parents=True)
    (legacy / "sessions/convA/linked").symlink_to(outside, target_is_directory=True)

    report = await migration.migrate_legacy_sandbox_workspace(legacy)

    copied = workspace / "users/userA/sessions/convA/linked"
    assert copied.is_symlink()
    assert copied.readlink() == outside
    assert report is not None
    assert (report.copied_files, report.skipped_existing) == (1, 0)


async def test_special_files_are_reported_by_their_legacy_path_and_not_copied(
    roots: tuple[Path, Path],
) -> None:
    legacy, workspace = roots
    (legacy / "sessions/convA").mkdir(parents=True)
    for name in ("pipe-1", "pipe-2"):
        os.mkfifo(legacy / "sessions/convA" / name)
    _write(legacy / "sessions/convA/a.txt", "A")

    report = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert report is not None
    assert sorted(report.unresolved) == ["sessions/convA/pipe-1", "sessions/convA/pipe-2"]
    assert report.copied_files == 1
    assert not (workspace / "users/userA/sessions/convA/pipe-1").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 file")
async def test_unreadable_files_are_reported_by_their_legacy_path_and_left_behind(
    roots: tuple[Path, Path],
) -> None:
    legacy, workspace = roots
    for name in ("locked-1.bin", "locked-2.bin"):
        _write(legacy / "sessions/convA" / name, "x")
        (legacy / "sessions/convA" / name).chmod(0)
    _write(legacy / "sessions/convA/a.txt", "A")

    report = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert report is not None
    assert sorted(report.unreadable) == [
        "sessions/convA/locked-1.bin",
        "sessions/convA/locked-2.bin",
    ]
    assert report.copied_files == 1
    assert (workspace / "users/userA/sessions/convA/a.txt").read_text() == "A"


async def test_a_symlinked_sessions_root_is_never_walked(
    roots: tuple[Path, Path], tmp_path: Path
) -> None:
    legacy, workspace = roots
    _write(tmp_path / "elsewhere/convA/a.txt", "A")
    legacy.mkdir()
    (legacy / "sessions").symlink_to(tmp_path / "elsewhere", target_is_directory=True)

    report = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert report is not None
    assert report.migrated_sessions == {}
    assert not (workspace / "users/userA").exists()


async def test_a_symlinked_session_is_reported_and_never_followed(
    roots: tuple[Path, Path], tmp_path: Path
) -> None:
    legacy, workspace = roots
    _write(tmp_path / "elsewhere/a.txt", "A")
    (legacy / "sessions").mkdir(parents=True)
    (legacy / "sessions/convA").symlink_to(tmp_path / "elsewhere", target_is_directory=True)

    report = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert report is not None
    assert report.unresolved == ["sessions/convA"]
    assert report.migrated_sessions == {}
    assert not (workspace / "users/userA").exists()


async def test_an_unowned_session_does_not_stop_the_ones_after_it(
    roots: tuple[Path, Path],
) -> None:
    legacy, workspace = roots
    _write(legacy / "sessions/aaaUnknown/x.txt", "orphan")
    _write(legacy / "sessions/convA/a.txt", "A")

    report = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert report is not None
    assert report.migrated_sessions == {"convA": "userA"}
    assert (workspace / "users/userA/sessions/convA/a.txt").read_text() == "A"


async def test_the_report_lands_beside_earlier_migrations_and_on_the_wide_event(
    roots: tuple[Path, Path],
) -> None:
    legacy, workspace = roots
    (workspace / "_migrations").mkdir()
    _write(legacy / "notes.md", "whose?")
    _write(legacy / "sessions/convA/a.txt", "A")

    async with captured_wide_event() as event:
        report = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert report is not None
    saved = (workspace / migration.MIGRATION_REPORT_RELPATH).read_text()
    assert saved == report.model_dump_json(indent=2)
    assert event["legacy_workspace_migration"] == {
        "sessions": 1,
        "copied_files": 1,
        "unresolved": 1,
        "unreadable": 0,
    }


async def test_the_report_creates_its_directory_on_a_fresh_workspace(
    roots: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy, _ = roots
    fresh = tmp_path / "fresh/volume"
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(fresh))
    _write(legacy / "notes.md", "whose?")

    report = await migration.migrate_legacy_sandbox_workspace(legacy)

    assert report is not None
    assert (fresh / migration.MIGRATION_REPORT_RELPATH).is_file()
