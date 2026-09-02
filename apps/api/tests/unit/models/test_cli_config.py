"""Unit tests for CLI integration configuration models."""

from pydantic import ValidationError
import pytest

from app.models.cli_config import CliAuthSpec, CliConfig


def _auth(**overrides: object) -> CliAuthSpec:
    base: dict[str, object] = {"kind": "none", "verify_command": "tool --version"}
    base.update(overrides)
    return CliAuthSpec(**base)  # type: ignore[arg-type]


class TestCliAuthSpecShapeInvariants:
    """Each auth shape must carry the fields its connect flow reads.

    These are the failures that would otherwise surface as a connect dialog
    that collects a secret and drops it, or a device login with nothing to run.
    """

    def test_device_requires_login_command(self):
        with pytest.raises(ValidationError, match="requires login_command"):
            _auth(kind="device")

    def test_device_accepts_login_command(self):
        spec = _auth(kind="device", login_command="tool auth login")
        assert spec.login_command == "tool auth login"

    def test_token_requires_token_env(self):
        with pytest.raises(ValidationError, match="requires token_env"):
            _auth(kind="token", token_label="API token")

    def test_token_requires_token_label(self):
        with pytest.raises(ValidationError, match="requires token_label"):
            _auth(kind="token", token_env="TOOL_TOKEN")

    def test_token_shape_is_complete(self):
        spec = _auth(kind="token", token_env="TOOL_TOKEN", token_label="API token")
        assert spec.token_env == "TOOL_TOKEN"

    def test_none_must_not_declare_a_login(self):
        with pytest.raises(ValidationError, match="must not set login_command"):
            _auth(kind="none", login_command="tool auth login")

    @pytest.mark.parametrize(
        "bad", ["lower_case", "1STARTS_WITH_DIGIT", "HAS-DASH", "HAS SPACE", ""]
    )
    def test_token_env_rejects_non_environment_names(self, bad: str):
        # token_env is interpolated into `export <name>=...`; anything that is
        # not a shell-legal variable name would produce a broken env file.
        with pytest.raises(ValidationError):
            _auth(kind="token", token_env=bad, token_label="x")

    @pytest.mark.parametrize("good", ["GH_TOKEN", "T", "_LEADING", "A1_B2"])
    def test_token_env_accepts_environment_names(self, good: str):
        assert _auth(kind="token", token_env=good, token_label="x").token_env == good


class TestCliConfigCommandValidation:
    """``command`` becomes a filename on PATH and is interpolated into shell."""

    @pytest.mark.parametrize(
        "bad",
        [
            "../escape",
            "/usr/bin/absolute",
            "with space",
            "semi;colon",
            "pipe|char",
            "dollar$sign",
            "back`tick`",
            "amp&",
            "",
            "-leading-dash",
        ],
    )
    def test_rejects_unsafe_command_names(self, bad: str):
        with pytest.raises(ValidationError):
            CliConfig(command=bad, install_command="true", auth=_auth())

    @pytest.mark.parametrize("good", ["gh", "link-cli", "wrangler", "tool.js", "a_b", "x1"])
    def test_accepts_plain_executable_names(self, good: str):
        assert CliConfig(command=good, install_command="true", auth=_auth()).command == good

    def test_rejects_command_longer_than_the_bound(self):
        with pytest.raises(ValidationError):
            CliConfig(command="a" * 65, install_command="true", auth=_auth())

    @pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
    def test_rejects_blank_install_command(self, blank: str):
        with pytest.raises(ValidationError, match="install_command cannot be empty"):
            CliConfig(command="gh", install_command=blank, auth=_auth())

    def test_capabilities_default_to_empty_not_shared(self):
        first = CliConfig(command="gh", install_command="true", auth=_auth())
        second = CliConfig(command="gh", install_command="true", auth=_auth())
        first.capabilities.append("mutated")
        assert second.capabilities == []
