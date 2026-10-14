"""Unit tests for the run_on_device executor tool.

The tool runs a shell command on a paired machine. The behavior that must hold:
it refuses a device the requesting user does not own (authz), it surfaces the
device's exit code + stdout + stderr, and it turns a transport failure into a
readable message instead of raising.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.integration_tool import _full_disk_access_hint, run_on_device
from app.services.mcp.device_exec import DeviceExecError
from tests.helpers import captured_wide_event

_MODULE = "app.agents.tools.integration_tool"
_CONFIG = {"configurable": {"user_id": "u1"}}


def _device(device_id: str, client: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=device_id, client=client)


def _result(exit_code=0, stdout="", stderr="", truncated=False) -> SimpleNamespace:
    return SimpleNamespace(exit_code=exit_code, stdout=stdout, stderr=stderr, truncated=truncated)


async def _run(device_id="dev-1", command="ls", config=_CONFIG):
    return await run_on_device.ainvoke({"device_id": device_id, "command": command}, config=config)


async def test_runs_command_and_formats_output():
    exec_mock = AsyncMock(return_value=_result(exit_code=0, stdout="a.txt\nb.txt\n"))
    list_devices = AsyncMock(return_value=[_device("dev-1")])
    with (
        patch(f"{_MODULE}.list_devices_service", list_devices),
        patch(f"{_MODULE}.run_device_command", exec_mock),
    ):
        async with captured_wide_event() as event:
            result = await _run(command="ls ~")

    assert event["tool"] == {"name": "run_on_device", "action": "exec"}
    # Ownership is checked for THIS user's id (kills the str(user_id) -> None mutants).
    list_devices.assert_awaited_once_with("u1")
    exec_mock.assert_awaited_once_with("dev-1", "ls ~")
    assert "exit code: 0" in result
    assert "a.txt\nb.txt" in result


async def test_refuses_a_device_the_user_does_not_own():
    exec_mock = AsyncMock()
    with (
        patch(f"{_MODULE}.list_devices_service", AsyncMock(return_value=[_device("dev-1")])),
        patch(f"{_MODULE}.run_device_command", exec_mock),
    ):
        result = await _run(device_id="someone-elses-device")

    # Authz is the whole point: an id the user doesn't own must never reach the
    # bridge, so the command is not dispatched at all.
    exec_mock.assert_not_awaited()
    # Exact refusal message (kills string-content mutants on the not-found path).
    assert result == (
        "No device 'someone-elses-device' is linked to your account. "
        "Call list_devices to see your paired machines and their ids."
    )


async def test_nonzero_exit_surfaces_stderr():
    with (
        patch(f"{_MODULE}.list_devices_service", AsyncMock(return_value=[_device("dev-1")])),
        patch(
            f"{_MODULE}.run_device_command",
            AsyncMock(return_value=_result(exit_code=2, stderr="no such file")),
        ),
    ):
        result = await _run(command="cat missing")

    assert "exit code: 2" in result
    assert "no such file" in result


async def test_offline_device_error_is_reported_not_raised():
    with (
        patch(f"{_MODULE}.list_devices_service", AsyncMock(return_value=[_device("dev-1")])),
        patch(
            f"{_MODULE}.run_device_command",
            AsyncMock(side_effect=DeviceExecError("Your device is offline.")),
        ),
    ):
        result = await _run()

    assert "Could not run the command" in result
    assert "offline" in result


async def test_unexpected_transport_error_is_reported_and_logged():
    # A non-DeviceExecError (a bug or transport fault) must not raise out of the
    # tool: it returns a readable message AND surfaces on the wide event with the
    # real exception type (kills the log.error field mutants + the return string).
    with (
        patch(f"{_MODULE}.list_devices_service", AsyncMock(return_value=[_device("dev-1")])),
        patch(f"{_MODULE}.run_device_command", AsyncMock(side_effect=ValueError("kaboom"))),
    ):
        async with captured_wide_event() as event:
            result = await _run()

    assert result == "Error running the command: kaboom"
    (error,) = event["errors"]
    assert "Error running command on device" in error["msg"]
    assert error["error_type"] == "ValueError"


async def test_macos_permission_denied_cli_device_points_at_the_daemon():
    with (
        patch(
            f"{_MODULE}.list_devices_service",
            AsyncMock(return_value=[_device("dev-1", client=None)]),
        ),
        patch(
            f"{_MODULE}.run_device_command",
            AsyncMock(
                return_value=_result(
                    exit_code=1, stderr="ls: /Users/x/Downloads: Operation not permitted"
                )
            ),
        ),
    ):
        result = await _run(command="ls ~/Downloads")

    # A raw errno is useless; a CLI device inherits its terminal's grant, so the
    # fix is grant-terminal + restart the daemon.
    assert "Full Disk Access" in result
    assert "gaia bridge down" in result


async def test_macos_permission_denied_desktop_device_points_at_the_app():
    with (
        patch(
            f"{_MODULE}.list_devices_service",
            AsyncMock(return_value=[_device("dev-1", client="desktop")]),
        ),
        patch(
            f"{_MODULE}.run_device_command",
            AsyncMock(
                return_value=_result(
                    exit_code=1, stderr="ls: /Users/x/Downloads: Operation not permitted"
                )
            ),
        ),
    ):
        result = await _run(command="ls ~/Downloads")

    # The desktop app IS the TCC grantee — no terminal, no daemon restart. The
    # hint must point at reopening the app, not the CLI's `gaia bridge` restart.
    assert "Full Disk Access" in result
    assert "reopen the app" in result
    assert "gaia bridge down" not in result


async def test_missing_user_id_fails_loud():
    result = await _run(config={"configurable": {}})
    assert result == "Error: User ID not found in configuration."


@pytest.mark.parametrize("stderr", ["ls: cannot access '/x': No such file", None])
async def test_unrelated_stderr_gets_no_privacy_hint(stderr):
    # The TCC hint fires ONLY on the privacy marker: any other stderr (or none)
    # must not append it, and a missing stderr must not crash the check.
    with (
        patch(f"{_MODULE}.list_devices_service", AsyncMock(return_value=[_device("dev-1")])),
        patch(
            f"{_MODULE}.run_device_command",
            AsyncMock(return_value=_result(exit_code=1, stderr=stderr)),
        ),
    ):
        result = await _run(command="ls /x")

    assert "Full Disk Access" not in result


# --- exact composed output ---------------------------------------------------
# The tool joins parts into one blob the model reads verbatim; pin exact bytes
# (header wording, interpolation, branch) rather than a substring.


async def test_successful_output_is_exactly_composed():
    with (
        patch(f"{_MODULE}.list_devices_service", AsyncMock(return_value=[_device("dev-1")])),
        patch(
            f"{_MODULE}.run_device_command",
            AsyncMock(return_value=_result(exit_code=0, stdout="hello", stderr="warn")),
        ),
    ):
        result = await _run()

    assert result == "exit code: 0\n--- stdout ---\nhello\n--- stderr ---\nwarn"
    # truncated is False here, so its line must be absent (pairs with the
    # truncated=True test to pin the branch in both directions).
    assert "(output truncated" not in result


async def test_silent_command_reports_no_output_without_section_headers():
    with (
        patch(f"{_MODULE}.list_devices_service", AsyncMock(return_value=[_device("dev-1")])),
        patch(
            f"{_MODULE}.run_device_command",
            AsyncMock(return_value=_result(exit_code=0, stdout="", stderr="")),
        ),
    ):
        result = await _run()

    assert result == "exit code: 0\n(no output)"
    assert "--- stdout ---" not in result
    assert "--- stderr ---" not in result


async def test_truncation_line_present_only_when_truncated():
    with (
        patch(f"{_MODULE}.list_devices_service", AsyncMock(return_value=[_device("dev-1")])),
        patch(
            f"{_MODULE}.run_device_command",
            AsyncMock(return_value=_result(exit_code=0, stdout="hello", truncated=True)),
        ),
    ):
        result = await _run()

    assert result == (
        "exit code: 0\n--- stdout ---\nhello\n"
        "(output truncated: command produced more than the cap)"
    )


# --- macOS TCC (Full Disk Access) hint ---------------------------------------
# Wording differs by client and is user-facing guidance, so pin both hints by
# equality and prove run_on_device appends the right one only on a privacy block.

_DESKTOP_HINT = (
    "\nmacOS blocked this path with its privacy protection (TCC); you cannot grant "
    "this yourself. This device is the GAIA desktop app. Tell the user to grant it "
    "Full Disk Access in System Settings > Privacy & Security > Full Disk Access "
    "(enable GAIA), then reopen the app. The grant carries into the commands it "
    "runs. They can open that pane with "
    '`open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"`.'
)

_CLI_HINT = (
    "\nmacOS blocked this path with its privacy protection (TCC); you cannot grant "
    "this yourself. This device is the gaia CLI. Tell the user to grant their "
    "terminal Full Disk Access in System Settings > Privacy & Security > Full Disk "
    "Access, then restart the bridge with `gaia bridge down && gaia bridge up`. "
    "They can open that pane with "
    '`open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"`.'
)


def test_full_disk_access_hint_desktop_exact_text():
    assert _full_disk_access_hint(_device("dev-1", client="desktop")) == _DESKTOP_HINT


def test_full_disk_access_hint_cli_exact_text():
    # Anything that is not the desktop app is the CLI daemon.
    assert _full_disk_access_hint(_device("dev-1", client=None)) == _CLI_HINT
    assert _full_disk_access_hint(_device("dev-1", client="cli")) == _CLI_HINT


async def test_tcc_block_appends_exact_desktop_hint():
    with (
        patch(
            f"{_MODULE}.list_devices_service",
            AsyncMock(return_value=[_device("dev-1", client="desktop")]),
        ),
        patch(
            f"{_MODULE}.run_device_command",
            AsyncMock(
                return_value=_result(
                    exit_code=1, stderr="ls: /Users/x/Downloads: Operation not permitted"
                )
            ),
        ),
    ):
        result = await _run(command="ls ~/Downloads")

    # The hint is joined as its own part, so the join adds a newline and the
    # hint itself opens with one — hence the blank line before "macOS".
    assert result == (
        "exit code: 1\n"
        "--- stderr ---\nls: /Users/x/Downloads: Operation not permitted\n" + _DESKTOP_HINT
    )


async def test_tcc_block_appends_exact_cli_hint():
    with (
        patch(
            f"{_MODULE}.list_devices_service",
            AsyncMock(return_value=[_device("dev-1", client="cli")]),
        ),
        patch(
            f"{_MODULE}.run_device_command",
            AsyncMock(
                return_value=_result(
                    exit_code=1, stderr="ls: /Users/x/Downloads: Operation not permitted"
                )
            ),
        ),
    ):
        result = await _run(command="ls ~/Downloads")

    assert result == (
        "exit code: 1\n--- stderr ---\nls: /Users/x/Downloads: Operation not permitted\n"
        + _CLI_HINT
    )


async def test_no_tcc_hint_when_stderr_is_an_ordinary_error():
    # An ordinary non-zero exit must NOT trigger the privacy guidance, or every
    # failed command would drown the model in irrelevant Full Disk Access advice.
    with (
        patch(f"{_MODULE}.list_devices_service", AsyncMock(return_value=[_device("dev-1")])),
        patch(
            f"{_MODULE}.run_device_command",
            AsyncMock(
                return_value=_result(exit_code=1, stderr="cat: missing: No such file or directory")
            ),
        ),
    ):
        result = await _run(command="cat missing")

    assert result == "exit code: 1\n--- stderr ---\ncat: missing: No such file or directory"
    assert "macOS blocked this path" not in result
