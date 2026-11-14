"""The artifact card the coding tools put on their run: one owner of its shape for write, edit and bash."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

from app.agents.tools.coding import bash_tool
from app.agents.tools.coding._artifacts import (
    WrittenFile,
    publish_artifact,
    publish_artifact_write,
)
from app.agents.workspace.paths import MountRole
from app.services.artifact_events import ArtifactFileEvent

WRITER = "app.agents.tools.coding._context.current_stream_writer"
MTIME = 1_700_000_000.0


def _cards(emit: Callable[[], None]) -> list[dict[str, object]]:
    written: list[dict[str, object]] = []
    with patch(WRITER, return_value=written.append):
        emit()
    return written


def _path(card: dict[str, object]) -> object:
    return cast(dict[str, object], card["artifact_data"])["path"]


def test_publish_artifact_puts_the_file_on_the_run_as_a_card() -> None:
    cards = _cards(lambda: publish_artifact("c1", "report.md", 12, MTIME))

    assert cards == [
        {
            "artifact_data": {
                "event": "upsert",
                "session_id": "c1",
                "path": "report.md",
                "size_bytes": 12,
                "mtime": MTIME,
                "content_type": "text/markdown",
            }
        }
    ]


def test_a_write_under_artifacts_is_carded_relative_to_the_artifacts_root() -> None:
    written = WrittenFile(
        "u1", MountRole.ARTIFACTS, "c1", "/workspace/sessions/c1/artifacts/a/b.md"
    )

    (card,) = _cards(lambda: publish_artifact_write(written, 3, MTIME))

    assert _path(card) == "a/b.md"


def test_a_write_outside_artifacts_puts_no_card() -> None:
    written = WrittenFile("u1", MountRole.SCRATCH, "c1", "/workspace/sessions/c1/scratch/x.md")

    assert _cards(lambda: publish_artifact_write(written, 3, MTIME)) == []


def test_write_and_bash_put_the_same_card_for_the_same_file() -> None:
    written = WrittenFile("u1", MountRole.ARTIFACTS, "c1", "/workspace/sessions/c1/artifacts/r.md")

    by_write = _cards(lambda: publish_artifact_write(written, 5, MTIME))
    by_bash = _cards(lambda: publish_artifact("c1", "r.md", 5, MTIME))

    assert by_write == by_bash


async def test_bash_cards_every_file_find_lists_in_one_round_trip() -> None:
    sandbox = SimpleNamespace(
        commands=SimpleNamespace(
            run=AsyncMock(
                return_value=SimpleNamespace(stdout="a.md\x005\x001.5\x00b/c.txt\x0010\x00")
            )
        )
    )
    written: list[dict[str, ArtifactFileEvent]] = []
    with patch(WRITER, return_value=written.append):
        await bash_tool._publish_artifacts(sandbox, "c1")

    sandbox.commands.run.assert_awaited_once()
    # The trailing record is cut short (no mtime), so only the complete one is carded.
    assert [_path(card) for card in written] == ["a.md"]
