"""Unit tests for the persistent `edit` coding tool (edit_tool.py).

Pins the tool's own contract: which inputs are rejected before touching a
sandbox, the exact occurrence-counting / replacement semantics, the exact
bytes and messages it reports, and the exact payloads it passes to the
sandbox, stream-event, and artifact-publish seams. Only the E2B/sandbox
boundary and the emit seams are mocked (``acquire_sandbox``,
``atomic_write``, ``safe_emit``, ``publish_artifact_write``, the
rate-limiter's Redis seams); ``_read_editable_content``, ``canonical_path``,
``get_user_id``/``get_session_id`` and ``fs_timer`` run real, so the
rejection branches (path escape, read-only uploads, missing user) and the
read-decoding logic exercise production code. ``atomic_write``,
``canonical_path`` and ``publish_artifact_write`` have their own layer-2
tests (test_atomic_write.py, test_canonical_path.py, test_artifact_publish.py);
this file only checks how edit routes through them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from e2b import NotFoundException
import pytest

from app.agents.tools.coding.edit_tool import (
    MAX_FILE_BYTES,
    MAX_PATCH_BYTES,
    _do_edit,
    _read_editable_content,
    edit,
)
from app.agents.workspace.paths import MountRole
from app.models.payment_models import PlanType
from app.services.sandbox import SandboxAcquisitionError

MODULE = "app.agents.tools.coding.edit_tool"

USER_ID = "user-1"
SESSION_ID = "conv-1"

CONFIG: dict[str, Any] = {
    "configurable": {"user_id": USER_ID, "conversation_id": SESSION_ID},
    "metadata": {"user_id": USER_ID, "conversation_id": SESSION_ID},
}

ABS_PATH = "/workspace/sessions/conv-1/scratch/app.py"
MTIME = 1_700_000_000.0


@pytest.fixture(autouse=True)
def _rate_limit_passes() -> None:
    """The @with_rate_limiting seam (not under test) — fixed to pass.

    edit is invoked with a chat-shaped config, so the wrapper's user-context
    branch runs; its Redis lookups are the seam, not edit's logic.
    """
    with (
        patch(
            "app.decorators.rate_limiting.payment_service.get_cached_plan_type",
            AsyncMock(return_value=PlanType.FREE),
        ),
        patch(
            "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
            AsyncMock(return_value={}),
        ),
    ):
        yield


def _sbx(content: bytes = b"", *, read_error: Exception | None = None) -> AsyncMock:
    """A sandbox whose native filesystem read returns fixed content or raises."""
    sbx = AsyncMock()
    if read_error is not None:
        sbx.files.read = AsyncMock(side_effect=read_error)
    else:
        sbx.files.read = AsyncMock(return_value=content)
    return sbx


def _sandbox_cm(sbx: AsyncMock) -> Callable[[str], AsyncIterator[AsyncMock]]:
    """Stand-in for acquire_sandbox: yields a fixed sandbox for the config's user."""

    @contextlib.asynccontextmanager
    async def _cm(user_id: str) -> AsyncIterator[AsyncMock]:
        assert user_id == USER_ID, "the sandbox must be acquired for the config's user"
        yield sbx

    return _cm


@contextlib.asynccontextmanager
async def _do_edit_env(
    content: bytes = b"", *, read_error: Exception | None = None
) -> AsyncIterator[tuple[AsyncMock, AsyncMock, MagicMock, AsyncMock]]:
    """Patch the emit seams for direct `_do_edit` runs; yields (sbx, atomic, emit, publish)."""
    sbx = _sbx(content, read_error=read_error)
    with (
        patch(f"{MODULE}.atomic_write", AsyncMock(return_value=MTIME)) as mock_atomic,
        patch(f"{MODULE}.safe_emit") as mock_emit,
        patch(f"{MODULE}.publish_artifact_write", AsyncMock()) as mock_publish,
    ):
        yield sbx, mock_atomic, mock_emit, mock_publish


# --- _read_editable_content -------------------------------------------------- #


async def test_read_returns_utf8_content_and_empty_error() -> None:
    content = "héllo wörld".encode()
    out = await _read_editable_content(_sbx(content), "/workspace/x.txt")
    assert out == ("héllo wörld", "")


async def test_read_accepts_bytearray_payload() -> None:
    # Native filesystem read is binary-safe: bytearray is coerced via bytes().
    sbx = _sbx()
    sbx.files.read = AsyncMock(return_value=bytearray(b"abc"))
    out = await _read_editable_content(sbx, "/workspace/x.txt")
    assert out == ("abc", "")


async def test_read_missing_file_returns_clean_error() -> None:
    sbx = _sbx(read_error=NotFoundException("no such file"))
    out = await _read_editable_content(sbx, "/workspace/x.txt")
    assert out == (None, "Error: file not found at /workspace/x.txt")


