"""Layer 3 — read tool internals: sandbox fallback, special-read routing, and the read tool's exact argument forwarding.

Mocks the files boundary (get_info + read) and the special-read collaborators
(_read_image, system_file_body, gaia_task_files) so each branch's exact
arguments are pinned. Asserts behavior, not call counts.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from e2b import NotFoundException

from app.agents.tools.coding.read_tool import (
    MAX_SANDBOX_READ_BYTES,
    ReadPage,
    ReadTarget,
    _read_file_sandbox,
    _read_special,
    read,
)
from app.services.storage import JuiceFSUnavailable

MODULE = "app.agents.tools.coding.read_tool"
CONFIG = {"metadata": {"user_id": "user-1", "conversation_id": "conv-1"}}


def _sbx(*, info=None, info_error=None, read_bytes=b"") -> AsyncMock:
    files = AsyncMock()
    if info_error is not None:
        files.get_info = AsyncMock(side_effect=info_error)
    else:
        files.get_info = AsyncMock(return_value=info)
    files.read = AsyncMock(return_value=bytearray(read_bytes))
    sbx = AsyncMock()
    sbx.files = files
    return sbx


def _target(rel: str, session_id: str | None = "conv-1") -> ReadTarget:
    return ReadTarget(
        user_id="user-1", abs_path=f"/workspace/{rel}", rel=rel, session_id=session_id
    )


def _page(offset: int = 0, limit: int = 10) -> ReadPage:
    return ReadPage(offset=offset, limit=limit)


async def test_missing_file_returns_clean_message() -> None:
    sbx = _sbx(info_error=NotFoundException("no such file"))
    out = await _read_file_sandbox(sbx, "/workspace/x.txt", 0, 2000, None)
    assert out == "Error: file not found at /workspace/x.txt"
    sbx.files.read.assert_not_called()  # don't read after a 404


async def test_oversize_file_is_refused_before_reading() -> None:
    sbx = _sbx(info=SimpleNamespace(size=MAX_SANDBOX_READ_BYTES + 1))
    out = await _read_file_sandbox(sbx, "/workspace/big.log", 0, 2000, None)
    assert "exceeds" in out and "limit" in out
    sbx.files.read.assert_not_called(), "must not slurp a file over the cap (OOM guard)"


async def test_normal_file_is_read_and_numbered() -> None:
    sbx = _sbx(info=SimpleNamespace(size=5), read_bytes=b"a\nb\nc")
    out = await _read_file_sandbox(sbx, "/workspace/x.txt", 0, 2000, None)
    assert "a" in out and "b" in out and "c" in out
    assert out.split("\n")[0].lstrip().startswith("1")  # 1-indexed numbering


async def test_binary_content_does_not_crash() -> None:
    # Invalid UTF-8 must decode with errors="replace", not raise.
    sbx = _sbx(info=SimpleNamespace(size=3), read_bytes=b"\xff\xfe\x00")
    out = await _read_file_sandbox(sbx, "/workspace/x.bin", 0, 2000, None)
    assert isinstance(out, str) and out  # produced something, didn't crash


async def test_size_zero_falls_back_to_zero_not_unbounded() -> None:
    # getattr(info, "size", 0) or 0 — a missing/None size must be treated as 0,
    # which is under the cap, so it reads (an empty file is a valid read).
    sbx = _sbx(info=SimpleNamespace(size=0), read_bytes=b"")
    out = await _read_file_sandbox(sbx, "/workspace/empty.txt", 0, 2000, None)
    assert "exceeds" not in out


# --- _read_special routing --------------------------------------------------- #


async def test_read_special_image_forwards_exact_kwargs() -> None:
    target = _target("scratch/pic.png")
    with patch(f"{MODULE}._read_image", AsyncMock(return_value="IMAGE")) as mock_image:
        out = await _read_special(target, _page(), "image/png")

    assert out == "IMAGE"
    mock_image.assert_awaited_once_with(
        user_id="user-1",
        rel="scratch/pic.png",
        abs_path="/workspace/scratch/pic.png",
        mime_type="image/png",
        session_id="conv-1",
    )


async def test_read_special_system_file_is_served_from_memory_with_exact_args() -> None:
    target = _target("INDEX.md")
    with (
        patch(f"{MODULE}.system_file_body", return_value="BODY") as mock_body,
        patch(f"{MODULE}.user_owns_regular_file", AsyncMock(return_value=False)) as mock_owns,
        patch(f"{MODULE}._format_text_read", return_value="FORMATTED") as mock_fmt,
        patch(f"{MODULE}.gaia_task_files.resolve", AsyncMock(return_value=None)),
        patch(f"{MODULE}.log") as mock_log,
    ):
        out = await _read_special(target, _page(), None)

    assert out == "FORMATTED"
    mock_body.assert_called_once_with("INDEX.md")
    mock_owns.assert_awaited_once_with("user-1", "INDEX.md")
    mock_fmt.assert_called_once_with("/workspace/INDEX.md", "BODY", 0, 10, "conv-1")
    mock_log.set.assert_called_once_with(read_via="memory")


async def test_read_special_todo_forwards_exact_args_and_emits() -> None:
    rel = "gaia-tasks/fix-1234/canvas.md"
    target = _target(rel)
    task_ref = object()
    with (
        patch(f"{MODULE}.system_file_body", return_value=None),
        patch(
            f"{MODULE}.gaia_task_files.resolve", AsyncMock(return_value=task_ref)
        ) as mock_resolve,
        patch(f"{MODULE}.gaia_task_files.read_file", AsyncMock(return_value="BODY")) as mock_read,
        patch(f"{MODULE}._format_text_read", return_value="FORMATTED") as mock_fmt,
        patch(f"{MODULE}.log") as mock_log,
    ):
        out = await _read_special(target, _page(), None)

    assert out == "FORMATTED"
    mock_resolve.assert_awaited_once_with(rel, "user-1")
    mock_read.assert_awaited_once_with(task_ref, "user-1")
    mock_fmt.assert_called_once_with(f"/workspace/{rel}", "BODY", 0, 10, "conv-1")
    mock_log.set.assert_called_once_with(read_via="todo_document")


async def test_read_special_logs_unexpected_failure_exactly() -> None:
    target = _target("gaia-tasks/fix-1234/canvas.md")
    with (
        patch(f"{MODULE}.system_file_body", return_value=None),
        patch(
            f"{MODULE}.gaia_task_files.resolve",
            AsyncMock(side_effect=RuntimeError("mongo down")),
        ),
        patch(f"{MODULE}.log") as mock_log,
    ):
        out = await _read_special(target, _page(), None)

    assert out == "Error reading todo notes: mongo down"
    mock_log.error.assert_called_once_with(
        "read task file failed", error_type="RuntimeError", exc_info=True
    )


# --- read tool argument forwarding ------------------------------------------- #


async def test_read_forwards_exact_target_and_page_to_read_special() -> None:
    captured: dict[str, object] = {}

    async def _capture(target: ReadTarget, page: ReadPage, mime: str | None) -> str:
        captured["target"] = target
        captured["page"] = page
        captured["mime"] = mime
        return "SPECIAL"

    with patch(f"{MODULE}._read_special", _capture):
        out = await read.ainvoke(
            {"path": "scratch/pic.png", "offset": 0, "limit": 1}, config=CONFIG
        )

    assert out == "SPECIAL"
    assert captured["target"] == ReadTarget(
        user_id="user-1",
        abs_path="/workspace/sessions/conv-1/scratch/pic.png",
        rel="sessions/conv-1/scratch/pic.png",
        session_id="conv-1",
    )
    assert captured["page"] == ReadPage(offset=0, limit=1)
    assert captured["mime"] == "image/png"


async def test_read_host_path_forwards_exact_args() -> None:
    with (
        patch(f"{MODULE}._read_special", AsyncMock(return_value=None)),
        patch(f"{MODULE}.read_user_file", AsyncMock(return_value=(["a"], 1))) as mock_read,
        patch(f"{MODULE}._format_read", return_value="FORMATTED") as mock_fmt,
    ):
        out = await read.ainvoke({"path": "scratch/x.txt", "offset": 0, "limit": 10}, config=CONFIG)

    assert out == "FORMATTED"
    mock_read.assert_awaited_once_with(
        "user-1", "sessions/conv-1/scratch/x.txt", offset=0, limit=10
    )
    mock_fmt.assert_called_once_with(
        "/workspace/sessions/conv-1/scratch/x.txt", ["a"], 1, 0, 10, "conv-1"
    )


async def test_read_sandbox_fallback_forwards_exact_args() -> None:
    sbx = object()

    @contextlib.asynccontextmanager
    async def _cm(user_id: str) -> AsyncIterator[object]:
        assert user_id == "user-1"
        yield sbx

    with (
        patch(f"{MODULE}._read_special", AsyncMock(return_value=None)),
        patch(
            f"{MODULE}.read_user_file",
            AsyncMock(side_effect=JuiceFSUnavailable("no mount")),
        ),
        patch(f"{MODULE}.acquire_sandbox", _cm),
        patch(f"{MODULE}._read_file_sandbox", AsyncMock(return_value="FROM_SANDBOX")) as mock_sbx,
    ):
        out = await read.ainvoke({"path": "scratch/x.txt", "offset": 0, "limit": 10}, config=CONFIG)

    assert out == "FROM_SANDBOX"
    mock_sbx.assert_awaited_once_with(
        sbx, "/workspace/sessions/conv-1/scratch/x.txt", 0, 10, "conv-1"
    )
