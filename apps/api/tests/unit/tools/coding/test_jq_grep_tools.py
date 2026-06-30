"""jq/grep file-mining tools: behavior + security regressions.

These exercise the REAL `jq`/`grep` binaries (the whole point of the tools) and
mock only the JuiceFS boundary (`resolve_user_file`). Each test would fail if the
production logic under it were deleted — the security tests in particular encode
the exact vulnerabilities found in audit (jq module-loader file read, in-memory
DoS, shell/flag/env injection).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import sys
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.coding import _filter
from app.agents.tools.coding._filter import (
    _cap,
    _resolve_binary,
    _run,
    run_file_filter,
)
from app.agents.tools.coding.grep_tool import grep
from app.agents.tools.coding.jq_tool import _has_module_directive, jq
from app.constants.offload import FILTER_MAX_MEMORY_BYTES, MAX_FILTER_OUTPUT_CHARS
from app.services.storage import JuiceFSUnavailable

pytestmark = pytest.mark.unit

_HAS_JQ = shutil.which("jq") is not None
needs_jq = pytest.mark.skipif(not _HAS_JQ, reason="jq binary not installed")

JQ = shutil.which("jq") or "jq"
GREP = shutil.which("grep") or "grep"
CONFIG = {"configurable": {"user_id": "u1", "conversation_id": "c1"}}


def _jsonl(tmp_path: Path) -> Path:
    f = tmp_path / "inbox.jsonl"
    f.write_text('{"from":"github","subject":"hi"}\n{"from":"bob","subject":"yo"}\n')
    return f


def _mock_resolve(path: Path):
    """Patch the JuiceFS boundary so the tool runs the real binary on a temp file."""
    return patch.object(_filter, "resolve_user_file", AsyncMock(return_value=path))


# --------------------------------------------------------------------------- #
# _run — real binary behavior + exit-code handling
# --------------------------------------------------------------------------- #


@needs_jq
async def test_run_jq_filters_jsonl_per_line(tmp_path: Path) -> None:
    out = await _run(JQ, ["--", 'select(.from=="github")|.subject'], str(_jsonl(tmp_path)), (0,), "(none)", "jq")
    assert out.strip() == '"hi"'  # second line filtered out, first survives


@needs_jq
async def test_run_jq_raw_strips_quotes(tmp_path: Path) -> None:
    out = await _run(JQ, ["-r", "--", ".from"], str(_jsonl(tmp_path)), (0,), "(none)", "jq")
    assert out.split("\n")[0] == "github"  # -r => no surrounding quotes


@needs_jq
async def test_run_jq_invalid_program_is_error_not_crash(tmp_path: Path) -> None:
    out = await _run(JQ, ["--", "this is not jq"], str(_jsonl(tmp_path)), (0,), "(none)", "jq")
    assert out.startswith("jq error:")  # non-zero exit surfaced as an error string


@needs_jq
async def test_run_empty_output_uses_empty_message(tmp_path: Path) -> None:
    out = await _run(JQ, ["--", "select(.from==\"nobody\")"], str(_jsonl(tmp_path)), (0,), "(none)", "jq")
    assert out == "(none)"  # filter produced no output -> empty_message, not ""


async def test_run_grep_match_has_line_numbers(tmp_path: Path) -> None:
    out = await _run(GREP, ["-n", "-e", "github", "--"], str(_jsonl(tmp_path)), (0, 1), "(no matches)", "grep")
    assert out.strip().startswith("1:")  # -n => 1-indexed line number prefix


async def test_run_grep_no_match_is_not_an_error(tmp_path: Path) -> None:
    # grep exits 1 on no match; (0,1) are both ok, so we return empty_message.
    out = await _run(GREP, ["-n", "-e", "zzznope", "--"], str(_jsonl(tmp_path)), (0, 1), "(no matches)", "grep")
    assert out == "(no matches)"


async def test_run_grep_real_error_is_surfaced(tmp_path: Path) -> None:
    # Invalid regex => exit 2 (not in ok set) => error string.
    out = await _run(GREP, ["-n", "-e", "[", "--"], str(_jsonl(tmp_path)), (0, 1), "(no matches)", "grep")
    assert out.startswith("grep error:")


async def test_run_missing_file_is_error(tmp_path: Path) -> None:
    out = await _run(GREP, ["-n", "-e", "x", "--"], str(tmp_path / "nope.txt"), (0, 1), "(no matches)", "grep")
    assert out.startswith("grep error:")  # grep: nope.txt: No such file


# --------------------------------------------------------------------------- #
# SECURITY — these encode the audited vulnerabilities
# --------------------------------------------------------------------------- #


@needs_jq
async def test_security_no_shell_injection(tmp_path: Path) -> None:
    pwn = tmp_path / "pwned"
    out = await _run(JQ, ["--", f". ; touch {pwn}"], str(_jsonl(tmp_path)), (0,), "(none)", "jq")
    assert not pwn.exists(), "argv exec must not invoke a shell"
    assert out.startswith("jq error:")  # the metacharacters are inert jq source


@needs_jq
async def test_security_env_is_not_inherited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAIA_FAKE_SECRET", "leakme")
    out = await _run(JQ, ["-r", "--", '$ENV.GAIA_FAKE_SECRET // "ABSENT"'], str(_jsonl(tmp_path)), (0,), "(none)", "jq")
    assert "leakme" not in out
    assert "ABSENT" in out  # child env is replaced, not merged


@needs_jq
async def test_security_output_cap_truncates_and_kills(tmp_path: Path) -> None:
    # A program that streams unbounded stdout: the cap fires and kills the proc
    # (it returns instead of hanging) and the result is bounded + flagged.
    out = await _run(JQ, ["--", "range(100000000)"], str(_jsonl(tmp_path)), (0,), "(none)", "jq")
    assert "truncated" in out
    assert len(out) <= MAX_FILTER_OUTPUT_CHARS + 200


async def test_security_child_resource_limits_are_applied(tmp_path: Path) -> None:
    # Run python via the same _run path and have it report the rlimits its parent
    # (preexec_fn=_apply_child_limits) set in the child. RLIMIT_FSIZE works on
    # every platform; RLIMIT_AS is the prod (Linux) memory ceiling — macOS rejects
    # it, so only assert it there.
    code = (
        "import resource;"
        "print(resource.getrlimit(resource.RLIMIT_AS)[0],"
        "resource.getrlimit(resource.RLIMIT_FSIZE)[0])"
    )
    out = await _run(sys.executable, ["-c", code], str(tmp_path / "x"), (0,), "(none)", "py")
    soft_as, soft_fsize = out.split()
    assert int(soft_fsize) == 0  # read-only: no file writes (all platforms)
    if sys.platform == "linux":
        assert int(soft_as) == FILTER_MAX_MEMORY_BYTES  # memory ceiling (prod)


# --------------------------------------------------------------------------- #
# Execution robustness — concurrent pipe drain, encoding, truncation, limits
# --------------------------------------------------------------------------- #


@needs_jq
async def test_run_large_stderr_with_small_stdout_does_not_deadlock(tmp_path: Path) -> None:
    # jq's `stderr` builtin writes to stderr while stdout stays empty. >64KB of
    # stderr (Linux pipe buffer) must NOT deadlock the stdout drain into a bogus
    # 20s timeout — stdout/stderr are drained concurrently. The outer 10s bound is
    # the assertion: on the buggy sequential drain this never returns in time.
    f = tmp_path / "big.jsonl"
    f.write_text("".join(f'{{"n":{i}}}\n' for i in range(20000)))
    out = await asyncio.wait_for(
        _run(JQ, ["-c", "(.n|tostring|stderr)|empty"], str(f), (0,), "(none)", "jq"),
        timeout=10,
    )
    assert "timed out" not in out


@needs_jq
async def test_run_multibyte_output_truncation_no_crash(tmp_path: Path) -> None:
    # Multibyte output overrunning the byte cap may cut a char mid-sequence; the
    # decode must replace (U+FFFD), never raise, and the result must be valid text.
    f = tmp_path / "u.json"
    f.write_text('{"s":"x"}')
    out = await _run(JQ, ["-r", "--", '[range(50000)|"€"]|join("")'], str(f), (0,), "(none)", "jq")
    assert "truncated" in out
    out.encode("utf-8")  # no surrogate / UnicodeEncodeError


async def test_run_grep_binary_output_does_not_crash(tmp_path: Path) -> None:
    f = tmp_path / "bin.dat"
    f.write_bytes(b"needle\x00\xff\xfe\x80 here\n")
    out = await _run(GREP, ["-a", "-n", "-e", "needle", "--"], str(f), (0, 1), "(no matches)", "grep")
    assert "needle" in out  # invalid UTF-8 replaced, no UnicodeDecodeError


@needs_jq
async def test_run_truncation_returns_output_not_kill_error(tmp_path: Path) -> None:
    # Overrun the cap -> proc is SIGKILLed; the result is the capped output flagged
    # truncated, never the kill signal surfaced as an error.
    out = await _run(JQ, ["--", "range(100000000)"], str(_jsonl(tmp_path)), (0,), "(none)", "jq")
    assert "truncated" in out
    assert not out.startswith("jq error:")


async def test_child_fsize_zero_does_not_block_stdout_pipe(tmp_path: Path) -> None:
    # RLIMIT_FSIZE=0 forbids file writes but the stdout PIPE must stay writable,
    # else jq/grep output would be silently empty. Stay under the output cap.
    code = "import sys; sys.stdout.write('Z'*20000)"
    out = await _run(sys.executable, ["-c", code], str(tmp_path / "x"), (0,), "(none)", "py")
    assert out.count("Z") == 20000


async def test_run_file_filter_workspace_root_path_is_rejected_clearly() -> None:
    # "/workspace" canonicalizes to rel="" — must give an explicit reason, not "Error: ".
    out = await run_file_filter(
        config=CONFIG, binary="grep", args=["-n", "-e", "x", "--"], path="/workspace",
        ok_returncodes=(0, 1), empty_message="(no matches)", error_label="grep",
    )
    assert out.startswith("Error:")
    assert out.strip() != "Error:"


# --------------------------------------------------------------------------- #
# _cap / _resolve_binary
# --------------------------------------------------------------------------- #


def test_cap_passthrough_under_limit() -> None:
    assert _cap("short", truncated=False) == "short"


def test_cap_truncates_over_limit() -> None:
    out = _cap("x" * (MAX_FILTER_OUTPUT_CHARS + 50), truncated=False)
    assert "truncated" in out
    assert len(out) <= MAX_FILTER_OUTPUT_CHARS + 200


def test_cap_truncated_flag_forces_marker_even_when_short() -> None:
    out = _cap("tiny", truncated=True)
    assert "truncated" in out  # killed mid-stream => always flag it


def test_resolve_binary_unknown_raises() -> None:
    with pytest.raises(FileNotFoundError):
        _resolve_binary("definitely-not-a-real-binary-xyz")


def test_resolve_binary_known_is_absolute() -> None:
    assert _resolve_binary("grep").startswith("/")


# --------------------------------------------------------------------------- #
# run_file_filter — orchestration + error branches
# --------------------------------------------------------------------------- #


async def test_run_file_filter_bad_path_is_error() -> None:
    out = await run_file_filter(
        config=CONFIG, binary="grep", args=["-n", "-e", "x", "--"], path="",
        ok_returncodes=(0, 1), empty_message="(no matches)", error_label="grep",
    )
    assert out.startswith("Error:")  # canonical_path rejects empty path before any subprocess


async def test_run_file_filter_file_not_found_is_error() -> None:
    with patch.object(_filter, "resolve_user_file", AsyncMock(side_effect=FileNotFoundError("gmail/x.jsonl"))):
        out = await run_file_filter(
            config=CONFIG, binary="grep", args=["-n", "-e", "x", "--"], path="gmail/x.jsonl",
            ok_returncodes=(0, 1), empty_message="(no matches)", error_label="grep",
        )
    assert out == "Error: gmail/x.jsonl"


async def test_run_file_filter_surfaces_juicefs_unavailable(tmp_path: Path) -> None:
    # The mount being down must NOT be swallowed into a fake-success — it surfaces.
    with patch.object(_filter, "resolve_user_file", AsyncMock(side_effect=JuiceFSUnavailable("no mount"))):
        out = await run_file_filter(
            config=CONFIG, binary="jq", args=["--", "."], path="x.jsonl",
            ok_returncodes=(0,), empty_message="(none)", error_label="jq",
        )
    assert "Error running jq" in out
    assert "no mount" in out


@needs_jq
async def test_run_file_filter_happy_path_runs_real_jq(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await run_file_filter(
            config=CONFIG, binary="jq", args=["-r", "--", ".from"], path="inbox.jsonl",
            ok_returncodes=(0,), empty_message="(none)", error_label="jq",
        )
    assert out.split("\n")[0] == "github"  # full orchestration: resolve -> _run -> output


# --------------------------------------------------------------------------- #
# jq / grep tools — wrapper behavior (real binary via .ainvoke, mount mocked)
# --------------------------------------------------------------------------- #


@needs_jq
async def test_jq_tool_raw_flag_strips_quotes(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await jq.ainvoke({"query": ".from", "path": "inbox.jsonl", "raw": True}, config=CONFIG)
    assert out.split("\n")[0] == "github"  # raw=True => -r applied


@needs_jq
async def test_jq_tool_without_raw_keeps_quotes(tmp_path: Path) -> None:
    with _mock_resolve(_jsonl(tmp_path)):
        out = await jq.ainvoke({"query": ".from", "path": "inbox.jsonl"}, config=CONFIG)
    assert out.split("\n")[0] == '"github"'  # default => JSON-quoted


@needs_jq
async def test_jq_tool_blocks_module_import_exploit(tmp_path: Path) -> None:
    # CRITICAL regression: the module-loader file read must be refused BEFORE jq runs.
    secret_dir = tmp_path / "other"
    secret_dir.mkdir()
    (secret_dir / "s.json").write_text('{"secret":"TOPSECRET"}')
    target = tmp_path / "mine.json"
    target.write_text("{}")
    query = f'import "s" as $x {{search:"{secret_dir}"}}; $x.secret'
    with _mock_resolve(target):
        out = await jq.ainvoke({"query": query, "path": "mine.json", "raw": True}, config=CONFIG)
    assert "TOPSECRET" not in out  # the file is NOT read
    assert "not allowed" in out


@needs_jq
async def test_jq_tool_blocks_include_directive(tmp_path: Path) -> None:
    with _mock_resolve(tmp_path / "mine.json"):
        out = await jq.ainvoke({"query": 'include "evil"; .', "path": "mine.json"}, config=CONFIG)
    assert "not allowed" in out


@needs_jq
async def test_jq_tool_allows_field_named_import(tmp_path: Path) -> None:
    # The block must not false-positive on a field literally named "import".
    f = tmp_path / "d.json"
    f.write_text('{"import":"value"}')
    with _mock_resolve(f):
        out = await jq.ainvoke({"query": '.["import"]', "path": "d.json", "raw": True}, config=CONFIG)
    assert out.strip() == "value"


# Module-directive detection — fast, deterministic, no jq binary. jq treats a `#`
# line comment as inter-token whitespace, so a comment between the keyword and the
# module string is a valid directive a naive `\bimport\s*"` regex would miss.
@pytest.mark.parametrize(
    "query",
    [
        'import "m";',
        'include "m";',
        'include #c\n"m" {search:"/etc"}; .',  # comment-bypass (the audited hole)
        'import\t\t"m";',  # tabs
        'import  #a\n #b\n "m";',  # multiple comment lines
        'include"m";',  # no whitespace at all
    ],
)
def test_has_module_directive_blocks(query: str) -> None:
    assert _has_module_directive(query) is True


@pytest.mark.parametrize(
    "query",
    [
        ".from",
        '.["import"]',  # field literally named import
        'select(.subject | contains(" import "))',  # keyword inside a STRING value
        'select(.body | contains("please include \\"x\\""))',  # include inside a string
        ".importedField",  # identifier that merely starts with "import"
        '. # mentions import in a comment\n| .x',  # keyword only in a comment
    ],
)
def test_has_module_directive_allows(query: str) -> None:
    assert _has_module_directive(query) is False


@needs_jq
async def test_jq_tool_blocks_include_comment_bypass(tmp_path: Path) -> None:
    # CRITICAL regression: a `#` comment between `include` and the module string
    # must NOT smuggle a module load past the guard (verified jq loads it otherwise).
    mod = tmp_path / "mod"
    mod.mkdir()
    (mod / "conf.jq").write_text('def k: "TOPSECRET";')
    target = tmp_path / "mine.json"
    target.write_text("{}")
    query = f'include #c\n"conf" {{search:"{mod}"}}; k'
    with _mock_resolve(target):
        out = await jq.ainvoke({"query": query, "path": "mine.json", "raw": True}, config=CONFIG)
    assert "TOPSECRET" not in out  # module NOT loaded
    assert "not allowed" in out


@needs_jq
async def test_jq_tool_allows_keyword_inside_string(tmp_path: Path) -> None:
    # A query whose string DATA contains the keyword must run, not be rejected.
    f = tmp_path / "d.json"
    f.write_text('{"subject":"please import this"}')
    with _mock_resolve(f):
        out = await jq.ainvoke(
            {"query": 'select(.subject | contains("import")) | .subject', "path": "d.json", "raw": True},
            config=CONFIG,
        )
    assert "not allowed" not in out
    assert out.strip() == "please import this"


async def test_grep_tool_ignore_case_matches_other_case(tmp_path: Path) -> None:
    f = tmp_path / "log.txt"
    f.write_text("WARNING here\ninfo there\n")
    with _mock_resolve(f):
        out = await grep.ainvoke({"pattern": "warning", "path": "log.txt", "ignore_case": True}, config=CONFIG)
    assert "WARNING here" in out  # -i applied


async def test_grep_tool_pattern_dash_is_literal_not_flag(tmp_path: Path) -> None:
    # `-e <pattern>` must keep a flag-looking pattern as a literal regex.
    f = tmp_path / "log.txt"
    f.write_text("value -i is here\nplain line\n")
    with _mock_resolve(f):
        out = await grep.ainvoke({"pattern": "-i", "path": "log.txt"}, config=CONFIG)
    assert "value -i is here" in out  # matched the literal "-i", not toggled ignore-case
