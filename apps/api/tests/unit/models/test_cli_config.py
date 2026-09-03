"""Unit tests for CLI integration configuration models."""

from pydantic import ValidationError
import pytest

from app.models.cli_config import CliAuthSpec, CliConfig


def _auth(**overrides: object) -> CliAuthSpec:
    base: dict[str, object] = {"kind": "none", "verify_command": "tool --version"}
    base.update(overrides)
    return CliAuthSpec(**base)  # type: ignore[arg-type]  # kwargs dict widens to object; the model validates the real types


def _message(exc_info: pytest.ExceptionInfo[ValidationError]) -> str:
    """The single validation error's own message, without pydantic's wrapper.

    Asserted verbatim throughout this file because these strings are not just
    developer diagnostics: an authored CLI integration comes from a model that
    read a vendor's help text, ``cli_author`` re-raises them as "Invalid CLI
    configuration: <msg>", and that sentence is the entire instruction the
    model gets for its retry. Reworded to something vaguer and the retry
    guesses.
    """
    (error,) = exc_info.value.errors()
    return str(error["msg"]).removeprefix("Value error, ")


class TestCliAuthSpecShapeInvariants:
    """Each auth shape must carry the fields its connect flow reads.

    These are the failures that would otherwise surface as a connect dialog
    that collects a secret and drops it, or a device login with nothing to run.
    """

    def test_device_requires_login_command(self):
        with pytest.raises(ValidationError) as exc_info:
            _auth(kind="device")
        assert _message(exc_info) == "auth.kind='device' requires login_command"

    def test_device_accepts_login_command(self):
        spec = _auth(kind="device", login_command="tool auth login")
        assert spec.login_command == "tool auth login"

    def test_token_requires_token_env(self):
        with pytest.raises(ValidationError) as exc_info:
            _auth(kind="token", token_label="API token")
        assert _message(exc_info) == "auth.kind='token' requires token_env"

    def test_token_requires_token_label(self):
        with pytest.raises(ValidationError) as exc_info:
            _auth(kind="token", token_env="TOOL_TOKEN")
        assert _message(exc_info) == "auth.kind='token' requires token_label for the UI prompt"

    def test_token_shape_is_complete(self):
        spec = _auth(kind="token", token_env="TOOL_TOKEN", token_label="API token")
        assert spec.token_env == "TOOL_TOKEN"

    def test_none_must_not_declare_a_login(self):
        with pytest.raises(ValidationError) as exc_info:
            _auth(kind="none", login_command="tool auth login")
        assert _message(exc_info) == "auth.kind='none' must not set login_command"

    @pytest.mark.parametrize(
        "bad", ["lower_case", "1STARTS_WITH_DIGIT", "HAS-DASH", "HAS SPACE", ""]
    )
    def test_token_env_rejects_non_environment_names(self, bad: str):
        # token_env is interpolated into `export <name>=...`; anything that is
        # not a shell-legal variable name would produce a broken env file. The
        # message quotes the offending value so the author can see which of
        # their fields is wrong.
        with pytest.raises(ValidationError) as exc_info:
            _auth(kind="token", token_env=bad, token_label="x")
        assert _message(exc_info) == (f"token_env {bad!r} is not a valid environment variable name")

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
        # The message has to say both which value was rejected and what a
        # legal one looks like: the caller is often a model that read a
        # vendor's docs, and "invalid command" alone gives it nothing to fix.
        with pytest.raises(ValidationError) as exc_info:
            CliConfig(command=bad, install_command="true", auth=_auth())
        assert _message(exc_info) == (
            f"command {bad!r} must be a bare executable name "
            "(letters, digits, dot, dash, underscore)"
        )

    @pytest.mark.parametrize("good", ["gh", "link-cli", "wrangler", "tool.js", "a_b", "x1"])
    def test_accepts_plain_executable_names(self, good: str):
        assert CliConfig(command=good, install_command="true", auth=_auth()).command == good

    def test_rejects_command_longer_than_the_bound(self):
        with pytest.raises(ValidationError):
            CliConfig(command="a" * 65, install_command="true", auth=_auth())

    @pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
    def test_rejects_blank_install_command(self, blank: str):
        with pytest.raises(ValidationError) as exc_info:
            CliConfig(command="gh", install_command=blank, auth=_auth())
        assert _message(exc_info) == "install_command cannot be empty"

    def test_capabilities_default_to_empty_not_shared(self):
        first = CliConfig(command="gh", install_command="true", auth=_auth())
        second = CliConfig(command="gh", install_command="true", auth=_auth())
        first.capabilities.append("mutated")
        assert second.capabilities == []
