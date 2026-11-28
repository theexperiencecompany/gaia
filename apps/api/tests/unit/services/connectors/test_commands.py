"""A connector call is a read only when its spec proves it; everything else asks per command type."""

import pytest

from app.constants.connectors import MAX_CONNECTOR_ARGS, SDK_SCRIPT_COMMAND_TYPE
from app.services.connectors.commands import InvalidConnectorCallError, plan_call
from app.services.connectors.rest_helper import REST_HELPER_ARGV
from tests.factories import make_connector_spec

GH = make_connector_spec("cli")
RESEND = make_connector_spec("rest")
OPENAI = make_connector_spec("sdk")


@pytest.mark.parametrize(
    ("args", "command_type"),
    [
        (["api", "user"], "api"),
        (["repo", "list", "--limit", "5"], "repo list"),
        (["--repo", "o/r", "issue", "list"], "issue list"),
    ],
)
def test_a_listed_read_subcommand_runs_as_a_read(args: list[str], command_type: str) -> None:
    plan = plan_call(GH, args)

    assert (plan.is_write, plan.command_type) == (False, command_type)
    assert plan.argv == ("gh", *args)


@pytest.mark.parametrize("flag", ["-X", "--method=POST", "-f"])
def test_a_write_flag_makes_a_listed_read_a_write(flag: str) -> None:
    plan = plan_call(GH, ["api", "/repos/o/r/issues", flag, "title=x"])

    assert (plan.is_write, plan.command_type) == (True, "api")


def test_an_unlisted_subcommand_is_a_write_typed_by_its_first_two_words() -> None:
    plan = plan_call(GH, ["pr", "create", "--title", "x"])

    assert (plan.is_write, plan.command_type) == (True, "pr create")


def test_a_listed_prefix_does_not_cover_a_longer_unlisted_command() -> None:
    plan = plan_call(GH, ["repo", "delete", "o/r", "--yes"])

    assert (plan.is_write, plan.command_type) == (True, "repo delete")


def test_help_is_a_read() -> None:
    assert not plan_call(GH, ["pr", "merge", "--help"]).is_write


def test_rest_get_is_a_read_and_post_is_typed_by_method_and_resource() -> None:
    read = plan_call(RESEND, ["GET", "/domains"])
    write = plan_call(RESEND, ["post", "/emails", "--json", "{}"])

    assert (read.is_write, read.command_type) == (False, "GET")
    assert (write.is_write, write.command_type) == (True, "POST /emails")
    assert write.argv == (*REST_HELPER_ARGV, "POST", "/emails", "--json", "{}")


def test_rest_refuses_an_unknown_method_and_a_missing_path() -> None:
    with pytest.raises(InvalidConnectorCallError):
        plan_call(RESEND, ["TRACE", "/x"])
    with pytest.raises(InvalidConnectorCallError):
        plan_call(RESEND, ["GET"])


def test_an_sdk_script_is_always_one_write_type() -> None:
    plan = plan_call(OPENAI, ["-c", "print(1)"])

    assert plan.argv == ("python3", "-c", "print(1)")
    assert (plan.is_write, plan.command_type) == (True, SDK_SCRIPT_COMMAND_TYPE)


def test_too_many_args_or_a_nul_byte_is_refused() -> None:
    with pytest.raises(InvalidConnectorCallError):
        plan_call(GH, ["x"] * (MAX_CONNECTOR_ARGS + 1))
    with pytest.raises(InvalidConnectorCallError):
        plan_call(GH, ["api", "a\0b"])
