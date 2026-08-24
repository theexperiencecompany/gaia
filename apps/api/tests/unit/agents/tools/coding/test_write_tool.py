"""Unit tests for the persistent `write` coding tool (write_tool.py).

Pins the tool's own contract: which paths are rejected, the exact byte
counts/paths it reports, and the exact payloads it passes to the sandbox,
stream-event, and artifact-publish seams. Only the E2B/sandbox and event
seams are mocked (``acquire_sandbox``, ``atomic_write``, ``add_fs_bytes``,
``safe_emit``, ``publish_artifact_write``, the rate-limiter's Redis seams);
``canonical_path`` and ``fs_timer`` run real, so the rejection branches
(path escape, read-only uploads, missing user) exercise production logic.
``atomic_write``, ``canonical_path`` and ``publish_artifact_write`` have
their own layer-2 tests (test_atomic_write.py, test_canonical_path.py,
test_artifact_publish.py); this file only checks how write routes through
them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
import contextlib
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.coding.write_tool import MAX_CONTENT_BYTES, write
from app.agents.workspace.paths import MountRole
from app.constants.log_tags import LogTag
from app.models.payment_models import PlanType
from app.services.sandbox import SandboxAcquisitionError
from app.services.storage import FsOps

MODULE = "app.agents.tools.coding.write_tool"

USER_ID = "user-1"
SESSION_ID = "conv-1"

CONFIG: dict[str, Any] = {
    "configurable": {"user_id": USER_ID, "conversation_id": SESSION_ID},
    "metadata": {"user_id": USER_ID, "conversation_id": SESSION_ID},
}

SCRATCH_PATH = "/workspace/sessions/conv-1/scratch/notes.md"


@pytest.fixture(autouse=True)
def _rate_limit_passes() -> None:
    """The @with_rate_limiting seam (not under test) — fixed to pass.

    write is invoked with a chat-shaped config, so the wrapper's user-context
    branch runs; its Redis lookups are the seam, not write's logic.
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


def _sandbox_cm(sbx: AsyncMock) -> Callable[[str], AsyncIterator[AsyncMock]]:
    """Stand-in for acquire_sandbox: yields a fixed sandbox for the config's user."""

    @contextlib.asynccontextmanager
    async def _cm(user_id: str) -> AsyncIterator[AsyncMock]:
        assert user_id == USER_ID, "the sandbox must be acquired for the config's user"
        yield sbx

    return _cm


@pytest.mark.parametrize(
    ("content", "n_bytes"),
    [("hello", 5), ("héllo", 6), ("", 0)],
)
async def test_writes_session_scratch_file_with_exact_payloads(content: str, n_bytes: int) -> None:
    sbx = AsyncMock()
    mtime = 1_234.0
    with (
        patch(f"{MODULE}.acquire_sandbox", _sandbox_cm(sbx)),
        patch(f"{MODULE}.atomic_write", AsyncMock(return_value=mtime)) as mock_atomic,
        patch(f"{MODULE}.add_fs_bytes") as mock_bytes,
        patch(f"{MODULE}.safe_emit") as mock_emit,
        patch(f"{MODULE}.publish_artifact_write", AsyncMock()) as mock_publish,
    ):
        result = await write.ainvoke(
            {"path": "scratch/notes.md", "content": content}, config=CONFIG
        )

    assert result == f"Wrote {n_bytes} bytes to {SCRATCH_PATH}"
    # Byte count is UTF-8 encoded length, not character count.
    mock_atomic.assert_awaited_once_with(sbx, SCRATCH_PATH, content.encode("utf-8"))
    mock_bytes.assert_called_once_with(FsOps.TOOL_WRITE, n_bytes)
    mock_emit.assert_called_once_with(
        {
            "file_data": {
                "operation": "write",
                "path": SCRATCH_PATH,
                "size_bytes": n_bytes,
            }
        },
        session_id=SESSION_ID,
    )
    mock_publish.assert_awaited_once_with(
        USER_ID, MountRole.SCRATCH, SESSION_ID, SCRATCH_PATH, content, n_bytes, mtime
    )


async def test_writes_absolute_path_without_session_conv() -> None:
    abs_path = "/workspace/notes.md"
    sbx = AsyncMock()
    mtime = 42.0
    with (
        patch(f"{MODULE}.acquire_sandbox", _sandbox_cm(sbx)),
        patch(f"{MODULE}.atomic_write", AsyncMock(return_value=mtime)),
        patch(f"{MODULE}.add_fs_bytes"),
        patch(f"{MODULE}.safe_emit"),
        patch(f"{MODULE}.publish_artifact_write", AsyncMock()) as mock_publish,
    ):
        result = await write.ainvoke({"path": abs_path, "content": "hi"}, config=CONFIG)

    assert result == "Wrote 2 bytes to /workspace/notes.md"
    mock_publish.assert_awaited_once_with(
        USER_ID, MountRole.UNKNOWN, None, abs_path, "hi", 2, mtime
    )


