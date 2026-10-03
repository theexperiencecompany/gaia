"""Lab hooks fragment + sandbox seeding (vendored JSON validity, seed rendering)."""

import base64
import json
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

import pytest

from app.services.agent_lab import sandbox_setup
from app.services.agent_lab.sandbox_setup import (
    CLAUDE_INSTALL_LINE,
    CREDENTIAL_LINKS,
    LAB_CALLBACK_URL_VAR,
    LAB_RUN_ID_VAR,
    LAB_SESSION_ID_VAR,
    LAB_TOKEN_VAR,
    MERGE_SETTINGS_SCRIPT,
    OPENCODE_INSTALL_LINE,
    TOKEN_PLACEHOLDER,
    URL_PLACEHOLDER,
    build_seed_command,
    lab_events_enabled,
    mint_lab_hooks_token,
    render_hooks_fragment,
    render_lab_env,
)
from app.services.sandbox import execute_token
from app.utils.errors import AppError

FRAGMENT_PATH = Path(sandbox_setup.__file__).with_name("claude_hooks.json")
PLUGIN_PATH = Path(sandbox_setup.__file__).with_name("opencode_notify_plugin.js")
SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"
EVENTS_URL = "https://api.test.example/api/v1/lab/events"
SESSION_ID = "lab-run-1"
RUN_DIR = "/workspace/lab-runs/lab-run-1"


def _fragment_text() -> str:
    return FRAGMENT_PATH.read_text()


def _seed() -> str:
    return build_seed_command(EVENTS_URL, "tok-1", SESSION_ID, RUN_DIR)


@pytest.mark.unit
class TestHooksFragment:
    def test_parses_and_covers_stop_plus_notification(self) -> None:
        fragment = json.loads(_fragment_text())
        assert set(fragment["hooks"]) == {"Stop", "Notification"}

    def test_stop_has_no_matcher_and_notification_matches_both_types(self) -> None:
        """Stop fires without matcher support; Notification narrows to the two push types."""
        fragment = json.loads(_fragment_text())
        (stop_group,) = fragment["hooks"]["Stop"]
        assert "matcher" not in stop_group
        matched = [group for group in fragment["hooks"]["Notification"] if "matcher" in group]
        assert len(matched) == 1
        matchers = matched[0]["matcher"].replace(",", "|").split("|")
        assert {"agent_needs_input", "agent_completed"} <= set(matchers)

    def test_notification_catch_all_has_no_matcher(self) -> None:
        """A question matching nothing must not vanish: one matcherless Notification group."""
        fragment = json.loads(_fragment_text())
        catch_all = [group for group in fragment["hooks"]["Notification"] if "matcher" not in group]
        assert len(catch_all) == 1
        (handler,) = catch_all[0]["hooks"]
        assert handler["type"] == "http"

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

    def test_seed_targets_the_run_workdir_never_global(self) -> None:
        """Per-run isolation: concurrent runs keep separate tokens."""
        command = _seed()

        assert f"{RUN_DIR}/.claude/settings.json" in command
        assert f"{RUN_DIR}/.gaia/claude-hooks.json" in command
        assert "$HOME/.claude/settings.json" not in command
        assert "~/.claude/settings.json" not in command
        assert "/workspace/.claude/settings.json" not in command

    def test_seed_installs_both_clis_and_drops_codex(self) -> None:
        """MVP ships Claude + OpenCode install lines; Codex login is docs-only (link kept)."""
        command = _seed()

        assert CLAUDE_INSTALL_LINE in command
        assert OPENCODE_INSTALL_LINE in command
        assert "chatgpt.com/codex" not in command
        assert "@openai/codex" not in command

    def test_seed_echoes_a_stable_run_id_for_reply_routing(self) -> None:
        command = _seed()

        assert f"{LAB_RUN_ID_VAR}={SESSION_ID}" in command

    def test_seed_writes_a_sourced_env_file_for_serve_start(self) -> None:
        """The plugin reads GAIA_LAB_* from process.env; serve sources this file first."""
        command = _seed()
        env_path = f"{RUN_DIR}/.gaia/lab-env"

        assert env_path in command
        assert f'chmod 600 "{env_path}"' in command
        prefix = "echo '"
        encoded = next(
            part[len(prefix) : -len(f'\' | base64 -d > "{env_path}"')]
            for part in command.split(" && ")
            if part.startswith(prefix) and part.endswith(f'\' | base64 -d > "{env_path}"')
        )
        decoded = base64.b64decode(encoded).decode()
        assert decoded == render_lab_env(EVENTS_URL, "tok-1", SESSION_ID)
        assert f"{LAB_CALLBACK_URL_VAR}={EVENTS_URL}" in decoded
        assert f"{LAB_TOKEN_VAR}=tok-1" in decoded
        assert f"{LAB_SESSION_ID_VAR}={SESSION_ID}" in decoded

    def test_seed_requires_a_run_dir(self) -> None:
        with pytest.raises(AppError):
            build_seed_command(EVENTS_URL, "tok-1", SESSION_ID, "")

    def test_render_lab_env_fails_loud_on_empty_input(self) -> None:
        with pytest.raises(AppError):
            render_lab_env("", "tok-1", SESSION_ID)

    def test_seed_links_every_cli_credential_dir_into_the_workspace(self) -> None:
        command = _seed()

        assert len(CREDENTIAL_LINKS) == 3
        for _, target in CREDENTIAL_LINKS:
            assert target.startswith("/workspace/.credentials/")
            assert target in command

    def test_seed_never_clobbers_a_live_login(self) -> None:
        """Link-if-missing only: an existing credential dir is left alone."""
        command = _seed()

        assert "rm " not in command
        assert command.count("|| ln -s") == len(CREDENTIAL_LINKS)

    def test_seeded_fragment_decodes_to_the_rendered_push_config(self) -> None:
        command = build_seed_command(EVENTS_URL, "tok-secret", SESSION_ID, RUN_DIR)
        fragment_path = f"{RUN_DIR}/.gaia/claude-hooks.json"
        prefix = "echo '"
        encoded = next(
            part[len(prefix) : -len(f'\' | base64 -d > "{fragment_path}"')]
            for part in command.split(" && ")
            if part.startswith(prefix) and part.endswith(f'\' | base64 -d > "{fragment_path}"')
        )
        assert json.loads(base64.b64decode(encoded).decode()) == json.loads(
            render_hooks_fragment(EVENTS_URL, "tok-secret")
        )

    def test_seeded_plugin_decodes_to_the_vendored_source(self) -> None:
        """The relay plugin ships byte-identical; its contract is verified live, not here."""
        command = _seed()
        plugin_path = f"{RUN_DIR}/.opencode/plugins/gaia_lab_notify.js"
        prefix = "echo '"
        encoded = next(
            part[len(prefix) : -len(f'\' | base64 -d > "{plugin_path}"')]
            for part in command.split(" && ")
            if part.startswith(prefix) and part.endswith(f'\' | base64 -d > "{plugin_path}"')
        )
        assert base64.b64decode(encoded).decode() == PLUGIN_PATH.read_text()


