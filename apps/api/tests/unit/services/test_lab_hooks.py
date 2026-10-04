"""Lab hooks fragment + sandbox seeding (vendored JSON validity, seed rendering)."""

import base64
import json
from pathlib import Path
import shlex
import shutil
import subprocess
from unittest.mock import patch

import pytest

from app.services.agent_lab import sandbox_setup
from app.services.agent_lab.lab_runs import run_dir
from app.services.agent_lab.sandbox_setup import (
    CREDENTIAL_LINKS,
    LAB_CALLBACK_URL_VAR,
    LAB_RUN_ID_VAR,
    LAB_TOKEN_VAR,
    TOKEN_PLACEHOLDER,
    URL_PLACEHOLDER,
    build_seed_command,
    mint_lab_hooks_token,
    render_hooks_fragment,
)
from app.services.sandbox import execute_token
from app.utils.errors import AppError

FRAGMENT_PATH = Path(sandbox_setup.__file__).with_name("claude_hooks.json")
PLUGIN_PATH = Path(sandbox_setup.__file__).with_name("opencode_notify_plugin.js")
SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"
EVENTS_URL = "https://api.test.example/api/v1/lab/events"
RUN_ID = "lab-run-1"
RUN_DIR = run_dir(RUN_ID)


def _fragment_text() -> str:
    return FRAGMENT_PATH.read_text()


def _seed() -> str:
    return build_seed_command(EVENTS_URL, "tok-1", RUN_ID)


def _decoded_write(command: str, path: str) -> str:
    """Return what the seed writes to path (its base64 echo, decoded)."""
    prefix = "echo '"
    suffix = f'\' | base64 -d > "{path}"'
    encoded = next(
        part[len(prefix) : -len(suffix)]
        for part in command.split(" && ")
        if part.startswith(prefix) and part.endswith(suffix)
    )
    return base64.b64decode(encoded).decode()


@pytest.mark.unit
class TestHooksFragment:
    def test_parses_and_covers_every_way_a_turn_ends_or_waits(self) -> None:
        """StopFailure is the API-error stop (expired login, rate limit); Stop never fires for it."""
        fragment = json.loads(_fragment_text())
        assert set(fragment["hooks"]) == {"Stop", "StopFailure", "Notification"}

    def test_each_event_has_exactly_one_matcherless_group(self) -> None:
        """Every push runs the todo, so one notification must POST once, never twice."""
        fragment = json.loads(_fragment_text())
        for event in ("Stop", "StopFailure", "Notification"):
            (group,) = fragment["hooks"][event]
            assert "matcher" not in group

    def test_every_handler_is_an_http_push_with_placeholders(self) -> None:
        fragment = json.loads(_fragment_text())
        handlers = [
            handler
            for groups in fragment["hooks"].values()
            for group in groups
            for handler in group["hooks"]
        ]
        assert len(handlers) == 3
        for handler in handlers:
            assert handler["type"] == "http"
            assert handler["timeout"] == 15
            assert handler["url"] == URL_PLACEHOLDER
            assert handler["headers"]["Authorization"] == f"Bearer {TOKEN_PLACEHOLDER}"
            assert handler["allowedEnvVars"] == []

    def test_placeholders_match_the_seeder_contract_and_no_host_is_baked_in(self) -> None:
        text = _fragment_text()
        assert URL_PLACEHOLDER in text
        assert TOKEN_PLACEHOLDER in text
        assert "://" not in text