async def test_content_at_max_bytes_boundary_is_written() -> None:
    at_limit = "a" * MAX_CONTENT_BYTES
    with (
        patch(f"{MODULE}.acquire_sandbox", _sandbox_cm(AsyncMock())),
        patch(f"{MODULE}.atomic_write", AsyncMock(return_value=1.0)),
        patch(f"{MODULE}.add_fs_bytes") as mock_bytes,
        patch(f"{MODULE}.safe_emit"),
        patch(f"{MODULE}.publish_artifact_write", AsyncMock()),
    ):
        result = await write.ainvoke(
            {"path": "scratch/big.txt", "content": at_limit}, config=CONFIG
        )

    assert (
        result == f"Wrote {MAX_CONTENT_BYTES} bytes to /workspace/sessions/conv-1/scratch/big.txt"
    )
    mock_bytes.assert_called_once_with(FsOps.TOOL_WRITE, MAX_CONTENT_BYTES)


async def test_content_over_max_bytes_is_rejected_before_sandbox() -> None:
    oversized = "a" * (MAX_CONTENT_BYTES + 1)
    with patch(f"{MODULE}.acquire_sandbox") as mock_acquire:
        result = await write.ainvoke(
            {"path": "scratch/big.txt", "content": oversized}, config=CONFIG
        )

    assert result == f"Error: content exceeds {MAX_CONTENT_BYTES} bytes"
    mock_acquire.assert_not_called()


async def test_user_uploaded_is_read_only() -> None:
    with patch(f"{MODULE}.acquire_sandbox") as mock_acquire:
        result = await write.ainvoke(
            {"path": "user-uploaded/report.pdf", "content": "x"}, config=CONFIG
        )

    assert result == (
        "Error: user-uploaded/ is read-only. Copy the file to scratch "
        "first: cp user-uploaded/<name> scratch/"
    )
    mock_acquire.assert_not_called()


async def test_missing_user_id_returns_error() -> None:
    result = await write.ainvoke(
        {"path": "scratch/x.py", "content": "x"},
        config={"configurable": {}, "metadata": {}},
    )

    assert result == "Error: user_id not found in RunnableConfig"


async def test_path_escaping_workspace_is_rejected() -> None:
    with patch(f"{MODULE}.acquire_sandbox") as mock_acquire:
        result = await write.ainvoke({"path": "/etc/passwd", "content": "x"}, config=CONFIG)

    assert result == "Error: path must stay inside /workspace"
    mock_acquire.assert_not_called()


async def test_sandbox_unavailable_returns_friendly_error() -> None:
    with patch(f"{MODULE}.acquire_sandbox", side_effect=SandboxAcquisitionError("pool empty")):
        result = await write.ainvoke({"path": "scratch/x.py", "content": "x"}, config=CONFIG)

    assert result == "Error: sandbox unavailable — pool empty"


async def test_write_failure_returns_error_and_logs() -> None:
    with (
        patch(f"{MODULE}.acquire_sandbox", _sandbox_cm(AsyncMock())),
        patch(f"{MODULE}.atomic_write", AsyncMock(side_effect=RuntimeError("disk full"))),
        patch(f"{MODULE}.log") as mock_log,
    ):
        result = await write.ainvoke({"path": "scratch/x.py", "content": "x"}, config=CONFIG)

    assert result == "Error writing file: disk full"
    mock_log.error.assert_called_once_with(
        f"{LogTag.SANDBOX} write tool failed", error_type="RuntimeError", exc_info=True
    )


async def test_artifact_publish_failure_propagates() -> None:
    # publish_artifact_write is deliberately outside the try block: the real
    # implementation never raises (suppress inside publish_artifact), so a
    # raise here must surface to the agent, not be converted to an error string.
    with (
        patch(f"{MODULE}.acquire_sandbox", _sandbox_cm(AsyncMock())),
        patch(f"{MODULE}.atomic_write", AsyncMock(return_value=1.0)),
        patch(f"{MODULE}.safe_emit"),
        patch(
            f"{MODULE}.publish_artifact_write",
            AsyncMock(side_effect=RuntimeError("channel down")),
        ),
    ):
        with pytest.raises(RuntimeError, match="channel down"):
            await write.ainvoke({"path": "scratch/x.py", "content": "x"}, config=CONFIG)
