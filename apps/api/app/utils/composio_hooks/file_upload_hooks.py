"""File-upload capability for every Composio tool, not one toolkit.

Composio's native file param (``attachment`` of ``{name, mimetype, s3key}``) is
unusable by the model — it cannot produce an s3key. Rather than teaching each
toolkit its own workaround, this module gives the model one friendly
``attachments`` reference list everywhere it can work:

- schema modifier (all tools, scoped by shape): any tool whose schema carries
  Composio's ``file_uploadable`` marker gets its native ``attachment`` swapped
  for ``attachments``. Outlook, Slack uploads, and future toolkits need zero
  per-toolkit code.
- before-hook (all tools, scoped by evidence): ``attachments`` references are
  uploaded and rewritten to ``attachment`` before the tool runs. Anything that
  is not our shape (Slack message blocks, legacy strings) passes through
  untouched — the hook only engages on file evidence (``workspace_path``/``url``).

Per-surface hooks (Gmail's compose card) keep only their display logic and call
``resolve_tool_attachments`` for the shared resolution.
"""

from typing import Any, TypedDict

from composio.types import Tool, ToolExecuteParams
from pydantic import BaseModel, ValidationError

from app.constants.email import (
    ATTACHMENTS_NO_USER_ERROR,
    ATTACHMENTS_NOT_LIST_ERROR,
    EMAIL_ATTACHMENTS_PARAM_DESCRIPTION,
)
from app.constants.log_tags import LogTag
from app.models.mail_models import (
    AttachmentReference,
    ComposioAttachment,
    attachment_references_param_schema,
)
from app.services.composio.attachments import resolve_attachments_sync
from app.utils.errors import AppError
from shared.py.wide_events import log

from .registry import HookAbortError, register_before_hook, register_schema_modifier

NATIVE_UPLOAD_PARAM = "attachment"
FRIENDLY_UPLOAD_PARAM = "attachments"


class AttachmentDisplay(TypedDict):
    """Per-file metadata safe for display/logging (never the s3key)."""

    name: str
    mimetype: str


def _subtree_has_file_marker(node: object) -> bool:
    """Recursive ``file_uploadable: True`` scan (anyOf/oneOf/allOf/properties/items).

    Mirrors Composio's own ``FileHelper._has_file_property``: ``FileUploadable``
    emits the marker into the schema, so this is the authoritative signal — it
    survives renames and reshapes that a param-name heuristic cannot.
    """
    if not isinstance(node, dict):
        return False
    if node.get("file_uploadable", False):
        return True
    for key in ("anyOf", "oneOf", "allOf"):
        variants = node.get(key)
        if isinstance(variants, list) and any(
            _subtree_has_file_marker(v) for v in variants
        ):
            return True
    properties = node.get("properties")
    if isinstance(properties, dict) and any(
        _subtree_has_file_marker(v) for v in properties.values()
    ):
        return True
    items = node.get("items")
    if isinstance(items, dict) and _subtree_has_file_marker(items):
        return True
    return isinstance(items, list) and any(_subtree_has_file_marker(i) for i in items)


def _looks_like_legacy_upload_param(native: dict[str, Any]) -> bool:
    """Unmarked object carrying FileUploadable's s3key fingerprint.

    Deliberately NOT bare ``{"type": "object"}``: Graph-style passthrough
    objects (OUTLOOK_ADD_MAIL_ATTACHMENT's contentBytes/contentType shape) are
    also bare objects, and swapping one would corrupt the call. An unmarked
    object is only claimed when it carries the s3key the uploader produces.
    """
    properties = native.get("properties")
    return isinstance(properties, dict) and "s3key" in properties


def has_native_upload_param(schema: Tool) -> bool:
    """Whether the schema carries Composio's native file-upload param."""
    input_params: object = schema.input_parameters
    if not isinstance(input_params, dict):
        return False
    props = input_params.get("properties")
    if not isinstance(props, dict):
        return False
    if FRIENDLY_UPLOAD_PARAM in props:
        return False
    native = props.get(NATIVE_UPLOAD_PARAM)
    if not isinstance(native, dict):
        return False
    if _subtree_has_file_marker(native):
        return True
    # Legacy fallback: marker presence in live schemas is unverifiable offline,
    # so an s3key-fingerprinted object still swaps (logged) instead of silently
    # dropping attach capability. Remove once live-verified.
    if _looks_like_legacy_upload_param(native):
        log.debug(
            f"{LogTag.COMPOSIO} Swapping unmarked attachment param",
        )
        return True
    return False


