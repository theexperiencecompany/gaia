"""Outlook-specific hooks: file attachments for string-form path params.

OUTLOOK_SEND_EMAIL and OUTLOOK_CREATE_DRAFT take ``attachment`` as a path
string Composio fetches itself — but it cannot read sandbox ``/workspace/...``
paths (auto-upload is off), so a workspace-local value would fail downstream.
This hook mints a minutes-lived single-purpose grant URL Composio fetches
during execution instead. http(s) values, lists, and missing keys pass through
untouched; mint failures abort loud — never send mail missing its file.
"""

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


@register_before_hook(tools=["OUTLOOK_SEND_EMAIL", "OUTLOOK_CREATE_DRAFT"])
def outlook_attachment_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Swap a workspace-local ``attachment`` path for a grant URL Composio can fetch."""
    arguments: object = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return params
    raw = arguments.get("attachment")
    if not isinstance(raw, str) or raw.startswith(("http://", "https://")):
        return params

    user_id = params.get("user_id")
    if not user_id:
        raise HookAbortError(ATTACHMENTS_NO_USER_ERROR)

    try:
        arguments["attachment"] = mint_share_url(
            user_id=user_id, workspace_path=raw, tool=tool, toolkit=toolkit
        )
    except HookAbortError:
        raise
    except Exception as exc:
        raise HookAbortError(f"Could not attach '{raw}': {exc}") from exc
    params["arguments"] = arguments  # pragma: no mutate
    return params