@pytest.mark.unit
class TestRenderAndSeed:
    def test_render_replaces_every_placeholder(self) -> None:
        rendered = render_hooks_fragment(EVENTS_URL, "tok-1")

        assert "{{" not in rendered
        parsed = json.loads(rendered)
        urls = {
            handler["url"]
            for groups in parsed["hooks"].values()
            for group in groups
            for handler in group["hooks"]
        }
        assert urls == {EVENTS_URL}
        assert "tok-1" in rendered

    def test_seed_command_carries_no_placeholders_or_baked_hosts(self) -> None:
        """Host/token travel base64-encoded (no shell quoting hazard), never literal."""
        command = _seed()

        assert "{{" not in command
        assert "}}" not in command
        assert EVENTS_URL not in command
        assert "tok-1" not in command

    def test_seed_writes_only_under_the_run_workdir(self) -> None:
        """Per-run isolation: concurrent runs keep separate tokens, no global settings touched."""
        command = _seed()

        assert f"{RUN_DIR}/.gaia/claude-settings.json" in command
        assert ".claude/settings.json" not in command

    def test_run_folders_live_on_local_disk_not_juicefs(self) -> None:
        """On real E2B each JuiceFS-seeded file cost ~2.4s of hosted-metadata round trips."""
        assert not RUN_DIR.startswith("/workspace/")

    def test_seed_makes_the_run_folder_and_token_files_owner_only(self) -> None:
        command = _seed()
        assert f'chmod 700 "{RUN_DIR}"' in command
        assert f'chmod 600 "{RUN_DIR}/.gaia/claude-settings.json"' in command

    def test_seed_installs_no_cli(self) -> None:
        """Installing is the launch line's job (drive skills), so a launch pays only for its CLI."""
        command = _seed()

        assert "install" not in command
        assert "curl" not in command

    def test_run_env_points_both_clis_at_the_seeded_files(self) -> None:
        env = sandbox_setup.lab_env(EVENTS_URL, "tok-1", RUN_ID)

        assert env[LAB_CALLBACK_URL_VAR] == EVENTS_URL
        assert env[LAB_TOKEN_VAR] == "tok-1"
        assert env[LAB_RUN_ID_VAR] == RUN_ID
        assert env[sandbox_setup.LAB_CLAUDE_SETTINGS_VAR] == f"{RUN_DIR}/.gaia/claude-settings.json"
        assert env[sandbox_setup.OPENCODE_CONFIG_DIR_VAR] == f"{RUN_DIR}/.opencode"

    def test_seed_writes_the_run_env_as_a_sourceable_private_file(self) -> None:
        """A later bash call (resume) gets no env injected; it sources this file instead."""
        command = _seed()
        env_path = f"{RUN_DIR}/.gaia/lab-env"

        assert f'chmod 600 "{env_path}"' in command
        sourced = subprocess.run(
            ["bash", "-c", "set -a; . /dev/stdin; set +a; env"],
            input=_decoded_write(command, env_path),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        for key, value in sandbox_setup.lab_env(EVENTS_URL, "tok-1", RUN_ID).items():
            assert f"{key}={value}" in sourced

    def test_env_values_are_shell_quoted(self) -> None:
        decoded = _decoded_write(_seed(), f"{RUN_DIR}/.gaia/lab-env")
        assert f"{LAB_CALLBACK_URL_VAR}={shlex.quote(EVENTS_URL)}" in decoded

    def test_seed_requires_a_run_id(self) -> None:
        with pytest.raises(AppError):
            build_seed_command(EVENTS_URL, "tok-1", "")

    def test_seed_links_every_cli_credential_dir_into_the_workspace(self) -> None:
        command = _seed()

        assert len(CREDENTIAL_LINKS) == 2
        for _, target in CREDENTIAL_LINKS:
            assert target.startswith("/workspace/.credentials/")
            assert target in command

    def test_seed_never_clobbers_a_live_login(self) -> None:
        """Link-if-missing only: an existing credential dir is left alone."""
        command = _seed()

        assert "rm " not in command
        assert command.count("|| ln -s") == len(CREDENTIAL_LINKS)

    def test_seeded_settings_decode_to_the_rendered_push_config(self) -> None:
        command = build_seed_command(EVENTS_URL, "tok-secret", RUN_ID)
        written = _decoded_write(command, f"{RUN_DIR}/.gaia/claude-settings.json")
        assert json.loads(written) == json.loads(render_hooks_fragment(EVENTS_URL, "tok-secret"))

    def test_seeded_plugin_decodes_to_the_vendored_source(self) -> None:
        """The relay plugin ships byte-identical; its contract is verified live, not here."""
        written = _decoded_write(_seed(), f"{RUN_DIR}/.opencode/plugins/gaia_lab_notify.js")
        assert written == PLUGIN_PATH.read_text()


@pytest.mark.unit
class TestNotifyPlugin:
    def test_plugin_passes_node_syntax_check(self) -> None:
        """Vendored JS must parse; payload shape is verified live, never asserted here."""
        if shutil.which("node") is None:
            pytest.skip("node is not installed — plugin syntax check needs a live drive")
        subprocess.run(["node", "--check", str(PLUGIN_PATH)], check=True, capture_output=True)


@pytest.mark.unit
class TestLabHooksToken:
    def test_hooks_token_carries_an_empty_tool_scope(self) -> None:
        with patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET):
            token = mint_lab_hooks_token("u1", "lab-1")
            claims = execute_token.verify_execute_token(token)

        assert claims.user_id == "u1"
        assert claims.run_id == "lab-1"
        assert claims.scoped_tool_names == []

    def test_unconfigured_events_url_fails_loud(self) -> None:
        with patch.object(sandbox_setup.settings, "SANDBOX_LAB_EVENTS_CALLBACK_URL", None):
            with pytest.raises(AppError) as err:
                sandbox_setup.lab_events_url()
        assert err.value.status_code == 503