async def test_read_oversize_file_refused() -> None:
    sbx = _sbx(b"x" * (MAX_FILE_BYTES + 1))
    out = await _read_editable_content(sbx, "/workspace/big.bin")
    assert out == (None, f"Error: file exceeds {MAX_FILE_BYTES} bytes; cannot edit")


async def test_read_exact_max_size_allowed() -> None:
    content = b"x" * MAX_FILE_BYTES
    out = await _read_editable_content(_sbx(content), "/workspace/x.txt")
    assert out == (content.decode("utf-8"), "")


async def test_read_non_utf8_file_returns_clean_error() -> None:
    sbx = _sbx(b"\xff\xfe\x80\x00")
    out = await _read_editable_content(sbx, "/workspace/x.bin")
    assert out == (None, "Error: file is not UTF-8; cannot edit")


# --- _do_edit ---------------------------------------------------------------- #


async def test_do_edit_single_occurrence_replaces_with_exact_payloads() -> None:
    async with _do_edit_env(b"def foo():\n    return 1\n") as (
        sbx,
        mock_atomic,
        mock_emit,
        mock_publish,
    ):
        out = await _do_edit(
            sbx,
            user_id=USER_ID,
            abs_path=ABS_PATH,
            role=MountRole.SCRATCH,
            role_conv=SESSION_ID,
            old_string="return 1",
            new_string="return 2",
            replace_all=False,
            session_id=SESSION_ID,
        )

    assert out == "Edited /workspace/sessions/conv-1/scratch/app.py (1 occurrence replaced)"
    mock_atomic.assert_awaited_once_with(sbx, ABS_PATH, b"def foo():\n    return 2\n")
    mock_emit.assert_called_once_with(
        {
            "file_data": {
                "operation": "edit",
                "path": ABS_PATH,
                "size_bytes": 24,
                "occurrences_replaced": 1,
            }
        },
        session_id=SESSION_ID,
    )
    mock_publish.assert_awaited_once_with(
        USER_ID, MountRole.SCRATCH, SESSION_ID, ABS_PATH, "def foo():\n    return 2\n", 24, MTIME
    )


async def test_do_edit_replace_all_replaces_every_occurrence() -> None:
    async with _do_edit_env(b"a b a c a") as (sbx, mock_atomic, mock_emit, mock_publish):
        out = await _do_edit(
            sbx,
            user_id=USER_ID,
            abs_path=ABS_PATH,
            role=MountRole.SCRATCH,
            role_conv=SESSION_ID,
            old_string="a",
            new_string="X",
            replace_all=True,
            session_id=SESSION_ID,
        )

    assert out == "Edited /workspace/sessions/conv-1/scratch/app.py (3 occurrences replaced)"
    mock_atomic.assert_awaited_once_with(sbx, ABS_PATH, b"X b X c X")
    mock_emit.assert_called_once_with(
        {
            "file_data": {
                "operation": "edit",
                "path": ABS_PATH,
                "size_bytes": 9,
                "occurrences_replaced": 3,
            }
        },
        session_id=SESSION_ID,
    )
    mock_publish.assert_awaited_once_with(
        USER_ID, MountRole.SCRATCH, SESSION_ID, ABS_PATH, "X b X c X", 9, MTIME
    )


async def test_do_edit_multiple_occurrences_without_replace_all_is_ambiguous() -> None:
    async with _do_edit_env(b"a b a") as (sbx, mock_atomic, mock_emit, mock_publish):
        out = await _do_edit(
            sbx,
            user_id=USER_ID,
            abs_path=ABS_PATH,
            role=MountRole.SCRATCH,
            role_conv=SESSION_ID,
            old_string="a",
            new_string="X",
            replace_all=False,
            session_id=SESSION_ID,
        )

    assert out == (
        "Error: old_string appears 2 times. "
        "Pass replace_all=True or add surrounding context to disambiguate."
    )
    mock_atomic.assert_not_awaited()
    mock_emit.assert_not_called()
    mock_publish.assert_not_awaited()


async def test_do_edit_old_string_not_found_is_clean_error() -> None:
    async with _do_edit_env(b"hello") as (sbx, mock_atomic, mock_emit, mock_publish):
        out = await _do_edit(
            sbx,
            user_id=USER_ID,
            abs_path=ABS_PATH,
            role=MountRole.SCRATCH,
            role_conv=SESSION_ID,
            old_string="nope",
            new_string="X",
            replace_all=False,
            session_id=SESSION_ID,
        )

    assert out == "Error: old_string not found in file"
    mock_atomic.assert_not_awaited()
    mock_emit.assert_not_called()
    mock_publish.assert_not_awaited()


