"""Unwrap an execute-proxied call to its real (name, args).

The single definition every name-keyed seam imports — the HIL gate, the
streaming formatter, analytics, and the tool node's timeout check must agree on
what a proxied call "is", and five private copies of this logic would drift.
"""

from typing import Literal, TypedDict, cast

from app.constants.execute import EXECUTE_TOOL_NAME
from app.utils.json_args import decode_json_container

# The execute args that describe the call rather than the tool's own arguments.
ExecuteCallNote = Literal["account", "amends"]


class ExecuteCallArgs(TypedDict, total=False):
    """The execute proxy's own args as the model sent them: unvalidated, so every value is object."""

    task_description: object
    tool_name: object
    data: object
    account: object
    amends: object


def unwrap_execute_call(name: str, args: dict[str, object]) -> tuple[str, dict[str, object]]:
    """The REAL (name, args) of a call, seen through the execute proxy.

    An execute call carries its actual tool in ``args["tool_name"]``/``args["data"]``.
    A malformed proxy call (no usable tool_name) is returned as-is: it is gated,
    displayed and dispatched under its own name, and dispatch rejects it with a
    structured unknown_tool error.
    """
    if name != EXECUTE_TOOL_NAME:
        return name, args
    execute_args: ExecuteCallArgs = cast(ExecuteCallArgs, args)
    real_name = execute_args.get("tool_name")
    if not isinstance(real_name, str) or not real_name:
        return name, args
    # The proxy runs a JSON-encoded data as its object, so every seam reads it that way.
    data = decode_json_container(execute_args.get("data"))
    return real_name, data if isinstance(data, dict) else {}


def execute_call_note(name: str, args: dict[str, object], note: ExecuteCallNote) -> str | None:
    """The text an execute call carries in one of its own notes, or None when it names none.

    account: the connected account it acts as (None is the primary). amends: the approval
    id this call redoes with the user's change applied.
    """
    if name != EXECUTE_TOOL_NAME:
        return None
    value = cast(ExecuteCallArgs, args).get(note)
    return value if isinstance(value, str) and value else None
