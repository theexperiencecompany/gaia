"""Layer 2 — artifact event publishing (write/edit/bash share one owner).

Mocks only publish_artifact_event (the Redis wire boundary) and asserts on
the actual event dict the production code constructs — path stripping, the
inline-body rule, and that write and bash produce IDENTICAL events for the
same logical file (the #8 unification).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.coding import _artifacts
from app.agents.tools.coding._artifacts import (
    artifact_links_note,
    publish_artifact,
    publish_artifact_write,
)
from app.agents.workspace.paths import INLINE_ARTIFACT_MAX_BYTES, MountRole

SHORT_URL = "https://heygaia.link/abcdefghijk"


@pytest.fixture(autouse=True)
def mint():
    with patch(
        "app.services.artifact_events.get_or_create_short_link",
        AsyncMock(return_value=SHORT_URL),
    ) as mint:
        yield mint


def _capture() -> tuple[AsyncMock, list]:
    """Patch publish_artifact_event; return (mock, captured_events)."""
    events: list = []
    mock = AsyncMock(side_effect=lambda uid, ev: events.append((uid, ev)))
    return mock, events


async def test_publish_artifact_builds_upsert_event_with_content_type() -> None:
    mock, events = _capture()
    with patch.object(_artifacts, "publish_artifact_event", mock):
        await publish_artifact("u1", "c1", "report.md", 12, 1_700_000_000.0, "hello")

    assert len(events) == 1
    uid, ev = events[0]
    assert uid == "u1"
    assert ev["event"] == "upsert"
    assert ev["session_id"] == "c1"
    assert ev["path"] == "report.md"
    assert ev["size_bytes"] == 12
    # NOSONAR python:S1244 — deterministic epoch passed in must round-trip verbatim
    assert ev["mtime"] == 1_700_000_000.0  # NOSONAR python:S1244
    assert ev["content_type"] == "text/markdown"
    assert ev["body"] == "hello"


async def test_publish_artifact_never_raises_into_caller() -> None:
    # Best-effort: a Redis failure must not break the tool.
    mock = AsyncMock(side_effect=RuntimeError("redis down"))
    with patch.object(_artifacts, "publish_artifact_event", mock):
        await publish_artifact("u1", "c1", "x.md", 1, 1.0, None)  # must not raise


async def test_write_path_strips_artifacts_prefix_to_relative() -> None:
    mock, events = _capture()
    with patch.object(_artifacts, "publish_artifact_event", mock):
        await publish_artifact_write(
            "u1",
            MountRole.ARTIFACTS,
            "c1",
            "/workspace/sessions/c1/artifacts/sub/deep.txt",
            "data",
            4,
            1.0,
        )
    _, ev = events[0]
    assert ev["path"] == "sub/deep.txt", "must publish path relative to artifacts/ root"


async def test_write_path_noop_for_non_artifact_roles() -> None:
    mock, events = _capture()
    with patch.object(_artifacts, "publish_artifact_event", mock):
        await publish_artifact_write(
            "u1", MountRole.SCRATCH, "c1", "/workspace/sessions/c1/scratch/x", "d", 1, 1.0
        )
    assert events == [], "scratch writes must not publish artifact events"


async def test_write_path_noop_when_conv_missing() -> None:
    mock, events = _capture()
    with patch.object(_artifacts, "publish_artifact_event", mock):
        await publish_artifact_write("u1", MountRole.ARTIFACTS, None, "/workspace/x", "d", 1, 1.0)
    assert events == []


async def test_small_textual_file_is_inlined() -> None:
    mock, events = _capture()
    with patch.object(_artifacts, "publish_artifact_event", mock):
        await publish_artifact_write(
            "u1",
            MountRole.ARTIFACTS,
            "c1",
            "/workspace/sessions/c1/artifacts/a.md",
            "tiny",
            4,
            1.0,
        )
    _, ev = events[0]
    assert ev.get("body") == "tiny"


async def test_large_textual_file_is_not_inlined() -> None:
    mock, events = _capture()
    big = INLINE_ARTIFACT_MAX_BYTES + 1
    with patch.object(_artifacts, "publish_artifact_event", mock):
        await publish_artifact_write(
            "u1",
            MountRole.ARTIFACTS,
            "c1",
            "/workspace/sessions/c1/artifacts/a.md",
            "x" * big,
            big,
            1.0,
        )
    _, ev = events[0]
    assert "body" not in ev, "files over the inline cap must not carry a body"


async def test_binary_content_type_is_not_inlined() -> None:
    mock, events = _capture()
    with patch.object(_artifacts, "publish_artifact_event", mock):
        await publish_artifact_write(
            "u1",
            MountRole.ARTIFACTS,
            "c1",
            "/workspace/sessions/c1/artifacts/img.png",
            "rawbytes",
            8,
            1.0,
        )
    _, ev = events[0]
    assert "body" not in ev, "non-inlineable content-type must not carry a body"


async def test_write_and_bash_produce_identical_event_for_same_file() -> None:
    # The #8 contract: write (via publish_artifact_write) and bash (via the core
    # publish_artifact with the same rel/size/mtime/inline) must emit byte-equal
    # events, so the dedup signature coalesces them.
    mock, events = _capture()
    with patch.object(_artifacts, "publish_artifact_event", mock):
        await publish_artifact_write(
            "u1",
            MountRole.ARTIFACTS,
            "c1",
            "/workspace/sessions/c1/artifacts/r.md",
            "hello",
            5,
            1_700_000_000.0,
        )
        await publish_artifact("u1", "c1", "r.md", 5, 1_700_000_000.0, "hello")

    assert events[0] == events[1], "write-path and bash-path events must be identical"


async def test_publish_artifact_returns_the_artifacts_link() -> None:
    """The tool hands the artifact's URL back to the agent."""
    mock, _ = _capture()
    with patch.object(_artifacts, "publish_artifact_event", mock):
        url = await publish_artifact("u1", "c1", "report.html", 12, 1.0, "<p>hi</p>")

    assert url == SHORT_URL


async def test_a_failed_publish_returns_no_link() -> None:
    mock = AsyncMock(side_effect=RuntimeError("redis down"))
    with patch.object(_artifacts, "publish_artifact_event", mock):
        assert await publish_artifact("u1", "c1", "x.md", 1, 1.0, None) is None


async def test_a_non_artifact_write_returns_no_link() -> None:
    url = await publish_artifact_write(
        "u1", MountRole.SCRATCH, "c1", "/workspace/sessions/c1/scratch/x", "d", 1, 1.0
    )
    assert url is None


def test_the_links_note_names_each_file_and_its_link() -> None:
    note = artifact_links_note({"report.html": SHORT_URL})
    assert "report.html" in note and SHORT_URL in note


def test_no_links_means_no_note() -> None:
    assert artifact_links_note({}) == ""
