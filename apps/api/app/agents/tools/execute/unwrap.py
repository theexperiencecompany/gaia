"""Unwrap an execute-proxied call to its real (name, args).

The single definition every name-keyed seam imports — the HIL gate, the
streaming formatter, analytics, and the tool node's timeout check must agree on
what a proxied call "is", and five private copies of this logic would drift.
"""

import json
from typing import TypedDict, cast

from app.constants.execute import EXECUTE_TOOL_NAME


class ExecuteCallArgs(TypedDict, total=False):
    """The execute proxy's own args as the model sent them: unvalidated, so every value is object."""

    task_description: object
    tool_name: object
    data: object
    account: object


def decode_json_object(value: object) -> object:
    """Read a JSON-encoded object as the object; anything else is returned unchanged.

    Models often JSON-encode execute's data, and the proxy runs it, so every
    seam that reads the args must decode it the same way.
    """
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(decoded, dict):
            return decoded
    return value


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
    data = decode_json_object(execute_args.get("data"))
    return real_name, data if isinstance(data, dict) else {}


def execute_call_account(name: str, args: dict[str, object]) -> str | None:
    """The connected account an execute call names, or None for the primary / a non-execute call."""
    if name != EXECUTE_TOOL_NAME:
        return None
    execute_args: ExecuteCallArgs = cast(ExecuteCallArgs, args)
    account = execute_args.get("account")
    return account if isinstance(account, str) and account else None
