"""File-upload capability for every Composio tool, not one toolkit.

Composio's native file param (an ``{name, mimetype, s3key}`` object the model
cannot produce — it has no s3key) is unusable by an agent. Rather than teaching
each toolkit its own workaround, this module gives the model one friendly
``attachments`` reference list everywhere it can work:

- schema modifier (all tools, scoped by shape): any tool whose schema carries
  Composio's ``file_uploadable`` marker gets that param swapped for
  ``attachments``, and the swap is recorded per tool. Outlook, Slack uploads,
  and future toolkits need zero per-toolkit code — the marked param is found by
  marker, not by name.
- before-hook (only the tools we swapped): ``attachments`` references are
  uploaded and written back under the tool's own native param name before it
  runs. A tool we never swapped is left completely alone, even if it happens to
  take an ``attachments`` argument of its own.

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

# Tool slug -> the native upload param name this module swapped out of its
# schema. Written by the schema modifier when tools are bound, read by the
# before-hook at execution: it is the only evidence that ``attachments`` on a
# call is the param we injected rather than one the tool already had.
_swapped_upload_params: dict[str, str] = {}


class AttachmentDisplay(TypedDict):
    """Per-file metadata safe for display/logging (never the s3key)."""

    name: str
    mimetype: str


def _is_file_upload_node(node: object) -> bool:
    """``file_uploadable: True`` on this node itself, its variants, or its items.

    ``FileUploadable`` emits the marker onto the field's own schema node, so the
    marker is read there — through ``anyOf``/``oneOf``/``allOf`` (an optional
    param) and ``items`` (a list of files), which are still the same param.

    Deliberately does NOT descend into ``properties``: a composite param that
    merely *contains* a file field is not one we can swap. The modifier deletes
    the whole property it claims and the before-hook writes a bare
    ``{name, mimetype, s3key}`` back under it, so claiming e.g. a
    ``message: {text, file}`` param would delete the param the tool needs and
    hand it a shape it cannot accept.
    """
    if not isinstance(node, dict):
        return False
    if node.get("file_uploadable", False):
        return True
    for key in ("anyOf", "oneOf", "allOf"):
        variants = node.get(key)
        if isinstance(variants, list) and any(_is_file_upload_node(v) for v in variants):
            return True
    items = node.get("items")
    if isinstance(items, dict) and _is_file_upload_node(items):
        return True
    return isinstance(items, list) and any(_is_file_upload_node(i) for i in items)


def _looks_like_legacy_upload_param(native: dict[str, Any]) -> bool:
    """Unmarked object carrying FileUploadable's s3key fingerprint.

    Deliberately NOT bare ``{"type": "object"}``: Graph-style passthrough
    objects (OUTLOOK_ADD_MAIL_ATTACHMENT's contentBytes/contentType shape) are
    also bare objects, and swapping one would corrupt the call. An unmarked
    object is only claimed when it carries the s3key the uploader produces.
    """
    properties = native.get("properties")
    return isinstance(properties, dict) and "s3key" in properties


def find_native_upload_param(schema: Tool) -> str | None:
    """Name of the tool's native file-upload param, or None if it has none.

    The marker is looked for under *every* property, not just one called
    ``attachment``: Composio names the param per tool, so a name check would
    silently skip every toolkit that picked a different one.
    """
    input_params: object = schema.input_parameters
    if not isinstance(input_params, dict):
        return None
    props = input_params.get("properties")
    if not isinstance(props, dict):
        return None
    if FRIENDLY_UPLOAD_PARAM in props:
        return None
    for name, prop in props.items():
        if _is_file_upload_node(prop):
            return str(name)
    # Legacy fallback: marker presence in live schemas is unverifiable offline,
    # so an s3key-fingerprinted object still swaps (logged) instead of silently
    # dropping attach capability. Scoped to the conventional param name — an
    # unmarked s3key shape anywhere in the schema is too weak a signal to act
    # on. Remove once live-verified.
    native = props.get(NATIVE_UPLOAD_PARAM)
    if isinstance(native, dict) and _looks_like_legacy_upload_param(native):
        log.debug(
            f"{LogTag.COMPOSIO} Swapping unmarked attachment param",
        )
        return NATIVE_UPLOAD_PARAM
    return None


@register_schema_modifier()
def file_upload_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Expose friendly ``attachments`` instead of Composio's raw upload param.

    Runs for every tool but only acts on genuine file-upload params
    (``file_uploadable`` marker, or the legacy s3key shape). Scalar ids,
    Graph-style passthrough objects, Slack blocks/strings, and already-swapped
    schemas pass through untouched.
    """
    native_param = find_native_upload_param(schema)
    if native_param is None:
        return schema
    input_params = schema.input_parameters
    assert isinstance(input_params, dict)  # narrowed by find_native_upload_param
    props = input_params.get("properties")
    assert isinstance(props, dict)  # narrowed by find_native_upload_param
    props.pop(native_param)
    # Built fresh per call from AttachmentReference, so a field change reaches
    # every tool with no second edit (and no shared-mutable default).
    props[FRIENDLY_UPLOAD_PARAM] = attachment_references_param_schema(
        EMAIL_ATTACHMENTS_PARAM_DESCRIPTION
    )
    required = input_params.get("required")
    if isinstance(required, list) and native_param in required:
        required.remove(native_param)
    _swapped_upload_params[tool] = native_param
    return schema


def _display_from_native(native: object) -> list[AttachmentDisplay]:
    """Display metadata off an already-resolved native upload arg."""
    items = native if isinstance(native, list) else [native]
    return [
        {"name": item.get("name") or "", "mimetype": item.get("mimetype") or ""}
        for item in items
        if isinstance(item, dict)
    ]


def resolve_tool_attachments(
    tool: str, toolkit: str, params: ToolExecuteParams, *, native_param: str
) -> list[AttachmentDisplay]:
    """Turn friendly ``attachments`` references into the tool's native upload arg.

    Uploads each referenced file and rewrites ``arguments`` in place, collapsing
    one file to a bare object (Composio accepts a single FileUploadable or a
    list; the bare form is the widely accepted one). Raises ``HookAbortError``
    instead of running the tool with a missing file — a silently attachment-less
    send would be a data-loss bug.

    Callers must already know ``attachments`` is the param this module injected
    (the Gmail hook by tool identity, the generic hook via
    ``_swapped_upload_params``), so anything unexpected in it aborts rather than
    passing through. Order-independent: whichever hook runs first consumes
    ``attachments``; the other derives display from the resolved native arg.
    """
    arguments = params.get("arguments", {})
    raw = arguments.get(FRIENDLY_UPLOAD_PARAM)
    # A missing key, an explicit None, or an empty list is a genuine no-op. A
    # *present* but malformed value ("" / {} / a bare string) must abort — a
    # truthiness check here would swallow it and send the mail attachment-less.
    if raw is None or raw == []:
        return _display_from_native(arguments.get(native_param))
    if isinstance(raw, dict):
        raw = [raw]
    elif not isinstance(raw, list):
        raise HookAbortError(ATTACHMENTS_NOT_LIST_ERROR)

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

    arguments[native_param] = resolved[0] if len(resolved) == 1 else resolved
    del arguments[FRIENDLY_UPLOAD_PARAM]
    # Redundant: `arguments` is already `params["arguments"]` by reference.
    params["arguments"] = arguments  # pragma: no mutate
    return [{"name": a["name"], "mimetype": a["mimetype"]} for a in resolved]


def swapped_upload_param(tool: str) -> str | None:
    """The native upload param this module swapped out of ``tool``'s schema, if any.

    The single source of truth for that name: Composio names the param per tool,
    so any caller that hardcodes one is guessing. ``None`` means we never swapped
    this tool, and an ``attachments`` argument on it is the tool's own.
    """
    return _swapped_upload_params.get(tool)


@register_before_hook()
def file_upload_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Resolve friendly ``attachments`` on the tools whose schema we swapped.

    A tool this module never swapped is left untouched — its ``attachments``
    argument, if any, belongs to the tool and rewriting it would corrupt the
    call. For the tools we did swap, a reference that fails to resolve aborts
    via ``HookAbortError`` (re-raised by the registry, never swallowed).
    """
    native_param = swapped_upload_param(tool)
    if native_param is None:
        return params
    display = resolve_tool_attachments(tool, toolkit, params, native_param=native_param)
    if display:
        log.set(attachment_count=len(display))  # pragma: no mutate
    return params
