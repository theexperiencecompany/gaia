"""Layer 3 — read tool sandbox fallback: OOM cap, binary safety, missing file.

Mocks the files boundary (get_info + read). Asserts the size cap fires, binary
content decodes without crashing, and a missing file gives a clean message.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from e2b import NotFoundException
import pytest

from app.agents.tools.coding.read_tool import MAX_SANDBOX_READ_BYTES, _read_file_sandbox

pytestmark = pytest.mark.unit


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
