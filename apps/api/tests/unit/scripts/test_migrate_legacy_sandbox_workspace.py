"""The CLI entry gaia up runs: it migrates the --legacy-root it is given and tells the admin what stayed behind."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import settings
from app.scripts import migrate_legacy_sandbox_workspace as script
from app.services.sandbox.legacy_workspace_migration import LegacyWorkspaceReport


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "JUICEFS_HOST_MOUNT_PATH", str(tmp_path))
    return tmp_path


def _run(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    report: LegacyWorkspaceReport | None,
) -> list[Path]:
    seen: list[Path] = []

    async def migrate(legacy_root: Path) -> LegacyWorkspaceReport | None:
        seen.append(legacy_root)
        return report

    monkeypatch.setattr(script, "migrate_legacy_sandbox_workspace", migrate)
    monkeypatch.setattr("sys.argv", ["migrate_legacy_sandbox_workspace", *argv])
    script.main()
    return seen


def test_a_migration_reports_counts_leftovers_and_where_the_report_is(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = LegacyWorkspaceReport(
        migrated_sessions={"convA": "userA", "convB": "userB"},
        copied_files=7,
        skipped_existing=2,
        unresolved=["notes.md", "sessions/orphan"],
        unreadable=["sessions/convA/locked.bin"],
    )

    seen = _run(monkeypatch, ["--legacy-root", "/legacy-sandbox-workspace"], report)

    assert seen == [Path("/legacy-sandbox-workspace")]
    assert capsys.readouterr().out.splitlines() == [
        "Migrated 2 session(s), 7 file(s); skipped 2 already present.",
        "Left in the legacy volume (no provable owner): notes.md, sessions/orphan",
        "Left in the legacy volume (unreadable): sessions/convA/locked.bin",
        f"Report: {workspace / '_migrations' / 'legacy-sandbox-workspace.json'}",
    ]


def test_a_clean_migration_lists_no_leftovers(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = LegacyWorkspaceReport(migrated_sessions={"convA": "userA"}, copied_files=1)

    _run(monkeypatch, ["--legacy-root", "/legacy"], report)

    assert capsys.readouterr().out.splitlines() == [
        "Migrated 1 session(s), 1 file(s); skipped 0 already present.",
        f"Report: {workspace / '_migrations' / 'legacy-sandbox-workspace.json'}",
    ]


def test_an_already_migrated_volume_says_so_and_points_at_the_report(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, ["--legacy-root", "/legacy"], None)

    assert capsys.readouterr().out.splitlines() == [
        "Legacy sandbox workspace already migrated "
        f"(report: {workspace / '_migrations' / 'legacy-sandbox-workspace.json'})",
    ]


def test_the_legacy_root_is_required(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exited:
        _run(monkeypatch, [], None)

    assert exited.value.code == 2
    assert "--legacy-root" in capsys.readouterr().err


def test_help_describes_the_migration_from_the_module_docstring(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["migrate_legacy_sandbox_workspace", "--help"])

    with pytest.raises(SystemExit) as exited:
        script.main()

    assert exited.value.code == 0
    help_lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    assert "Copy the pre-isolation shared sandbox volume into per-user workspaces." in help_lines
    # The example keeps its own lines, so it can be copied straight into a shell.
    assert "docker compose -f docker-compose.selfhost.yml run --rm --no-deps \\" in help_lines
    assert "--legacy-root /legacy-sandbox-workspace" in help_lines
