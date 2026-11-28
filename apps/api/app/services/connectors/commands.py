"""Turn a connector call's args into the argv the runner executes, and say whether it writes.

A call is a read only when the spec proves it: a listed read subcommand with no
write flag (CLI), or a safe HTTP method (REST). Everything else is a write, and
its command type is what one remembered approval covers.
"""

from dataclasses import dataclass
import re

from app.constants.connectors import (
    MAX_CONNECTOR_ARG_CHARS,
    MAX_CONNECTOR_ARGS,
    SDK_SCRIPT_COMMAND_TYPE,
)
from app.models.connector_models import ConnectorKind, ConnectorSpec, SdkRuntime
from app.services.connectors.rest_helper import REST_HELPER_ARGV

_SUBCOMMAND_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_WRITE_TYPE_WORDS = 2
_HELP_FLAGS = frozenset({"--help", "-h"})
_HELP_SUBCOMMAND = "help"
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_REST_METHODS = _READ_METHODS | frozenset({"POST", "PUT", "PATCH", "DELETE"})
_SDK_BINARIES = {SdkRuntime.PYTHON: "python3", SdkRuntime.NODE: "node"}
_NO_SUBCOMMAND = "run"


class InvalidConnectorCallError(ValueError):
    """Raised when args cannot form a call: too many, too long, or not a valid request."""


@dataclass(frozen=True)
class CallPlan:
    argv: tuple[str, ...]
    is_write: bool
    # What a remembered "always allow" covers, e.g. "pr create" or "POST /emails".
    command_type: str


def _check_args(args: list[str]) -> None:
    if len(args) > MAX_CONNECTOR_ARGS:
        raise InvalidConnectorCallError(f"at most {MAX_CONNECTOR_ARGS} args per call")
    for arg in args:
        if len(arg) > MAX_CONNECTOR_ARG_CHARS:
            raise InvalidConnectorCallError(f"an arg is longer than {MAX_CONNECTOR_ARG_CHARS}")
        if "\0" in arg:
            raise InvalidConnectorCallError("an arg contains a NUL byte")


def _subcommand_words(args: list[str]) -> list[str]:
    """Return the leading subcommand words, skipping flags and the arg after a bare flag.

    The arg after a bare flag may be its value, so it never counts as a subcommand.
    """
    words: list[str] = []
    after_flag = False
    for arg in args:
        if arg.startswith("-"):
            after_flag = "=" not in arg
            continue
        if after_flag:
            after_flag = False
            continue
        if not _SUBCOMMAND_RE.fullmatch(arg):
            break
        words.append(arg)
    return words


def _is_bare_flag(arg: str) -> bool:
    return arg.startswith("-") and "=" not in arg


def _is_help(args: list[str], words: list[str]) -> bool:
    """Say whether the call asks for help: the help subcommand, or a help flag last and not a value."""
    if words[:1] == [_HELP_SUBCOMMAND]:
        return True
    if not args or args[-1] not in _HELP_FLAGS:
        return False
    return len(args) < 2 or not _is_bare_flag(args[-2])


def _is_write_flag(arg: str, flag: str) -> bool:
    """Match a long flag as --flag or --flag=v, and a short one also with its value attached (-XPOST)."""
    if flag.startswith("--"):
        return arg.split("=", 1)[0] == flag
    return arg.startswith(flag) and not arg.startswith("--")


def _has_write_flag(args: list[str], write_flags: list[str]) -> bool:
    return any(
        _is_write_flag(arg, flag) for arg in args if arg.startswith("-") for flag in write_flags
    )


def _listed_read(words: list[str], read_commands: list[str]) -> str | None:
    """Return the longest read prefix the words start with, or None when none does."""
    prefixes: list[list[str]] = [command.split() for command in read_commands]
    matches: list[list[str]] = [p for p in prefixes if p and words[: len(p)] == p]
    if not matches:
        return None
    longest = max(len(match) for match in matches)
    return " ".join(next(match for match in matches if len(match) == longest))


def _plan_cli(spec: ConnectorSpec, command: str, args: list[str]) -> CallPlan:
    argv = (command, *args)
    words = _subcommand_words(args)
    if _is_help(args, words):
        return CallPlan(argv=argv, is_write=False, command_type="help")
    read = _listed_read(words, spec.risk.read_commands)
    if read is not None and not _has_write_flag(args, spec.risk.write_flags):
        return CallPlan(argv=argv, is_write=False, command_type=read)
    command_type = " ".join(words[:_WRITE_TYPE_WORDS]) or _NO_SUBCOMMAND
    return CallPlan(argv=argv, is_write=True, command_type=command_type)


def _plan_rest(args: list[str]) -> CallPlan:
    if len(args) < 2:
        raise InvalidConnectorCallError("a REST call is METHOD PATH [options]")
    method = args[0].upper()
    if method not in _REST_METHODS:
        raise InvalidConnectorCallError(f"unsupported HTTP method {args[0]!r}")
    path = args[1]
    argv = (*REST_HELPER_ARGV, method, *args[1:])
    if method in _READ_METHODS:
        return CallPlan(argv=argv, is_write=False, command_type=method)
    segment = path.lstrip("/").split("/", 1)[0].split("?", 1)[0]
    return CallPlan(argv=argv, is_write=True, command_type=f"{method} /{segment}")


def plan_call(spec: ConnectorSpec, args: list[str]) -> CallPlan:
    """Return the argv and read/write class of one call against a connector."""
    _check_args(args)
    match spec.kind:
        case ConnectorKind.CLI:
            if spec.command is None:
                raise InvalidConnectorCallError("cli connector without a command")
            return _plan_cli(spec, spec.command, args)
        case ConnectorKind.REST:
            return _plan_rest(args)
        case ConnectorKind.SDK:
            if spec.sdk_runtime is None:
                raise InvalidConnectorCallError("sdk connector without a runtime")
            argv = (_SDK_BINARIES[spec.sdk_runtime], *args)
            return CallPlan(argv=argv, is_write=True, command_type=SDK_SCRIPT_COMMAND_TYPE)
