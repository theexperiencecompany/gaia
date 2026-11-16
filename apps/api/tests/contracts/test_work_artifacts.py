"""work_artifacts against real Mongo and a real artifacts/ tree: the cards a finished work's files get."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.constants.chat import ARTIFACT_CARD
from app.db.repositories.conversations import conversation_repository
from app.services.conversation.work_artifacts import reconcile_artifacts
from app.services.storage.sessions import artifacts as artifacts_module
from shared.py.conversation_wire import ToolDataEntry
from tests.unit.services.conversation.test_conversation_log_contract import UID


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the session's artifacts/ at a temp dir and return it."""
    monkeypatch.setattr(artifacts_module, "session_base", lambda _user, _conv: tmp_path)
    (tmp_path / "artifacts").mkdir()
    return tmp_path / "artifacts"


def _write(tree: Path, name: str, body: str, mtime: float) -> None:
    (tree / name).write_text(body)
    os.utime(tree / name, (mtime, mtime))


def _shown(cards: tuple[ToolDataEntry, ...]) -> list[tuple[str, str]]:
    assert all(card["tool_name"] == ARTIFACT_CARD for card in cards)
    return [(card["data"]["event"], card["data"]["path"]) for card in cards]


def _carded(path: str) -> ToolDataEntry:
    return ToolDataEntry(tool_name=ARTIFACT_CARD, data={"event": "upsert", "path": path})


async def test_a_file_no_tool_carded_gets_a_card_once(conversation: str, tree: Path) -> None:
    _write(tree, "report.csv", "a,b", 1_000.0)

    assert _shown(await reconcile_artifacts(UID, conversation, [])) == [("upsert", "report.csv")]
    assert await reconcile_artifacts(UID, conversation, []) == ()
    [registered] = await conversation_repository.list_artifacts(conversation, user_id=UID)
    assert (registered["path"], registered["mtime"], registered["size_bytes"]) == (
        "report.csv",
        1_000.0,
        3,
    )


async def test_a_file_the_work_already_carded_is_registered_but_not_carded_twice(
    conversation: str, tree: Path
) -> None:
    _write(tree, "chart.png", "png", 1_000.0)

    assert await reconcile_artifacts(UID, conversation, [_carded("chart.png")]) == ()
    assert await reconcile_artifacts(UID, conversation, []) == ()


async def test_a_file_changed_after_its_run_is_carded_again(conversation: str, tree: Path) -> None:
    _write(tree, "notes.md", "v1", 1_000.0)
    await reconcile_artifacts(UID, conversation, [])

    _write(tree, "notes.md", "v2 longer", 2_000.0)

    assert _shown(await reconcile_artifacts(UID, conversation, [])) == [("upsert", "notes.md")]


async def test_a_deleted_file_gets_a_remove_card_and_leaves_the_registry(
    conversation: str, tree: Path
) -> None:
    _write(tree, "draft.txt", "x", 1_000.0)
    _write(tree, "final.txt", "y", 1_000.0)
    await reconcile_artifacts(UID, conversation, [])

    (tree / "draft.txt").unlink()

    assert _shown(await reconcile_artifacts(UID, conversation, [])) == [("remove", "draft.txt")]
    registry = await conversation_repository.list_artifacts(conversation, user_id=UID)
    assert [entry["path"] for entry in registry] == ["final.txt"]
