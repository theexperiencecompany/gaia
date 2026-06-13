"""Layer 1 — E2B SDK contract guards.

The whole sandbox layer rests on assumptions about the `e2b` SDK surface:
the pause method is `beta_pause` (not `pause`), `connect` auto-resumes, files
ops raise specific exception types, `EntryInfo` carries `modified_time`, etc.

Mocked behavior tests CANNOT catch an SDK upgrade that renames these — they
mock the very surface that changed. THESE tests run against the *installed*
SDK with zero mocks, so they break loudly the day `nx run api:sync` bumps e2b
in a way that would silently break production (exactly the original
`getattr(sbx, "pause")` → None bug).

If one of these fails after a dependency bump, the fix is in `app/services/
sandbox/` and `app/agents/tools/coding/`, NOT in this test.
"""

from __future__ import annotations

import dataclasses
import inspect

from e2b import (
    AsyncSandbox,
    CommandExitException,
    NotFoundException,
    TimeoutException,
)
from e2b.sandbox.filesystem.filesystem import EntryInfo, WriteInfo
from e2b.sandbox_async.filesystem.filesystem import Filesystem
import pytest

pytestmark = pytest.mark.unit


def test_pause_method_is_beta_pause_not_plain_pause() -> None:
    # The original prod outage: code called getattr(sbx, "pause") which was
    # None, silently disabling idle-pause. The method is `beta_pause`.
    assert hasattr(AsyncSandbox, "beta_pause"), "AsyncSandbox.beta_pause vanished"
    assert not hasattr(AsyncSandbox, "pause"), (
        "AsyncSandbox grew a plain `pause` — the lifecycle code uses `beta_pause`; "
        "reconcile before this silently diverges"
    )


def test_resume_does_not_exist_connect_is_the_resume_path() -> None:
    # `_connect_sandbox` relies on connect() auto-resuming a paused sandbox;
    # there is no separate resume().
    assert not hasattr(AsyncSandbox, "resume"), (
        "AsyncSandbox grew a `resume` — _connect_sandbox assumes connect() resumes"
    )
    assert hasattr(AsyncSandbox, "connect")


def test_connect_accepts_timeout_kwarg() -> None:
    # _connect_sandbox passes timeout= to refresh the kill timer on resume.
    params = inspect.signature(AsyncSandbox.connect).parameters
    assert "timeout" in params, "connect() lost its timeout kwarg"


def test_lifecycle_surface_present() -> None:
    for method in ("is_running", "connect", "set_timeout", "kill", "beta_pause"):
        assert hasattr(AsyncSandbox, method), f"AsyncSandbox.{method} missing"


def test_is_running_accepts_request_timeout() -> None:
    # _health_probe calls is_running(request_timeout=...).
    params = inspect.signature(AsyncSandbox.is_running).parameters
    assert "request_timeout" in params


def test_filesystem_surface_present() -> None:
    # read/write/rename/make_dir/get_info back the native-files migration.
    for method in ("read", "write", "rename", "make_dir", "get_info", "watch_dir"):
        assert hasattr(Filesystem, method), f"Filesystem.{method} missing"


def test_files_read_accepts_format_kwarg() -> None:
    # read tool uses files.read(format="bytes"/"text").
    params = inspect.signature(Filesystem.read).parameters
    assert "format" in params


def test_entryinfo_carries_modified_time_and_size() -> None:
    # atomic_write reads EntryInfo.modified_time (from rename); read fallback
    # reads .size (from get_info) for its OOM cap.
    fields = {f.name for f in dataclasses.fields(EntryInfo)}
    assert {"modified_time", "size"} <= fields, fields


def test_writeinfo_lacks_mtime_so_rename_is_required_for_mtime() -> None:
    # Documents WHY atomic_write does write→rename (not just write): WriteInfo
    # has no mtime, EntryInfo (from rename) does. If WriteInfo ever grows mtime
    # this test fails and atomic_write can be simplified to a single write.
    fields = {f.name for f in dataclasses.fields(WriteInfo)}
    assert "modified_time" not in fields


def test_command_exit_exception_carries_exit_fields() -> None:
    # bash _run_foreground + run-time tools read e.exit_code/.stdout/.stderr.
    fields = {f.name for f in dataclasses.fields(CommandExitException)}
    assert {"exit_code", "stdout", "stderr"} <= fields, fields


def test_exception_types_importable() -> None:
    # bash/read/edit import these by name from `e2b`.
    assert issubclass(NotFoundException, Exception)
    assert issubclass(TimeoutException, Exception)
    assert issubclass(CommandExitException, Exception)
