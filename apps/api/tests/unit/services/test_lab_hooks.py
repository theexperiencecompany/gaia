"""Lab hooks fragment + sandbox seeding (vendored JSON validity, seed rendering)."""

import base64
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from app.services.agent_lab import sandbox_setup
from app.services.agent_lab.claude_driver import ClaudeDriver
from app.services.agent_lab.driver import AgentDriver
from app.services.agent_lab.sandbox_setup import (
    CREDENTIAL_LINKS,
    MERGE_SETTINGS_SCRIPT,
    SEEDED_FRAGMENT_PATH,
    TOKEN_PLACEHOLDER,
    URL_PLACEHOLDER,
    WORKSPACE_CLAUDE_SETTINGS,
    build_seed_command,
    lab_events_enabled,
    mint_lab_hooks_token,
    render_hooks_fragment,
)
from app.services.sandbox import execute_token

FRAGMENT_PATH = Path(sandbox_setup.__file__).with_name("claude_hooks.json")
SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"
EVENTS_URL = "https://api.test.example/api/v1/lab/events"


def _fragment_text() -> str:
    return FRAGMENT_PATH.read_text()


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
        (notification_group,) = fragment["hooks"]["Notification"]
        matchers = notification_group["matcher"].replace(",", "|").split("|")
        assert {"agent_needs_input", "agent_completed"} <= set(matchers)

    def test_every_handler_is_an_http_push_with_placeholders(self) -> None:
        fragment = json.loads(_fragment_text())
        handlers = [
            handler
            for groups in fragment["hooks"].values()
            for group in groups
            for handler in group["hooks"]
        ]
        assert len(handlers) == 2
        for handler in handlers:
            assert handler["type"] == "http"
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
        command = build_seed_command(EVENTS_URL, "tok-1")

        assert "{{" not in command
        assert EVENTS_URL not in command
        assert WORKSPACE_CLAUDE_SETTINGS in command
        assert SEEDED_FRAGMENT_PATH in command

    def test_seed_links_every_cli_credential_dir_into_the_workspace(self) -> None:
        command = build_seed_command(EVENTS_URL, "tok-1")

        assert len(CREDENTIAL_LINKS) == 3
        for _, target in CREDENTIAL_LINKS:
            assert target.startswith("/workspace/.credentials/")
            assert target in command

    def test_seed_never_clobbers_a_live_login(self) -> None:
        """Link-if-missing only: an existing credential dir is left alone."""
        command = build_seed_command(EVENTS_URL, "tok-1")

        assert "rm " not in command
        assert command.count("|| ln -s") == len(CREDENTIAL_LINKS)

    def test_seeded_fragment_decodes_to_the_rendered_push_config(self) -> None:
        command = build_seed_command(EVENTS_URL, "tok-secret")
        prefix = "echo '"
        encoded = next(
            part[len(prefix) : -len("' | base64 -d > " + SEEDED_FRAGMENT_PATH)]
            for part in command.split(" && ")
            if part.startswith(prefix) and part.endswith("' | base64 -d > " + SEEDED_FRAGMENT_PATH)
        )
        assert json.loads(base64.b64decode(encoded).decode()) == json.loads(
            render_hooks_fragment(EVENTS_URL, "tok-secret")
        )


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
        assert len(merged["hooks"]["Notification"]) == 1

        self._run_merge(fragment_file, settings_file)
        reseeded = json.loads(settings_file.read_text())
        assert len(reseeded["hooks"]["Stop"]) == 1

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


@pytest.mark.unit
class TestDriverWiring:
    def test_only_claude_opts_into_hook_seeding(self) -> None:
        assert ClaudeDriver.lab_hooks_enabled is True
        assert AgentDriver.build_seed_command(EVENTS_URL, "tok") is None
        assert AgentDriver.lab_hooks_enabled is False

    def test_claude_seed_delegates_to_the_rendered_command(self) -> None:
        assert ClaudeDriver.build_seed_command(EVENTS_URL, "tok-1") == build_seed_command(
            EVENTS_URL, "tok-1"
        )
