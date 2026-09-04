"""Outlook-specific hooks: file attachments for string-form path params.

OUTLOOK_SEND_EMAIL and OUTLOOK_CREATE_DRAFT take ``attachment`` as a path
string Composio fetches itself — but it cannot read sandbox ``/workspace/...``
paths (auto-upload is off), so a workspace-local value would fail downstream.
This hook mints a minutes-lived single-purpose grant URL Composio fetches
during execution instead. http(s) values and missing keys pass through
untouched; a list is minted per item, since every element reaches Composio the
same way a bare string would. Mint failures abort loud — never send mail
missing its file.
"""

from typing import TypeGuard

from composio.types import Tool, ToolExecuteParams

from app.constants.email import ATTACHMENTS_NO_USER_ERROR
from app.services.share_service import mint_share_url

from .registry import HookAbortError, register_before_hook, register_schema_modifier


@register_schema_modifier(tools=["OUTLOOK_SEND_EMAIL", "OUTLOOK_CREATE_DRAFT"])
def outlook_hide_user_id_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Strip ``user_id`` from the Outlook send schemas' agent-facing shape.

    Same rationale as Gmail's modifier: the mailbox is fixed by the connected
    account, and — critically — hooks below read identity from params. A
    model-supplied ``user_id`` must never reach them (spoof vector for
    per-user file grants), so the key is removed here, not trusted downstream.
    """
    input_params: object = schema.input_parameters
    if not isinstance(input_params, dict):
        return schema
    props = input_params.get("properties")
    if isinstance(props, dict):
        props.pop("user_id", None)
    required = input_params.get("required")
    if isinstance(required, list) and "user_id" in required:
        required.remove("user_id")
    return schema


def _needs_grant(value: object) -> TypeGuard[str]:
    """A path string Composio would have to read from our sandbox itself."""
    return isinstance(value, str) and not value.startswith(("http://", "https://"))


def _mint_attachment(value: object, *, user_id: str, tool: str, toolkit: str) -> object:
    """A fetchable grant URL for a workspace-local path; anything else unchanged."""
    if not _needs_grant(value):
        return value
    try:
        return mint_share_url(user_id=user_id, workspace_path=value, tool=tool, toolkit=toolkit)
    except Exception as exc:
        raise HookAbortError(f"Could not attach '{value}': {exc}") from exc


@register_before_hook(tools=["OUTLOOK_SEND_EMAIL", "OUTLOOK_CREATE_DRAFT"])
def outlook_attachment_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Swap workspace-local ``attachment`` paths for grant URLs Composio can fetch."""
    arguments: object = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return params
    raw = arguments.get("attachment")
    values = raw if isinstance(raw, list) else [raw]
    if not any(_needs_grant(value) for value in values):
        return params

    user_id = params.get("user_id")
    if not user_id:
        raise HookAbortError(ATTACHMENTS_NO_USER_ERROR)

    minted = [
        _mint_attachment(value, user_id=user_id, tool=tool, toolkit=toolkit) for value in values
    ]
    arguments["attachment"] = minted if isinstance(raw, list) else minted[0]
    params["arguments"] = arguments  # pragma: no mutate
    return params
