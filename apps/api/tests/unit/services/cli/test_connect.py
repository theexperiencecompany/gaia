"""Unit tests for the CLI connect state machine.

The machine keeps no state of its own — every call re-reads the sandbox — so the
tests drive it by varying only the observed :class:`CliState` and asserting the
phase and the single action taken. That is exactly the contract the client polls
against.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.cli_integrations import LOGIN_TIMEOUT_SECONDS
from app.models.cli_config import CliAuthSpec, CliConfig
from app.services.cli import connect
from app.services.cli.runtime import CliResult, CliState

USER = "user-1"
INTEGRATION = "stripe_link"

DEVICE = CliConfig(
    command="link-cli",
    install_command="npm install x",
    auth=CliAuthSpec(
        kind="device",
        login_command="link-cli auth login",
        verify_command="link-cli auth status",
    ),
)
TOKEN = CliConfig(
    command="gh",
    install_command="curl x",
    auth=CliAuthSpec(
        kind="token",
        verify_command="gh auth status",
        token_env="GH_TOKEN",
        token_label="GitHub token",
        token_help_url="https://github.test/tokens",
    ),
)
NO_AUTH = CliConfig(
    command="fmt",
    install_command="npm i fmt",
    auth=CliAuthSpec(kind="none", verify_command="fmt -v"),
)


def state(**overrides: object) -> CliState:
    base: dict[str, object] = {
        "installed": True,
        "authenticated": False,
        "login_running": False,
        "login_age_seconds": None,
        "login_output": "",
        "install_error": "",
    }
    base.update(overrides)
    return CliState(**base)  # type: ignore[arg-type]  # kwargs dict widens to object; the model validates the real types


@pytest.fixture
def env():
    """Patch everything outside this module; expose the doubles for assertions."""
    sandbox = MagicMock()

    @contextlib.asynccontextmanager
    async def _acquire(_user_id: str):
        yield sandbox

    with (
        patch.object(connect, "acquire_sandbox", _acquire),
        patch.object(connect, "add_user_integration", AsyncMock()) as add_user,
        patch.object(
            connect.user_integration_repository, "exists", AsyncMock(return_value=False)
        ) as exists,
        patch.object(connect, "update_user_integration_status", AsyncMock()) as set_status,
        patch.object(connect.runtime, "probe_state", AsyncMock()) as probe,
        patch.object(connect.runtime, "start_login", AsyncMock()) as start_login,
        patch.object(connect.runtime, "write_token", AsyncMock()) as write_token,
    ):
        start_login.return_value = CliResult(exit_code=0, stdout="", stderr="")
        write_token.return_value = CliResult(exit_code=0, stdout="", stderr="")
        yield MagicMock(
            sandbox=sandbox,
            add_user=add_user,
            exists=exists,
            set_status=set_status,
            probe=probe,
            start_login=start_login,
            write_token=write_token,
        )


class TestAlreadyAuthenticated:
    async def test_reports_connected_and_records_it(self, env):
        env.probe.return_value = state(authenticated=True)
        outcome = await connect.advance(USER, INTEGRATION, DEVICE)
        assert outcome.phase == "connected"
        assert outcome.is_terminal
        env.set_status.assert_awaited_once_with(USER, INTEGRATION, "connected")

    async def test_does_not_start_another_login(self, env):
        env.probe.return_value = state(authenticated=True)
        await connect.advance(USER, INTEGRATION, DEVICE)
        env.start_login.assert_not_awaited()

    async def test_attaches_the_integration_before_transitioning(self, env):
        env.probe.return_value = state(authenticated=True)
        await connect.advance(USER, INTEGRATION, DEVICE)
        env.add_user.assert_awaited_once()


class TestIdempotency:
    """advance() IS the client's poll loop, so every call must be safe."""

    async def test_does_not_re_add_an_integration_the_user_already_has(self, env):
        # add_user_integration raises on a duplicate, so an unguarded add turns
        # the second poll into "already added to workspace" and the connect
        # dialog dies one tick after it opens.
        env.exists.return_value = True
        env.probe.return_value = state(login_running=True, login_age_seconds=3, login_output="go")
        outcome = await connect.advance(USER, INTEGRATION, DEVICE)
        env.add_user.assert_not_awaited()
        assert outcome.phase == "awaiting_approval"

    async def test_repeated_polls_stay_on_the_same_phase(self, env):
        env.exists.return_value = True
        env.probe.return_value = state(login_running=True, login_age_seconds=3, login_output="go")
        phases = [(await connect.advance(USER, INTEGRATION, DEVICE)).phase for _ in range(3)]
        assert phases == ["awaiting_approval"] * 3
        env.start_login.assert_not_awaited()