@register_schema_modifier()
def file_upload_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Expose friendly ``attachments`` instead of Composio's raw ``attachment``.

    Runs for every tool but only acts on genuine file-upload params
    (``file_uploadable`` marker, or the legacy s3key shape). Scalar ids,
    Graph-style passthrough objects, Slack blocks/strings, and already-swapped
    schemas pass through untouched.
    """
    if not has_native_upload_param(schema):
        return schema
    input_params = schema.input_parameters
    assert isinstance(input_params, dict)  # narrowed by has_native_upload_param
    props = input_params.get("properties")
    assert isinstance(props, dict)  # narrowed by has_native_upload_param
    props.pop(NATIVE_UPLOAD_PARAM)
    # Built fresh per call from AttachmentReference, so a field change reaches
    # every tool with no second edit (and no shared-mutable default).
    props[FRIENDLY_UPLOAD_PARAM] = attachment_references_param_schema(
        EMAIL_ATTACHMENTS_PARAM_DESCRIPTION
    )
    required = input_params.get("required")
    if isinstance(required, list) and NATIVE_UPLOAD_PARAM in required:
        required.remove(NATIVE_UPLOAD_PARAM)
    return schema


def _has_file_evidence(item: object) -> bool:
    """Whether the item looks like our file reference (not a foreign payload).

    Key/attribute *presence* (not values) is the discriminator: Slack blocks and
    similar never carry ``workspace_path``/``url`` at the top level, while our
    references — dicts from REST or Composio-generated Pydantic models from the
    agent path — always do, even when their values are invalid (those still fail
    loud at validation instead of slipping through).
    """
    if isinstance(item, BaseModel):
        fields = type(item).model_fields
        return "workspace_path" in fields or "url" in fields
    return isinstance(item, dict) and ("workspace_path" in item or "url" in item)


def _display_from_native(native: object) -> list[AttachmentDisplay]:
    """Display metadata off an already-resolved native ``attachment`` arg."""
    items = native if isinstance(native, list) else [native]
    return [
        {"name": item.get("name") or "", "mimetype": item.get("mimetype") or ""}
        for item in items
        if isinstance(item, dict)
    ]


def resolve_tool_attachments(
    tool: str, toolkit: str, params: ToolExecuteParams, *, strict: bool
) -> list[AttachmentDisplay]:
    """Turn friendly ``attachments`` references into Composio's ``attachment`` arg.

    Uploads each referenced file and rewrites ``arguments`` in place, collapsing
    one file to a bare object (Composio accepts a single FileUploadable or a
    list; the bare form is the widely accepted one). Raises ``HookAbortError``
    instead of running the tool with a missing file — a silently attachment-less
    send would be a data-loss bug.

    ``strict`` is the Gmail contract: abort on anything unexpected in
    ``attachments``. The generic hook runs lenient (``strict=False``) so foreign
    payloads sharing the key name pass through untouched. Order-independent:
    whichever hook runs first consumes ``attachments``; the other derives
    display from the resolved ``attachment``.
    """
    arguments = params.get("arguments", {})
    raw = arguments.get(FRIENDLY_UPLOAD_PARAM)
    if not raw:
        return _display_from_native(arguments.get(NATIVE_UPLOAD_PARAM))
    if isinstance(raw, dict):
        if not _has_file_evidence(raw):
            if strict:
                raise HookAbortError(ATTACHMENTS_NOT_LIST_ERROR)
            return []
        raw = [raw]
    elif not isinstance(raw, list):
        if strict:
            raise HookAbortError(ATTACHMENTS_NOT_LIST_ERROR)
        return []
    if not strict and not any(_has_file_evidence(item) for item in raw):
        return []

    user_id = params.get("user_id")
    if not user_id:
        raise HookAbortError(ATTACHMENTS_NO_USER_ERROR)

    try:
        # Items arrive as dicts (REST) or as Composio's schema-generated Pydantic
        # models (agent path, where langchain coerces the tool args) — normalise
        # both to a plain mapping before validating into our reference model.
        references = [
            AttachmentReference.model_validate(
                item.model_dump() if isinstance(item, BaseModel) else item
            )
            for item in raw
        ]
    except ValidationError as exc:
        raise HookAbortError(f"Invalid attachment reference: {exc}") from exc

    try:
        resolved: list[ComposioAttachment] = resolve_attachments_sync(
            user_id, references, tool=tool, toolkit=toolkit
        )
    except AppError as exc:
        raise HookAbortError(exc.message) from exc

    arguments[NATIVE_UPLOAD_PARAM] = resolved[0] if len(resolved) == 1 else resolved
    del arguments[FRIENDLY_UPLOAD_PARAM]
    # Redundant: `arguments` is already `params["arguments"]` by reference.
    params["arguments"] = arguments  # pragma: no mutate
    return [{"name": a["name"], "mimetype": a["mimetype"]} for a in resolved]


@register_before_hook()
def file_upload_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Resolve friendly ``attachments`` on any tool that carries them.

    Lenient by design: foreign ``attachments`` payloads are not ours to judge,
    so they pass through untouched. Genuine file references that fail still
    abort via ``HookAbortError`` (re-raised by the registry, never swallowed).
    """
    display = resolve_tool_attachments(tool, toolkit, params, strict=False)
    if display:
        log.set(attachment_count=len(display))  # pragma: no mutate
    return params
