"""Unit tests for the CLI sandbox runtime.

The scripts this module generates are executed by a real shell inside the
sandbox, so the tests that matter most check them AS SHELL: every script is
parsed with ``sh -n``, including with adversarial install commands and
integration ids. A quoting bug here is not a cosmetic defect — it is arbitrary
shell in the user's sandbox, or an install that silently never happens.
"""

from __future__ import annotations

import shutil
import subprocess
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.constants.cli_integrations import app_dir, home_dir, launcher_path
from app.models.cli_config import CliAuthSpec, CliConfig
from app.services.cli import runtime

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX sh required")


def make_config(**overrides: object) -> CliConfig:
    base: dict[str, object] = {
        "command": "link-cli",
        "install_command": "npm install @stripe/link-cli",
        "auth": CliAuthSpec(
            kind="device",
            login_command="link-cli auth login",
            verify_command="link-cli auth status",
        ),
    }
    base.update(overrides)
    return CliConfig(**base)  # type: ignore[arg-type]  # kwargs dict widens to object; the model validates the real types


def assert_valid_shell(script: str) -> None:
    """Parse the script with a real shell; fail with its complaint if invalid."""
    result = subprocess.run(["sh", "-n"], input=script, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"generated script is not valid shell:\n{result.stderr}"


class TestGeneratedScriptsAreValidShell:
    def test_install_script_parses(self):
        assert_valid_shell(runtime._install_script("stripe_link", make_config()))

    def test_wrapped_command_parses(self):
        assert_valid_shell(runtime._wrap("stripe_link", make_config(), "link-cli --version"))

    @pytest.mark.parametrize(
        "install_command",
        [
            "npm install pkg && echo done",
            "curl -fsSL 'https://example.test/a b.tgz' -o x.tgz && tar -xzf x.tgz",
            'printf "#!/bin/sh\\necho hi\\n" > bin/tool && chmod +x bin/tool',
            "sh -c 'echo nested single quotes'",
            'echo "double \\"escaped\\" quotes"',
            "echo $HOME && echo ${PATH} && echo `date`",
            "echo 'unbalanced-looking; but fine'",
            "for i in 1 2 3; do echo $i; done",
        ],
    )
    def test_install_command_is_embedded_verbatim_and_stays_parseable(self, install_command: str):
        # install_command is intentionally free-form shell (that is what makes an
        # arbitrary vendor CLI installable), so it is embedded rather than quoted
        # — but embedding it must not break the surrounding script.
        script = runtime._install_script("app_id", make_config(install_command=install_command))
        assert install_command in script
        assert_valid_shell(script)

    @pytest.mark.parametrize(
        "user_command",
        [
            "link-cli --version",
            "link-cli auth status --format json | grep -q true",
            "link-cli list && echo ok || echo failed",
            "link-cli x > out.json 2>&1",
            "echo 'single' && echo \"double\"",
        ],
    )
    def test_user_commands_keep_shell_features(self, user_command: str):
        script = runtime._wrap("app_id", make_config(), user_command)
        assert user_command in script
        assert_valid_shell(script)

    def test_probe_state_script_parses_with_a_piped_verify_command(self):
        config = make_config(
            auth=CliAuthSpec(
                kind="device",
                login_command="link-cli auth login",
                verify_command=(
                    "link-cli auth status --format json "
                    "| grep -qi '\"authenticated\"[[:space:]]*:[[:space:]]*true'"
                ),
            )
        )
        # probe_state builds its script through _wrap; rebuild the same shape.
        script = runtime._wrap(
            "stripe_link", config, f"if ( {config.auth.verify_command} ); then :; fi"
        )
        assert_valid_shell(script)


class TestLauncher:
    def test_points_home_at_durable_storage(self):
        body = runtime._launcher_body("stripe_link")
        assert f"export HOME={home_dir('stripe_link')}" in body
        # The durable home must be the JuiceFS workspace, never local disk:
        # local disk is lost when the sandbox is recreated, which would log the
        # user out of every CLI roughly hourly.
        assert home_dir("stripe_link").startswith("/workspace/")

    def test_sets_xdg_variables_for_tools_that_honour_them(self):
        body = runtime._launcher_body("x")
        for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
            assert f"export {var}=" in body

    def test_sources_the_credential_env_file_when_present(self):
        body = runtime._launcher_body("x")
        assert 'if [ -f "$HOME/.gaia-env" ]' in body
        assert '. "$HOME/.gaia-env"' in body

    def test_execs_the_resolved_binary_with_all_arguments(self):
        assert 'exec "$GAIA_CLI_BINARY" "$@"' in runtime._launcher_body("x")

    def test_search_path_covers_every_install_layout(self):
        path = runtime._bin_search_path("app_id")
        app = app_dir("app_id")
        # npm, release tarball, pip --user, and a bare downloaded binary.
        for expected in (f"{app}/node_modules/.bin", f"{app}/bin", f"{app}/.local/bin", app):
            assert expected in path


class TestInstallGuard:
    def test_skips_install_when_the_marker_and_launcher_both_exist(self):
        script = runtime._install_script("app_id", make_config())
        # The guard reinstalls when EITHER is missing: the marker alone is not
        # enough, because the launcher lives on local disk and a sandbox can be
        # recreated with a stale marker from a previous layout.
        assert "if [ ! -f " in script
        assert "|| [ ! -x " in script

    def test_reports_a_distinct_exit_code_for_install_failure(self):
        script = runtime._install_script("app_id", make_config())
        assert f"exit {runtime.INSTALL_FAILED_EXIT_CODE}" in script

    def test_install_runs_with_home_on_local_disk(self):
        # npm's cache is hundreds of small files; on JuiceFS the same install
        # was measured at >600s versus ~20s locally.
        script = runtime._install_script("app_id", make_config())
        assert f"export HOME={app_dir('app_id')}/.home" in script

    def test_writes_the_launcher_for_the_configured_command(self):
        script = runtime._install_script("app_id", make_config(command="gh"))
        assert launcher_path("gh") in script


class TestParseState:
    def test_reads_every_flag(self):
        stdout = (
            f"{runtime._STATE_LINE} authenticated=1 running=0 age=42\n"
            f"{runtime._OUTPUT_BEGIN}\n"
            "go to https://example.test\ncode ABCD\n"
        )
        state = runtime._parse_state(stdout)
        assert state.installed is True
        assert state.authenticated is True
        assert state.login_running is False
        assert state.login_age_seconds == 42
        assert state.login_output == "go to https://example.test\ncode ABCD"

    def test_negative_age_means_no_login_has_been_started(self):
        stdout = (
            f"{runtime._STATE_LINE} authenticated=0 running=0 age=-1\n{runtime._OUTPUT_BEGIN}\n"
        )
        assert runtime._parse_state(stdout).login_age_seconds is None

    def test_output_after_the_marker_is_captured_verbatim_including_markers(self):
        # A CLI could legitimately print something resembling our own marker;
        # everything after the first output marker is payload, not protocol.
        stdout = (
            f"{runtime._STATE_LINE} authenticated=0 running=1 age=3\n"
            f"{runtime._OUTPUT_BEGIN}\n"
            f"{runtime._STATE_LINE} authenticated=1 running=0 age=0\n"
        )
        state = runtime._parse_state(stdout)
        assert state.authenticated is False, "a marker inside CLI output must not be re-read"
        assert runtime._STATE_LINE in state.login_output

    def test_missing_state_line_reports_not_installed(self):
        assert runtime._parse_state("total garbage").installed is False

    def test_empty_stdout_reports_not_installed(self):
        state = runtime._parse_state("")
        assert state.installed is False
        assert state.authenticated is False

    def test_output_is_truncated_to_the_documented_bound(self):
        from app.constants.cli_integrations import LOGIN_OUTPUT_MAX_CHARS

        stdout = (
            f"{runtime._STATE_LINE} authenticated=0 running=1 age=1\n"
            f"{runtime._OUTPUT_BEGIN}\n" + ("x" * (LOGIN_OUTPUT_MAX_CHARS * 2))
        )
        assert len(runtime._parse_state(stdout).login_output) <= LOGIN_OUTPUT_MAX_CHARS


class TestProbeStateInstallFailure:
    async def test_reports_the_install_error_rather_than_not_authenticated(self):
        sandbox = MagicMock()
        sandbox.commands.run = AsyncMock(
            return_value=MagicMock(
                exit_code=runtime.INSTALL_FAILED_EXIT_CODE,
                stdout="",
                stderr="npm ERR! 404 no such package",
            )
        )
        state = await runtime.probe_state(sandbox, "app_id", make_config())
        assert state.installed is False
        assert state.authenticated is False
        assert "404" in state.install_error


class TestWriteToken:
    async def test_never_puts_the_secret_in_a_shell_command(self):
        sandbox = MagicMock()
        sandbox.commands.run = AsyncMock(return_value=MagicMock(exit_code=0, stdout="", stderr=""))
        sandbox.files.write = AsyncMock()
        config = make_config(
            auth=CliAuthSpec(
                kind="token",
                verify_command="gh auth status",
                token_env="GH_TOKEN",
                token_label="GitHub token",
            )
        )
        secret = "ghp_supersecretvalue"

        await runtime.write_token(sandbox, "gh", config, secret)

        sandbox.files.write.assert_awaited_once()
        path, body = sandbox.files.write.await_args.args
        assert path == f"{home_dir('gh')}/.gaia-env"
        assert secret in body
        # argv and shell history are readable inside the sandbox and are
        # persisted by the bash tool's run logs; the secret must not reach them.
        for call in sandbox.commands.run.await_args_list:
            assert secret not in call.args[0]


class TestUserVisibleOutput:
    """CLI output is relayed to the user verbatim, minus GAIA's own plumbing."""

    def test_drops_lines_naming_the_durable_home(self):
        text = (
            'verification_url: "https://app.link.com/device/setup?code=abc"\n'
            "credentials_path: /workspace/.gaia/apps/stripe_link/.config/x.json\n"
            "phrase: abc"
        )
        out = runtime.user_visible_output(text)
        assert "/workspace" not in out
        assert "https://app.link.com/device/setup?code=abc" in out
        assert "phrase: abc" in out

    @pytest.mark.parametrize(
        "line",
        [
            "config written to /home/user/.gaia/apps/gh/x",
            "installed into /opt/gaia/runtime/bin",
            "see /workspace/.gaia/apps/gh/install.log",
        ],
    )
    def test_drops_every_internal_root(self, line: str):
        assert runtime.user_visible_output(f"keep me\n{line}\nkeep me too") == (
            "keep me\nkeep me too"
        )

    def test_keeps_vendor_paths_that_are_not_ours(self):
        # A vendor's own URL or a path on the user's real machine is theirs to
        # show; only GAIA's sandbox roots are noise.
        text = "open https://dashboard.example.test/tokens\nrun: gh auth login"
        assert runtime.user_visible_output(text) == text

    def test_empty_input_stays_empty(self):
        assert runtime.user_visible_output("") == ""

    def test_output_that_is_entirely_internal_collapses_to_nothing(self):
        assert runtime.user_visible_output("/workspace/a\n/opt/gaia/b") == ""


class TestLoginLifecycleHardening:
    """Defects found reviewing this branch, each with a concrete failure."""

    def test_age_is_measured_from_the_pid_file_not_the_log(self):
        # The log's mtime is its LAST WRITE. A login that prints progress while
        # it polls (link-cli auth login --interval does exactly this) would look
        # permanently fresh, so the connect flow would never restart an expired
        # device code and the user would stare at a dead one until the client
        # cap fired.
        script = runtime._state_script("app_id", make_config())
        assert runtime._login_pid_path("app_id") in script
        stat_lines = [line for line in script.splitlines() if "stat -c %Y" in line]
        assert stat_lines, "expected an mtime read"
        for line in stat_lines:
            assert runtime._login_pid_path("app_id") in line
            assert runtime._login_log_path("app_id") not in line

    def test_the_verify_command_carries_its_own_deadline_and_no_stdin(self):
        # Without these, an authored verify_command that waits on a TTY blocks
        # for the whole probe budget while holding the per-user sandbox lock,
        # queueing every other tool call that user makes behind it.
        from app.constants.cli_integrations import VERIFY_TIMEOUT_SECONDS

        script = runtime._state_script("app_id", make_config())
        assert f"timeout {VERIFY_TIMEOUT_SECONDS}" in script
        assert "</dev/null" in script

    def test_a_verify_command_with_a_pipe_survives_being_bounded(self):
        # The bound wraps the command in `sh -c`, so it has to be quoted as one
        # argument or a piped verify would be split.
        config = make_config(
            auth=CliAuthSpec(
                kind="device",
                login_command="tool auth login",
                verify_command="tool auth status --json | grep -q true",
            )
        )
        script = runtime._wrap("app_id", config, runtime._state_script("app_id", config))
        assert_valid_shell(script)
        assert "grep -q true" in script

    def test_the_login_log_read_is_bounded_in_the_sandbox(self):
        # Truncating in Python still pulls an unbounded log across the wire on
        # every one of up to 240 poll ticks.
        script = runtime._state_script("app_id", make_config())
        assert "tail -c" in script
        assert f"cat {runtime._login_log_path('app_id')}" not in script

    async def test_starting_a_login_kills_the_one_it_replaces(self):
        # Deleting the pid file without killing the process orphans it: its only
        # handle is gone, so cancel_login can never reach it.
        sandbox = MagicMock()
        sandbox.commands.run = AsyncMock(return_value=MagicMock(exit_code=0, stdout="", stderr=""))
        await runtime.start_login(sandbox, "app_id", make_config())

        script = sandbox.commands.run.await_args.args[0]
        kill_index = script.index("kill ")
        remove_index = script.index("rm -f")
        assert kill_index < remove_index, "the predecessor must die before its pid file is removed"