class TestInstallFailure:
    async def test_surfaces_the_install_error_to_the_user(self, env):
        env.probe.return_value = state(installed=False, install_error="npm ERR! 404")
        outcome = await connect.advance(USER, INTEGRATION, DEVICE)
        assert outcome.phase == "failed"
        assert "link-cli" in (outcome.message or "")
        assert "404" in (outcome.instructions or "")

    async def test_never_marks_the_integration_connected(self, env):
        env.probe.return_value = state(installed=False, install_error="boom")
        await connect.advance(USER, INTEGRATION, DEVICE)
        env.set_status.assert_not_awaited()


class TestDeviceLogin:
    async def test_starts_a_login_when_none_has_run(self, env):
        env.probe.return_value = state()
        outcome = await connect.advance(USER, INTEGRATION, DEVICE)
        assert outcome.phase == "awaiting_approval"
        env.start_login.assert_awaited_once()

    async def test_relays_the_cli_output_verbatim_while_polling(self, env):
        instructions = 'verification_url: "https://link.test/d?code=abc"\nphrase: abc'
        env.probe.return_value = state(
            login_running=True, login_age_seconds=5, login_output=instructions
        )
        outcome = await connect.advance(USER, INTEGRATION, DEVICE)
        assert outcome.phase == "awaiting_approval"
        assert outcome.instructions == instructions

    async def test_does_not_restart_a_running_login(self, env):
        env.probe.return_value = state(
            login_running=True, login_age_seconds=5, login_output="go here"
        )
        await connect.advance(USER, INTEGRATION, DEVICE)
        env.start_login.assert_not_awaited()

    async def test_keeps_showing_a_finished_login_that_already_printed_its_code(self, env):
        # Some CLIs print the code and exit, leaving the exchange to the next
        # status call. Restarting there would invalidate the code the user is
        # currently typing.
        env.probe.return_value = state(
            login_running=False, login_age_seconds=30, login_output="enter code ABC"
        )
        outcome = await connect.advance(USER, INTEGRATION, DEVICE)
        assert outcome.phase == "awaiting_approval"
        assert outcome.instructions == "enter code ABC"
        env.start_login.assert_not_awaited()

    async def test_waits_rather_than_restarting_when_a_fresh_login_has_not_printed_yet(self, env):
        env.probe.return_value = state(login_running=False, login_age_seconds=2, login_output="")
        outcome = await connect.advance(USER, INTEGRATION, DEVICE)
        assert outcome.phase == "awaiting_approval"
        env.start_login.assert_not_awaited()

    async def test_restarts_once_the_previous_attempt_is_stale(self, env):
        env.probe.return_value = state(
            login_running=False,
            login_age_seconds=LOGIN_TIMEOUT_SECONDS + 1,
            login_output="expired code",
        )
        await connect.advance(USER, INTEGRATION, DEVICE)
        env.start_login.assert_awaited_once()

    async def test_reports_failure_when_the_login_cannot_be_started(self, env):
        env.probe.return_value = state()
        env.start_login.return_value = CliResult(exit_code=1, stdout="", stderr="no such command")
        outcome = await connect.advance(USER, INTEGRATION, DEVICE)
        assert outcome.phase == "failed"
        assert "no such command" in (outcome.instructions or "")


class TestTokenAuth:
    async def test_asks_for_the_token_with_the_configured_prompt(self, env):
        env.probe.return_value = state()
        outcome = await connect.advance(USER, "gh", TOKEN)
        assert outcome.phase == "needs_token"
        assert outcome.token_label == "GitHub token"
        assert outcome.token_help_url == "https://github.test/tokens"

    async def test_writes_a_supplied_token_before_re_probing(self, env):
        env.probe.return_value = state(authenticated=True)
        outcome = await connect.advance(USER, "gh", TOKEN, token="ghp_x")
        env.write_token.assert_awaited_once()
        assert env.write_token.await_args.args[3] == "ghp_x"
        assert outcome.phase == "connected"

    async def test_reports_a_rejected_token_instead_of_asking_again(self, env):
        # Re-prompting on a bad token is an infinite loop from the user's side:
        # they paste the same value and see the same dialog with no explanation.
        env.probe.return_value = state(authenticated=False)
        outcome = await connect.advance(USER, "gh", TOKEN, token="bad")
        assert outcome.phase == "failed"
        assert "did not accept" in (outcome.message or "")

    async def test_surfaces_a_write_failure(self, env):
        env.write_token.return_value = CliResult(exit_code=1, stdout="", stderr="invalid token")
        outcome = await connect.advance(USER, "gh", TOKEN, token="bad")
        assert outcome.phase == "failed"
        assert "invalid token" in (outcome.instructions or "")
        env.probe.assert_not_awaited()

    async def test_never_starts_a_device_login(self, env):
        env.probe.return_value = state()
        await connect.advance(USER, "gh", TOKEN)
        env.start_login.assert_not_awaited()