@pytest.mark.unit
class TestNotifyPlugin:
    def test_plugin_passes_node_syntax_check(self) -> None:
        """Vendored JS must parse; payload shape is verified live, never asserted here."""
        if shutil.which("node") is None:
            pytest.skip("node is not installed — plugin syntax check needs a live drive")
        subprocess.run(["node", "--check", str(PLUGIN_PATH)], check=True, capture_output=True)


@pytest.mark.unit
class TestMergeScript:
    def test_merges_fragment_without_dupes_or_key_loss(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"other": {"keep": True}, "hooks": {"Stop": []}}))
        fragment_file = tmp_path / "fragment.json"
        fragment_file.write_text(render_hooks_fragment(EVENTS_URL, "tok-1"))

        self._run_merge(fragment_file, settings_file)
        merged = json.loads(settings_file.read_text())
        assert merged["other"] == {"keep": True}
        assert len(merged["hooks"]["Stop"]) == 1
        assert len(merged["hooks"]["Notification"]) == 2

        self._run_merge(fragment_file, settings_file)
        reseeded = json.loads(settings_file.read_text())
        assert len(reseeded["hooks"]["Stop"]) == 1
        assert len(reseeded["hooks"]["Notification"]) == 2

    def test_creates_settings_from_scratch(self, tmp_path: Path) -> None:
        settings_file = tmp_path / "settings.json"
        fragment_file = tmp_path / "fragment.json"
        fragment_file.write_text(render_hooks_fragment(EVENTS_URL, "tok-1"))

        self._run_merge(fragment_file, settings_file)
        assert set(json.loads(settings_file.read_text())["hooks"]) == {"Stop", "Notification"}

    def test_corrupt_settings_fail_loud(self, tmp_path: Path) -> None:
        """A corrupt file must never be silently replaced — the seed fails instead."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{not json")
        fragment_file = tmp_path / "fragment.json"
        fragment_file.write_text(render_hooks_fragment(EVENTS_URL, "tok-1"))

        with pytest.raises(subprocess.CalledProcessError):
            self._run_merge(fragment_file, settings_file)
        assert settings_file.read_text() == "{not json"

    @staticmethod
    def _run_merge(fragment_file: Path, settings_file: Path) -> None:
        script_file = fragment_file.parent / "merge.py"
        script_file.write_text(MERGE_SETTINGS_SCRIPT)
        subprocess.run(
            ["python3", str(script_file), str(fragment_file), str(settings_file)],
            check=True,
            capture_output=True,
        )


@pytest.mark.unit
class TestLabHooksToken:
    def test_hooks_token_carries_an_empty_tool_scope(self) -> None:
        with patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET):
            token = mint_lab_hooks_token("u1", "lab-1")
            claims = execute_token.verify_execute_token(token)

        assert claims.user_id == "u1"
        assert claims.run_id == "lab-1"
        assert claims.scoped_tool_names == []

    def test_seeding_gate_needs_secret_and_url(self) -> None:
        with (
            patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET),
            patch.object(sandbox_setup.settings, "SANDBOX_LAB_EVENTS_CALLBACK_URL", EVENTS_URL),
        ):
            assert lab_events_enabled() is True
        with patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", None):
            assert lab_events_enabled() is False
