"""Attacks on the CLI command shape (app/services/hil/command_shape.py).

The shape is the ONLY thing standing between "one CLI is one tool" and "one verdict
covers every command that CLI can run". So two properties are attacked here:

* **Nothing that runs is left out of the shape.** A second command hidden behind a
  harmless first — after ``&&``, a ``;``, a pipe, a newline, or inside ``$( )`` — would
  otherwise ride a verdict earned by the first, forever, from the cache.
* **Unshapeable means empty, never a guess.** Every string this cannot reduce comes back
  ``""``, which the classifier turns into "destructive". A shape that quietly degraded to
  the executable alone would be a gate that reads what it wants to read.

The counterweight to both: a shape must stay STABLE across calls that differ only in
their arguments, or every call mints a new cache key and pays for a new LLM verdict.
"""

import pytest

from app.agents.tools.cli.cli_tool import (
    CLI_COMMAND_METADATA_KEY,
    CLI_INTEGRATION_METADATA_KEY,
)
from app.constants.hil import HIL_CLI_SHAPE_MAX_WORDS
from app.services.hil.command_shape import cli_command_shape, derive_command_shape

from .conftest import make_tool

# Exactly what ``build_cli_tool`` stamps on the tool it builds.
CLI_METADATA = {CLI_INTEGRATION_METADATA_KEY: "github", CLI_COMMAND_METADATA_KEY: "gh"}


class TestTheLeadingCommandWords:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("gh pr list", "gh pr list"),
            ("gh pr list --json number", "gh pr list"),
            ("link-cli spend-request create --amount 5", "link-cli spend-request create"),
            ("gh  pr   list  ", "gh pr list"),  # whitespace is not information
            ("gh pr list > out.json", "gh pr list"),  # a redirect target is not a command
            ("wrangler d1 execute db --command 'DROP TABLE t'", "wrangler d1 execute db"),
        ],
    )
    def test_flags_and_arguments_are_dropped(self, command: str, expected: str) -> None:
        assert derive_command_shape(command) == expected

    def test_calls_differing_only_in_arguments_share_one_shape(self) -> None:
        # The whole point of a shape: one classification, then cache hits forever. If
        # these diverge, every call pays for its own LLM verdict.
        assert derive_command_shape("gh pr list --json number --limit 5") == "gh pr list"
        assert derive_command_shape("gh pr list --state closed") == "gh pr list"

    def test_the_shape_is_bounded_so_one_cli_cannot_mint_unlimited_keys(self) -> None:
        shape = derive_command_shape("kubectl delete pod alpha beta gamma delta")
        assert len(shape.split(" ")) == HIL_CLI_SHAPE_MAX_WORDS

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("FOO=bar gh pr list", "gh pr list"),
            ("GH_TOKEN=x LOG_LEVEL=debug gh auth status", "gh auth status"),
        ],
    )
    def test_an_environment_prefix_is_not_the_command(self, command: str, expected: str) -> None:
        assert derive_command_shape(command) == expected

    def test_a_quoted_argument_is_one_token_however_it_is_punctuated(self) -> None:
        # A `;` inside quotes runs nothing. Splitting on it would invent a second
        # command out of an issue title and gate a harmless call forever after.
        assert (
            derive_command_shape('gh issue create --title "ship it; then deploy"')
            == "gh issue create"
        )
        assert derive_command_shape('link-cli note add "a; b"') == "link-cli note add"

    def test_a_flag_before_the_subcommand_ends_the_shape_there(self) -> None:
        # Deliberately coarse: `--repo` and its value are indistinguishable from
        # subcommands, so the shape stops rather than guessing. A bare `gh` is a shape
        # the classifier can only read as "could be anything", which gates.
        assert derive_command_shape("gh --repo acme/api pr list") == "gh"


class TestChainedCommandsAreAllInTheShape:
    """Each of these hides a repo deletion behind a harmless read. If any one of them
    reduces to the harmless prefix, that prefix's cached "safe" verdict lets every
    future chain built the same way run unattended."""

    @pytest.mark.parametrize(
        "command",
        [
            "gh pr list && gh repo delete acme/api",
            "gh pr list; gh repo delete acme/api",
            "gh pr list || gh repo delete acme/api",
            "gh pr list & gh repo delete acme/api",
            "gh pr list\ngh repo delete acme/api",
            "gh pr list | gh repo delete acme/api",
            "echo $(gh repo delete acme/api)",
            "echo `gh repo delete acme/api`",
        ],
    )
    def test_a_command_hidden_behind_a_harmless_one_is_still_shaped(self, command: str) -> None:
        shape = derive_command_shape(command)
        assert "gh repo delete" in shape
        assert shape != "gh pr list"
        assert shape != "echo"

    def test_a_chain_shapes_every_link_in_order(self) -> None:
        assert (
            derive_command_shape("gh pr list --json url | jq -r .url && gh pr merge 4")
            == "gh pr list ; jq ; gh pr merge"
        )

    def test_a_subshell_does_not_hide_what_it_wraps(self) -> None:
        assert derive_command_shape("(cd repo && rm -rf .git)") == "cd repo ; rm"


class TestUnshapeableFailsClosed:
    """``""`` is the contract with the classifier: it means "gate this", so anything
    unreadable must produce it rather than a partial shape."""

    @pytest.mark.parametrize(
        "command",
        [
            "",
            "   ",
            "\n\t ",
            "--help",  # flags only: nothing names a command
            "-rf /",
            '"just a quoted string"',
            'gh pr list "unterminated',  # where the quote closes decides what runs
            "&&",
            "/usr/local/bin/gh pr list",  # a path-qualified executable is not a plain word
            "./deploy.sh",
            "2>&1",
        ],
    )
    def test_it_yields_no_shape_at_all(self, command: str) -> None:
        assert derive_command_shape(command) == ""

    def test_one_unshapeable_link_discards_the_whole_chain(self) -> None:
        # The safe direction: a chain is only as classifiable as its least readable
        # link, so a readable prefix must not be handed over as if it were the command.
        assert derive_command_shape("gh pr list && ./wipe.sh") == ""


class TestReadingTheCallItself:
    def test_a_cli_tool_call_is_shaped_from_its_command_argument(self) -> None:
        tool = make_tool(name="run_gh", metadata=CLI_METADATA)
        assert cli_command_shape(tool, {"command": "gh repo delete acme/api", "timeout": 60}) == (
            "gh repo delete"
        )

    @pytest.mark.parametrize("metadata", [None, {}, {"unrelated": "x"}])
    def test_a_non_cli_tool_has_no_shape_and_is_classified_by_name(
        self, metadata: dict[str, str] | None
    ) -> None:
        # ``None`` is load-bearing: it is what tells the classifier to keep using the
        # registry's name-keyed flag for every tool that is not CLI-backed.
        tool = make_tool(name="send_email", metadata=metadata)
        assert cli_command_shape(tool, {"to": "bob@example.com"}) is None

    def test_a_call_with_no_tool_object_is_classified_by_name(self) -> None:
        assert cli_command_shape(None, {"command": "gh repo delete acme/api"}) is None

    @pytest.mark.parametrize("args", [None, {}, {"timeout": 60}, {"command": None}, {"command": 7}])
    def test_a_cli_call_with_no_usable_command_gates(self, args: dict[str, object] | None) -> None:
        # A CLI tool whose command argument is missing or malformed must fail closed —
        # ``""`` gates — never fall back to the name-keyed verdict a ``None`` would ask for.
        tool = make_tool(name="run_gh", metadata=CLI_METADATA)
        assert cli_command_shape(tool, args) == ""