class TestNoAuth:
    async def test_connects_when_the_cli_reports_ready(self, env):
        env.probe.return_value = state(authenticated=True)
        assert (await connect.advance(USER, "fmt", NO_AUTH)).phase == "connected"

    async def test_fails_when_the_cli_does_not_report_ready(self, env):
        # Nothing to log into, so a failing verify means a broken install, not a
        # missing credential — asking the user for one would be misleading.
        env.probe.return_value = state(authenticated=False)
        outcome = await connect.advance(USER, "fmt", NO_AUTH)
        assert outcome.phase == "failed"
        assert "not reporting as ready" in (outcome.message or "")


class TestReviewFixes:
    """Behaviours added after review; each one had a concrete failure."""

    async def test_a_token_sent_to_a_device_login_is_ignored_not_fatal(self, env):
        # The connect endpoint is public and carries bearer_token for the MCP
        # transport, so a token can arrive for a device CLI. Writing it would
        # raise on the missing token_env and surface as an opaque error.
        env.probe.return_value = state(login_running=True, login_age_seconds=2, login_output="go")
        outcome = await connect.advance(USER, INTEGRATION, DEVICE, token="stray")
        env.write_token.assert_not_awaited()
        assert outcome.phase == "awaiting_approval"

    async def test_a_failed_login_start_does_not_leak_sandbox_paths(self, env):
        env.probe.return_value = state()
        env.start_login.return_value = CliResult(
            exit_code=1, stdout="", stderr="cannot write /workspace/.gaia/apps/x/login.log"
        )
        outcome = await connect.advance(USER, INTEGRATION, DEVICE)
        assert outcome.phase == "failed"
        assert "/workspace" not in (outcome.instructions or "")

    async def test_a_rejected_token_does_not_leak_sandbox_paths(self, env):
        env.exists.return_value = False
        env.write_token.return_value = CliResult(
            exit_code=1, stdout="", stderr="bad token; see /home/user/.gaia/apps/gh/install.log"
        )
        outcome = await connect.advance(USER, "gh", TOKEN, token="bad")
        assert outcome.phase == "failed"
        assert "/home/user" not in (outcome.instructions or "")

    async def test_a_duplicate_attach_losing_a_race_is_not_an_error(self, env):
        # Two overlapping polls both see "absent"; the loser's insert raises.
        # That must stay a no-op, not a user-visible connect failure.
        env.exists.return_value = False
        env.add_user.side_effect = ValueError("Integration 'x' already added to workspace")
        env.probe.return_value = state(authenticated=True)
        outcome = await connect.advance(USER, INTEGRATION, DEVICE)
        assert outcome.phase == "connected"

    async def test_an_unrelated_attach_failure_still_propagates(self, env):
        env.exists.return_value = False
        env.add_user.side_effect = RuntimeError("mongo down")
        with pytest.raises(RuntimeError):
            await connect.advance(USER, INTEGRATION, DEVICE)


class TestInfrastructureFailuresAreExplained:
    """A user cannot act on "500: failed to run reserve script"."""

    async def test_an_unavailable_sandbox_says_what_to_do(self, env):
        from app.services.sandbox import SandboxAcquisitionError

        with patch.object(
            connect,
            "acquire_sandbox",
            MagicMock(side_effect=SandboxAcquisitionError("e2b 500: reserve script failed")),
        ):
            outcome = await connect.advance(USER, INTEGRATION, DEVICE)

        assert outcome.phase == "failed"
        assert "link-cli" in (outcome.message or "")
        assert "try again" in (outcome.message or "").lower()

    async def test_a_sandbox_rate_limit_is_named_as_the_users_own_quota(self, env):
        from app.services.sandbox.errors import SandboxRateLimitError

        with patch.object(
            connect,
            "acquire_sandbox",
            MagicMock(side_effect=SandboxRateLimitError("too many")),
        ):
            outcome = await connect.advance(USER, INTEGRATION, DEVICE)

        assert outcome.phase == "failed"
        assert "too many workspaces" in (outcome.message or "")
        # A quota is not a broken integration, so no upstream noise is shown.
        assert outcome.instructions is None

    async def test_the_integration_is_still_attached_before_the_failure(self, env):
        from app.services.sandbox import SandboxAcquisitionError

        with patch.object(
            connect,
            "acquire_sandbox",
            MagicMock(side_effect=SandboxAcquisitionError("down")),
        ):
            await connect.advance(USER, INTEGRATION, DEVICE)
        # Otherwise a user who hits a blip has no record to retry against.
        env.add_user.assert_awaited_once()
