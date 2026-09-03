"""The registry name for a CLI integration's tool.

The tool registry is process-global and keyed by name alone, while custom CLI
integrations are per-user Mongo documents. Two users each authoring a CLI called
``gh`` therefore share one registry slot unless the name disambiguates them.
"""

import pytest

from app.constants.cli_integrations import app_dir, cli_tool_name, install_marker_path


class TestPlatformNames:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("link-cli", "run_link_cli"),
            ("gh", "run_gh"),
            ("wrangler", "run_wrangler"),
            ("tool.js", "run_tool_js"),
        ],
    )
    def test_curated_integrations_keep_the_clean_name(self, command, expected):
        # The model both selects this name and types the command inside it, so
        # keeping them the same word measurably reduces it inventing another.
        assert cli_tool_name(command, "stripe_link", is_platform=True) == expected

    def test_the_name_does_not_depend_on_the_integration_id(self):
        a = cli_tool_name("gh", "one", is_platform=True)
        b = cli_tool_name("gh", "two", is_platform=True)
        assert a == b == "run_gh"


class TestCustomNames:
    def test_two_users_authoring_the_same_cli_do_not_collide(self):
        # Last-writer-wins in the registry would give one user's approval cards,
        # Chroma namespace and cached HIL verdict to the other user's tool.
        a = cli_tool_name("gh", "11111111-1111-1111-1111-111111111111", is_platform=False)
        b = cli_tool_name("gh", "22222222-2222-2222-2222-222222222222", is_platform=False)
        assert a != b

    def test_the_command_is_still_readable_in_the_name(self):
        name = cli_tool_name("gh", "some-uuid", is_platform=False)
        assert name.startswith("run_gh_")

    def test_the_same_integration_always_gets_the_same_name(self):
        # Registration is idempotent and re-runs on every subagent build; a
        # non-deterministic name would register a new tool each time.
        first = cli_tool_name("gh", "stable-id", is_platform=False)
        second = cli_tool_name("gh", "stable-id", is_platform=False)
        assert first == second

    def test_a_custom_name_never_shadows_the_platform_form(self):
        assert cli_tool_name("gh", "any-id", is_platform=False) != cli_tool_name(
            "gh", "any-id", is_platform=True
        )


class TestInstallMarkerPath:
    """Where the "this CLI is already installed" marker lives.

    ``probe_state`` skips the ~20 s install when this file exists, so the path
    is the whole of that decision. It has to sit inside the integration's own
    app directory: a shared location would let installing one CLI convince the
    sandbox that every other CLI was installed too, and the agent would then
    invoke a command that is not there.
    """

    def test_the_marker_lives_inside_that_integrations_app_directory(self):
        assert install_marker_path("stripe_link").startswith(f"{app_dir('stripe_link')}/")

    def test_two_integrations_do_not_share_a_marker(self):
        assert install_marker_path("stripe_link") != install_marker_path("github_cli")
