"""grep tool + shared `_filter` subprocess execution: behavior + hardening.

Exercises the real subprocess path (`python` as a generic vehicle, `grep` for
grep-specifics) and mocks only the JuiceFS boundary (`resolve_user_file`). The
hardening tests encode real risks: env exfil, output-cap runaway, child rlimits,
the stderr-pipe deadlock, and flag injection.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import sys
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.coding import _filter
from app.agents.tools.coding._filter import _cap, _resolve_binary, _run, run_file_filter
from app.agents.tools.coding.grep_tool import grep
from app.constants.offload import FILTER_MAX_MEMORY_BYTES, MAX_FILTER_OUTPUT_CHARS
from app.services.storage import JuiceFSUnavailable

pytestmark = pytest.mark.unit

PY = sys.executable
GREP = shutil.which("grep") or "grep"
CONFIG = {"configurable": {"user_id": "u1", "conversation_id": "c1"}}


def _mock_resolve(path: Path):
    return patch.object(_filter, "resolve_user_file", AsyncMock(return_value=path))


async def _py(code: str, tmp_path: Path, ok=(0,), empty="(none)") -> str:
    # Run a python program via the real _run path; the target file arg is ignored.
    return await _run(PY, ["-c", code], str(tmp_path / "target"), ok, empty, "py")


# --- _run behavior + exit codes ---------------------------------------------- #


async def test_run_returns_stdout(tmp_path: Path) -> None:
    assert await _py("import sys;sys.stdout.write('hello')", tmp_path) == "hello"


async def test_run_nonzero_exit_is_error(tmp_path: Path) -> None:
    out = await _py("import sys;sys.stderr.write('boom');sys.exit(2)", tmp_path)
    assert out.startswith("py error:")


async def test_run_empty_output_uses_empty_message(tmp_path: Path) -> None:
    assert await _py("pass", tmp_path) == "(none)"


# --- grep behavior ----------------------------------------------------------- #


def _log(tmp_path: Path) -> Path:
    f = tmp_path / "run.log"
    f.write_text("INFO ok\nERROR boom\ninfo again\n")
    return f


async def test_run_grep_match_has_line_numbers(tmp_path: Path) -> None:
    out = await _run(GREP, ["-n", "-e", "ERROR", "--"], str(_log(tmp_path)), (0, 1), "(no matches)", "grep")
    assert out.strip() == "2:ERROR boom"


async def test_run_grep_no_match_is_not_error(tmp_path: Path) -> None:
    out = await _run(GREP, ["-n", "-e", "zzz", "--"], str(_log(tmp_path)), (0, 1), "(no matches)", "grep")
    assert out == "(no matches)"


async def test_run_grep_invalid_regex_is_error(tmp_path: Path) -> None:
    out = await _run(GREP, ["-n", "-e", "[", "--"], str(_log(tmp_path)), (0, 1), "(no matches)", "grep")
    assert out.startswith("grep error:")


async def test_run_grep_binary_output_does_not_crash(tmp_path: Path) -> None:
    f = tmp_path / "bin.dat"
    f.write_bytes(b"needle\x00\xff\xfe\x80 here\n")
    out = await _run(GREP, ["-a", "-n", "-e", "needle", "--"], str(f), (0, 1), "(no matches)", "grep")
    assert "needle" in out  # invalid UTF-8 replaced, no UnicodeDecodeError


# --- security / hardening ---------------------------------------------------- #


async def test_security_no_shell_metachars(tmp_path: Path) -> None:
    pwn = tmp_path / "pwned"
    # The ";touch" is argv data to python (ignored), never a shell command.
    await _run(PY, ["-c", "pass", f";touch {pwn}"], str(tmp_path / "t"), (0,), "(none)", "py")
    assert not pwn.exists()


async def test_security_env_is_not_inherited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAIA_FAKE_SECRET", "leakme")
    out = await _py("import os,sys;sys.stdout.write(os.environ.get('GAIA_FAKE_SECRET','ABSENT'))", tmp_path)
    assert "leakme" not in out
    assert out == "ABSENT"


async def test_security_output_cap_truncates(tmp_path: Path) -> None:
    out = await _py("import sys;sys.stdout.write('Z'*5_000_000)", tmp_path)
    assert "truncated" in out
    assert len(out) <= MAX_FILTER_OUTPUT_CHARS + 200


async def test_security_child_resource_limits_are_applied(tmp_path: Path) -> None:
    code = (
        "import resource;"
        "print(resource.getrlimit(resource.RLIMIT_AS)[0],"
        "resource.getrlimit(resource.RLIMIT_FSIZE)[0])"
    )
    out = await _py(code, tmp_path)
    soft_as, soft_fsize = out.split()
    assert int(soft_fsize) == 0  # read-only: no file writes (all platforms)
    if sys.platform == "linux":
        assert int(soft_as) == FILTER_MAX_MEMORY_BYTES  # prod memory ceiling


async def test_child_fsize_zero_does_not_block_stdout_pipe(tmp_path: Path) -> None:
    out = await _py("import sys;sys.stdout.write('Z'*20000)", tmp_path)
    assert out.count("Z") == 20000  # FSIZE=0 forbids file writes, not the pipe


async def test_large_stderr_small_stdout_does_not_deadlock(tmp_path: Path) -> None:
    # >64KB stderr (Linux pipe buffer) with empty stdout must not deadlock the
    # stdout drain into a spurious timeout. Outer 10s bound is the assertion.
    code = "import sys;sys.stderr.write('x'*300000)"
    out = await asyncio.wait_for(_py(code, tmp_path), timeout=10)
    assert "timed out" not in out


async def test_multibyte_output_truncation_no_crash(tmp_path: Path) -> None:
    out = await _py("import sys;sys.stdout.write('€'*60000)", tmp_path)  # € = 3 bytes
    assert "truncated" in out
    out.encode("utf-8")  # decoded result is valid text, no surrogate/exception


# --- _cap / _resolve_binary -------------------------------------------------- #


def test_cap_passthrough_under_limit() -> None:
    assert _cap("short", truncated=False) == "short"


def test_cap_truncates_over_limit() -> None:
    out = _cap("x" * (MAX_FILTER_OUTPUT_CHARS + 50), truncated=False)
    assert "truncated" in out and len(out) <= MAX_FILTER_OUTPUT_CHARS + 200


def test_cap_truncated_flag_forces_marker() -> None:
    assert "truncated" in _cap("tiny", truncated=True)


def test_resolve_binary_unknown_raises() -> None:
    with pytest.raises(FileNotFoundError):
        _resolve_binary("definitely-not-a-real-binary-xyz")


def test_resolve_binary_known_is_absolute() -> None:
    assert _resolve_binary("grep").startswith("/")


# --- run_file_filter orchestration + error branches -------------------------- #


async def test_run_file_filter_bad_path_is_error() -> None:
    out = await run_file_filter(
        config=CONFIG, binary="grep", args=["-n", "-e", "x", "--"], path="",
        ok_returncodes=(0, 1), empty_message="(no matches)", error_label="grep",
    )
    assert out.startswith("Error:")


async def test_run_file_filter_workspace_root_rejected_clearly() -> None:
    out = await run_file_filter(
        config=CONFIG, binary="grep", args=["-n", "-e", "x", "--"], path="/workspace",
        ok_returncodes=(0, 1), empty_message="(no matches)", error_label="grep",
    )
    assert out.startswith("Error:") and out.strip() != "Error:"


async def test_run_file_filter_file_not_found_is_error() -> None:
    with patch.object(_filter, "resolve_user_file", AsyncMock(side_effect=FileNotFoundError("g/x.jsonl"))):
        out = await run_file_filter(
            config=CONFIG, binary="grep", args=["-n", "-e", "x", "--"], path="g/x.jsonl",
            ok_returncodes=(0, 1), empty_message="(no matches)", error_label="grep",
        )
    assert out == "Error: g/x.jsonl"


async def test_run_file_filter_surfaces_juicefs_unavailable() -> None:
    with patch.object(_filter, "resolve_user_file", AsyncMock(side_effect=JuiceFSUnavailable("no mount"))):
        out = await run_file_filter(
            config=CONFIG, binary="grep", args=["-n", "-e", "x", "--"], path="x.jsonl",
            ok_returncodes=(0, 1), empty_message="(no matches)", error_label="grep",
        )
    assert "Error running grep" in out and "no mount" in out


async def test_run_file_filter_happy_path(tmp_path: Path) -> None:
    with _mock_resolve(_log(tmp_path)):
        out = await run_file_filter(
            config=CONFIG, binary="grep", args=["-n", "-e", "ERROR", "--"], path="run.log",
            ok_returncodes=(0, 1), empty_message="(no matches)", error_label="grep",
        )
    assert out.strip() == "2:ERROR boom"


# --- grep tool (ainvoke) ----------------------------------------------------- #


async def test_grep_tool_ignore_case(tmp_path: Path) -> None:
    f = tmp_path / "log.txt"
    f.write_text("WARNING here\ninfo there\n")
    with _mock_resolve(f):
        out = await grep.ainvoke({"pattern": "warning", "path": "log.txt", "ignore_case": True}, config=CONFIG)
    assert "WARNING here" in out


async def test_grep_tool_pattern_dash_is_literal_not_flag(tmp_path: Path) -> None:
    f = tmp_path / "log.txt"
    f.write_text("value -i is here\nplain line\n")
    with _mock_resolve(f):
        out = await grep.ainvoke({"pattern": "-i", "path": "log.txt"}, config=CONFIG)
    assert "value -i is here" in out  # -e keeps a flag-looking pattern literal
