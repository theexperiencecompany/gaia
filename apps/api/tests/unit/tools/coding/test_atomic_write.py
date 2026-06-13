"""Layer 2 — atomic_write: atomicity sequence + the naive-UTC mtime fix.

Mocks only the E2B `files` boundary; the write→rename ordering, the
temp-suffix, and the mtime-tagging are real production logic.
"""

from __future__ import annotations

from datetime import datetime
import os
import time
from unittest.mock import AsyncMock
import zoneinfo

import pytest

from app.agents.tools.coding._context import atomic_write
from app.constants.sandbox import WORKSPACE_TMP_SUFFIX

pytestmark = pytest.mark.unit


def _fake_sbx(entry_mtime: datetime | None) -> tuple[AsyncMock, dict]:
    """A sandbox whose files.rename returns EntryInfo-like obj with given mtime.

    Records the write/rename calls so the test can assert the atomic sequence.
    """
    calls: dict = {"write": [], "rename": []}

    class _Info:
        modified_time = entry_mtime

    files = AsyncMock()

    async def _write(path: str, data: bytes) -> None:
        calls["write"].append((path, data))

    async def _rename(src: str, dst: str):  # noqa: ANN202
        calls["rename"].append((src, dst))
        return _Info()

    files.write.side_effect = _write
    files.rename.side_effect = _rename
    sbx = AsyncMock()
    sbx.files = files
    return sbx, calls


async def test_writes_to_temp_then_renames_into_place() -> None:
    sbx, calls = _fake_sbx(datetime(2023, 11, 14, 22, 13, 20))
    await atomic_write(sbx, "/workspace/sessions/c/artifacts/out.md", b"hello")

    tmp = f"/workspace/sessions/c/artifacts/out.md{WORKSPACE_TMP_SUFFIX}"
    assert calls["write"] == [(tmp, b"hello")], "must write to the temp path first"
    assert calls["rename"] == [(tmp, "/workspace/sessions/c/artifacts/out.md")], (
        "must rename temp → final (atomic); a direct write is not atomic"
    )


async def test_mtime_is_true_utc_epoch_regardless_of_worker_timezone() -> None:
    # E2B's EntryInfo.modified_time is a NAIVE datetime in UTC. A bare
    # .timestamp() reinterprets it in the worker's local TZ. epoch 1700000000
    # == 2023-11-14T22:13:20Z. On a non-UTC worker the buggy code returned
    # 1699980200 (off by the offset). The dedup signature must match the host
    # st_mtime / bash %T@ which are true UTC epoch.
    naive_utc = datetime(2023, 11, 14, 22, 13, 20)
    sbx, _ = _fake_sbx(naive_utc)

    original_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Asia/Kolkata"  # UTC+5:30
        if hasattr(time, "tzset"):
            time.tzset()
        mtime = await atomic_write(sbx, "/workspace/x", b"d")
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        if hasattr(time, "tzset"):
            time.tzset()

    assert mtime == 1_700_000_000.0, (
        f"mtime {mtime} is not the true UTC epoch — naive datetime was "
        f"reinterpreted in local TZ (off by the UTC offset)"
    )


@pytest.mark.parametrize(
    "tz_name",
    ["UTC", "Asia/Kolkata", "America/Los_Angeles", "Pacific/Chatham"],
)
async def test_mtime_stable_across_timezones(tz_name: str) -> None:
    # The same EntryInfo must yield the same epoch on every worker TZ.
    zoneinfo.ZoneInfo(tz_name)  # assert the tz exists on this box
    sbx, _ = _fake_sbx(datetime(2023, 11, 14, 22, 13, 20))
    original_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = tz_name
        if hasattr(time, "tzset"):
            time.tzset()
        mtime = await atomic_write(sbx, "/workspace/x", b"d")
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        if hasattr(time, "tzset"):
            time.tzset()
    assert mtime == 1_700_000_000.0


async def test_orphan_temp_is_removed_when_rename_fails() -> None:
    # A transient rename failure (sandbox blip) must not leave a `.gaia-tmp`
    # orphan littering the workspace — clean it up best-effort, then re-raise.
    removed: list[str] = []
    files = AsyncMock()
    files.write = AsyncMock()
    files.rename = AsyncMock(side_effect=RuntimeError("rename failed"))
    files.remove = AsyncMock(side_effect=lambda p: removed.append(p))
    sbx = AsyncMock()
    sbx.files = files

    with pytest.raises(RuntimeError):
        await atomic_write(sbx, "/workspace/x.txt", b"d")

    assert removed == [f"/workspace/x.txt{WORKSPACE_TMP_SUFFIX}"], (
        "the temp file must be removed when rename fails"
    )


async def test_falls_back_to_wallclock_when_entry_has_no_mtime() -> None:
    sbx, _ = _fake_sbx(None)
    before = time.time()
    mtime = await atomic_write(sbx, "/workspace/x", b"d")
    after = time.time()
    assert before <= mtime <= after, "no EntryInfo mtime → must use wall-clock now"