async def test_do_edit_read_failure_aborts_before_any_write() -> None:
    async with _do_edit_env(read_error=NotFoundException("gone")) as (
        sbx,
        mock_atomic,
        mock_emit,
        mock_publish,
    ):
        out = await _do_edit(
            sbx,
            user_id=USER_ID,
            abs_path="/workspace/missing.txt",
            role=MountRole.SCRATCH,
            role_conv=SESSION_ID,
            old_string="x",
            new_string="y",
            replace_all=False,
            session_id=SESSION_ID,
        )

    assert out == "Error: file not found at /workspace/missing.txt"
    mock_atomic.assert_not_awaited()
    mock_emit.assert_not_called()
    mock_publish.assert_not_awaited()


async def test_do_edit_size_counts_bytes_not_characters() -> None:
    # "coffee☕" is 7 characters but 9 UTF-8 bytes; the reported size must be
    # the byte count (what the artifact watcher keys on), not len(content).
    async with _do_edit_env("café".encode()) as (sbx, mock_atomic, mock_emit, mock_publish):
        out = await _do_edit(
            sbx,
            user_id=USER_ID,
            abs_path=ABS_PATH,
            role=MountRole.SCRATCH,
            role_conv=SESSION_ID,
            old_string="café",
            new_string="coffee☕",
            replace_all=False,
            session_id=SESSION_ID,
        )

    assert out == "Edited /workspace/sessions/conv-1/scratch/app.py (1 occurrence replaced)"
    mock_atomic.assert_awaited_once_with(sbx, ABS_PATH, b"coffee\xe2\x98\x95")
    mock_emit.assert_called_once_with(
        {
            "file_data": {
                "operation": "edit",
                "path": ABS_PATH,
                "size_bytes": 9,
                "occurrences_replaced": 1,
            }
        },
        session_id=SESSION_ID,
    )
    mock_publish.assert_awaited_once_with(
        USER_ID, MountRole.SCRATCH, SESSION_ID, ABS_PATH, "coffee☕", 9, MTIME
    )


async def test_do_edit_without_session_id_emits_unstamped_event() -> None:
    async with _do_edit_env(b"x = 1") as (sbx, mock_atomic, mock_emit, mock_publish):
        out = await _do_edit(
            sbx,
            user_id=USER_ID,
            abs_path="/workspace/scratch/x.py",
            role=MountRole.SCRATCH,
            role_conv=None,
            old_string="1",
            new_string="2",
            replace_all=False,
            session_id=None,
        )

    assert out == "Edited /workspace/scratch/x.py (1 occurrence replaced)"
    mock_emit.assert_called_once_with(
        {
            "file_data": {
                "operation": "edit",
                "path": "/workspace/scratch/x.py",
                "size_bytes": 5,
                "occurrences_replaced": 1,
            }
        },
        session_id=None,
    )


# --- edit tool (ainvoke) ----------------------------------------------------- #


async def test_edit_replaces_file_with_exact_payloads() -> None:
    sbx = AsyncMock()
    sbx.files.read = AsyncMock(return_value=b"def foo():\n    return 1\n")
    with (
        patch(f"{MODULE}.acquire_sandbox", _sandbox_cm(sbx)),
        patch(f"{MODULE}.atomic_write", AsyncMock(return_value=MTIME)) as mock_atomic,
        patch(f"{MODULE}.safe_emit") as mock_emit,
        patch(f"{MODULE}.publish_artifact_write", AsyncMock()) as mock_publish,
    ):
        result = await edit.ainvoke(
            {"path": "scratch/app.py", "old_string": "return 1", "new_string": "return 2"},
            config=CONFIG,
        )

    assert result == "Edited /workspace/sessions/conv-1/scratch/app.py (1 occurrence replaced)"
    mock_atomic.assert_awaited_once_with(sbx, ABS_PATH, b"def foo():\n    return 2\n")
    mock_emit.assert_called_once_with(
        {
            "file_data": {
                "operation": "edit",
                "path": ABS_PATH,
                "size_bytes": 24,
                "occurrences_replaced": 1,
            }
        },
        session_id=SESSION_ID,
    )
    mock_publish.assert_awaited_once_with(
        USER_ID, MountRole.SCRATCH, SESSION_ID, ABS_PATH, "def foo():\n    return 2\n", 24, MTIME
    )


async def test_edit_relative_path_resolves_under_session_root() -> None:
    sbx = AsyncMock()
    sbx.files.read = AsyncMock(return_value=b"v = 1\n")
    with (
        patch(f"{MODULE}.acquire_sandbox", _sandbox_cm(sbx)),
        patch(f"{MODULE}.atomic_write", AsyncMock(return_value=1.0)) as mock_atomic,
        patch(f"{MODULE}.safe_emit"),
        patch(f"{MODULE}.publish_artifact_write", AsyncMock()),
    ):
        result = await edit.ainvoke(
            {"path": "app.py", "old_string": "v = 1", "new_string": "v = 2"},
            config=CONFIG,
        )

    assert result == "Edited /workspace/sessions/conv-1/app.py (1 occurrence replaced)"
    mock_atomic.assert_awaited_once_with(sbx, "/workspace/sessions/conv-1/app.py", b"v = 2\n")


