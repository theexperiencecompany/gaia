"""The artifact card the coding tools put on their run: one owner of its shape for write, edit and bash."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Mapping
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.coding import _artifacts, bash_tool
from app.agents.tools.coding._artifacts import (
    WrittenFile,
    artifact_links_note,
    publish_artifact,
    publish_artifact_write,
)
from app.agents.tools.coding._context import sh_quote
from app.agents.workspace.paths import MountRole, detect_content_type, session_artifacts
from app.config.settings import settings
from app.models.short_link_models import ShortLink, ShortLinkTargetType, WorkspaceFileTarget
from app.services.artifact_events import ArtifactFileEvent
from app.services.links.placeholders import LINK_NOTE, link_placeholder
from app.services.storage import ArtifactInfo

WRITER = "app.agents.tools.coding._context.current_stream_writer"
MTIME = 1_700_000_000.0
LINK = ShortLink(
    slug="abcdefghijk",
    user_id="u1",
    target=WorkspaceFileTarget(
        type=ShortLinkTargetType.WORKSPACE_FILE, conversation_id="c1", path="report.html"
    ),
)


@pytest.fixture(autouse=True)
def mint() -> Iterator[AsyncMock]:
    with patch.object(_artifacts, "attach_link", AsyncMock(return_value=LINK)) as mint:
        yield mint


def _artifact(rel: str, size_bytes: int, mtime: float = MTIME) -> ArtifactInfo:
    return ArtifactInfo(
        path=rel, size_bytes=size_bytes, mtime=mtime, content_type=detect_content_type(rel)
    )


async def _cards(emit: Callable[[], Awaitable[object]]) -> list[dict[str, object]]:
    written: list[dict[str, object]] = []
    with patch(WRITER, return_value=written.append):
        await emit()
    return written


def _card(card: Mapping[str, object]) -> dict[str, object]:
    return cast(dict[str, object], card["artifact_data"])


async def test_publish_artifact_puts_the_file_on_the_run_as_a_card() -> None:
    cards = await _cards(
        lambda: publish_artifact("u1", "c1", _artifact("report.md", 12), written_this_turn=False)
    )

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


async def test_a_write_under_artifacts_is_carded_relative_to_the_artifacts_root(
    mint: AsyncMock,
) -> None:
    written = WrittenFile(
        "u1", MountRole.ARTIFACTS, "c1", "/workspace/sessions/c1/artifacts/a/b.md"
    )

    (card,) = await _cards(lambda: publish_artifact_write(written, 3, MTIME))

    assert _card(card)["path"] == "a/b.md"
    mint.assert_awaited_once_with(
        "u1",
        WorkspaceFileTarget(
            type=ShortLinkTargetType.WORKSPACE_FILE, conversation_id="c1", path="a/b.md"
        ),
    )


async def test_a_write_outside_artifacts_puts_no_card_and_returns_no_link(
    mint: AsyncMock,
) -> None:
    written = WrittenFile("u1", MountRole.SCRATCH, "c1", "/workspace/sessions/c1/scratch/x.md")

    written_cards: list[dict[str, object]] = []
    with patch(WRITER, return_value=written_cards.append):
        handed = await publish_artifact_write(written, 3, MTIME)

    assert written_cards == []
    assert handed is None
    mint.assert_not_awaited()


async def test_write_and_bash_put_the_same_card_for_the_same_file() -> None:
    written = WrittenFile("u1", MountRole.ARTIFACTS, "c1", "/workspace/sessions/c1/artifacts/r.md")

    by_write = await _cards(lambda: publish_artifact_write(written, 5, MTIME))
    by_bash = await _cards(
        lambda: publish_artifact("u1", "c1", _artifact("r.md", 5), written_this_turn=True)
    )

    assert by_write == by_bash


async def test_a_file_written_this_turn_carries_its_link(mint: AsyncMock) -> None:
    """The card carries the URL; the agent gets only the link's placeholder."""
    written: list[dict[str, object]] = []
    with patch(WRITER, return_value=written.append):
        handed = await publish_artifact(
            "u1", "c1", _artifact("report.html", 12), written_this_turn=True
        )

    assert handed == link_placeholder(LINK.target)
    assert _card(written[0])["short_url"] == f"{settings.SHORTLINK_BASE_URL}/abcdefghijk"
    mint.assert_awaited_once_with("u1", LINK.target)


async def test_a_file_not_written_this_turn_is_carded_without_a_link(mint: AsyncMock) -> None:
    """Re-listing an untouched artifact must never share it."""
    (card,) = await _cards(
        lambda: publish_artifact("u1", "c1", _artifact("old.md", 1), written_this_turn=False)
    )

    assert "short_url" not in _card(card)
    mint.assert_not_awaited()


async def test_a_file_whose_sharing_is_off_is_carded_without_a_link(mint: AsyncMock) -> None:
    mint.return_value = None
    written: list[dict[str, object]] = []
    with patch(WRITER, return_value=written.append):
        handed = await publish_artifact("u1", "c1", _artifact("x.md", 1), written_this_turn=True)

    assert handed is None
    assert "short_url" not in _card(written[0])


def test_the_links_note_names_each_file_and_its_placeholder() -> None:
    note = artifact_links_note({"report.html": "gaia-link:a", "data.csv": "gaia-link:b"})
    assert note == f"\n\n{LINK_NOTE} Links:\n- report.html: gaia-link:a\n- data.csv: gaia-link:b"


def test_no_links_means_no_note() -> None:
    assert artifact_links_note({}) == ""


def _sandbox(stdout: str) -> SimpleNamespace:
    return SimpleNamespace(
        commands=SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(stdout=stdout)))
    )


async def test_bash_cards_every_file_find_lists_in_one_round_trip() -> None:
    sandbox = _sandbox("a.md\x005\x001.5\x00b/c.txt\x0010\x00")
    written: list[dict[str, ArtifactFileEvent]] = []
    with patch(WRITER, return_value=written.append):
        await bash_tool._publish_artifacts(sandbox, "u1", "c1", changed_since=MTIME)

    sandbox.commands.run.assert_awaited_once()
    (command,) = sandbox.commands.run.await_args.args
    assert command.startswith(f"find {sh_quote(session_artifacts('c1'))} -type f ")
    # The trailing record is cut short (no mtime), so only the complete one is carded.
    assert [card["artifact_data"] for card in written] == [
        {
            "event": "upsert",
            "session_id": "c1",
            "path": "a.md",
            "size_bytes": 5,
            "mtime": 1.5,
            "content_type": "text/markdown",
        }
    ]


async def test_bash_cards_every_complete_record_when_none_is_cut_short() -> None:
    sandbox = _sandbox("a.md\x005\x001.5\x00b/c.txt\x0010\x002.5\x00")
    written: list[dict[str, ArtifactFileEvent]] = []
    with patch(WRITER, return_value=written.append):
        await bash_tool._publish_artifacts(sandbox, "u1", "c1", changed_since=MTIME)

    assert [_card(card)["path"] for card in written] == ["a.md", "b/c.txt"]


async def test_bash_links_only_the_files_its_command_wrote(mint: AsyncMock) -> None:
    """A file older than the command, past the clock-skew allowance, is re-listed, not shared."""
    sandbox = _sandbox(f"old.md\x001\x00{MTIME - 60}\x00new.html\x002\x00{MTIME + 1}\x00")
    with patch(WRITER, return_value=lambda _: None):
        links = await bash_tool._publish_artifacts(sandbox, "u1", "c1", changed_since=MTIME)

    assert links == {"new.html": link_placeholder(LINK.target)}
    mint.assert_awaited_once()
