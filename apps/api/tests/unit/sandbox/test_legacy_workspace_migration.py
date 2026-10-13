"""The shared-volume migration on a real filesystem; only the owner lookup is faked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
