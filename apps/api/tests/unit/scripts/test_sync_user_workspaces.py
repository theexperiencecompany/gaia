"""Unit tests for the workspace re-sync script (app.scripts.sync_user_workspaces).

Thin CLI wrapper over app.services.workspace_sync.sync_stale_user_workspaces;
the tests pin argument parsing, the delegation call, and the result report —
the script was at 0% coverage.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.scripts import sync_user_workspaces
from app.services.workspace_sync import WorkspaceSyncResult


@pytest.mark.asyncio
async def test_run_delegates_and_reports() -> None:
    result = WorkspaceSyncResult(scanned=12, synced=3, skipped=9)
    with patch.object(
        sync_user_workspaces, "sync_stale_user_workspaces", new_callable=AsyncMock
    ) as sync:
        sync.return_value = result
        args = sync_user_workspaces.argparse.Namespace(all=False, force=False)
        code = await sync_user_workspaces._run(args)

    assert code == 0
    sync.assert_awaited_once_with(active_only=True, force=False)


def test_main_parses_flags(capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["sync_user_workspaces", "--help"])
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as exc:
        sync_user_workspaces.main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "sync_user_workspaces" in out
    assert "--all       Process every user, dormant ones included.\n" in out