async def test_edit_empty_old_string_rejected_before_sandbox() -> None:
    with patch(f"{MODULE}.acquire_sandbox") as mock_acquire:
        result = await edit.ainvoke(
            {"path": "scratch/app.py", "old_string": "", "new_string": "x"},
            config=CONFIG,
        )

    assert result == "Error: old_string is required"
    mock_acquire.assert_not_called()


@pytest.mark.parametrize(
    ("old_string", "new_string"),
    [
        ("x" * (MAX_PATCH_BYTES + 1), "y"),
        ("x", "y" * (MAX_PATCH_BYTES + 1)),
    ],
)
async def test_edit_oversize_strings_rejected_before_sandbox(
    old_string: str, new_string: str
) -> None:
    with patch(f"{MODULE}.acquire_sandbox") as mock_acquire:
        result = await edit.ainvoke(
            {"path": "scratch/app.py", "old_string": old_string, "new_string": new_string},
            config=CONFIG,
        )

    assert result == f"Error: old_string and new_string must each be <= {MAX_PATCH_BYTES} bytes"
    mock_acquire.assert_not_called()


async def test_edit_path_escaping_workspace_is_rejected() -> None:
    with patch(f"{MODULE}.acquire_sandbox") as mock_acquire:
        result = await edit.ainvoke(
            {"path": "/etc/passwd", "old_string": "root", "new_string": "toor"},
            config=CONFIG,
        )

    assert result == "Error: path must stay inside /workspace"
    mock_acquire.assert_not_called()


async def test_edit_user_uploaded_is_read_only() -> None:
    with patch(f"{MODULE}.acquire_sandbox") as mock_acquire:
        result = await edit.ainvoke(
            {"path": "user-uploaded/report.csv", "old_string": "a", "new_string": "b"},
            config=CONFIG,
        )

    assert result == (
        "Error: user-uploaded/ is read-only. Copy the file to scratch "
        "first: cp user-uploaded/<name> scratch/"
    )
    mock_acquire.assert_not_called()


async def test_edit_missing_user_id_returns_error() -> None:
    result = await edit.ainvoke(
        {"path": "scratch/x.py", "old_string": "a", "new_string": "b"},
        config={"configurable": {}, "metadata": {}},
    )

    assert result == "Error: user_id not found in RunnableConfig"


async def test_edit_sandbox_unavailable_returns_friendly_error() -> None:
    with patch(f"{MODULE}.acquire_sandbox", side_effect=SandboxAcquisitionError("pool empty")):
        result = await edit.ainvoke(
            {"path": "scratch/x.py", "old_string": "a", "new_string": "b"},
            config=CONFIG,
        )

    assert result == "Error: sandbox unavailable (pool empty)"


async def test_edit_unexpected_sandbox_failure_returns_error_and_logs() -> None:
    sbx = _sbx(read_error=RuntimeError("disk died"))
    with (
        patch(f"{MODULE}.acquire_sandbox", _sandbox_cm(sbx)),
        patch(f"{MODULE}.log") as mock_log,
    ):
        result = await edit.ainvoke(
            {"path": "scratch/x.py", "old_string": "a", "new_string": "b"},
            config=CONFIG,
        )

    assert result == "Error editing file: disk died"
    mock_log.error.assert_called_once_with(
        "edit tool failed", error_type="RuntimeError", exc_info=True
    )


async def test_edit_artifact_publish_failure_is_converted_to_error() -> None:
    # Unlike the write tool, publish_artifact_write is inside edit's try
    # block (it runs inside _do_edit), so a raise surfaces as the generic
    # error string rather than propagating to the agent.
    sbx = AsyncMock()
    sbx.files.read = AsyncMock(return_value=b"x = 1\n")
    with (
        patch(f"{MODULE}.acquire_sandbox", _sandbox_cm(sbx)),
        patch(f"{MODULE}.atomic_write", AsyncMock(return_value=1.0)),
        patch(f"{MODULE}.safe_emit"),
        patch(
            f"{MODULE}.publish_artifact_write",
            AsyncMock(side_effect=RuntimeError("channel down")),
        ),
    ):
        result = await edit.ainvoke(
            {"path": "scratch/x.py", "old_string": "x = 1", "new_string": "x = 2"},
            config=CONFIG,
        )

    assert result == "Error editing file: channel down"
