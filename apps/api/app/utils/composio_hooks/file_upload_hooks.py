"""File-upload capability for every Composio tool, not one toolkit.

Composio's native file param (an {name, mimetype, s3key} object the model cannot
produce) is unusable by an agent. A schema modifier finds any tool whose schema carries
the file_uploadable marker and swaps that param for a friendly attachments list,
recording the swap per tool; a before-hook then uploads referenced attachments and writes
them back under the tool's own native param name before it runs, leaving a tool that was
never swapped completely alone even if it takes an attachments argument of its own. New
toolkits need zero per-toolkit code — the marker, not the param name, decides what gets
swapped. Per-surface hooks (Gmail's compose card) reuse resolve_tool_attachments.
"""

from typing import TypedDict

from composio.types import Tool, ToolExecuteParams
from pydantic import BaseModel, ConfigDict, ValidationError

from app.constants.email import (
    ATTACHMENTS_NO_USER_ERROR,
    ATTACHMENTS_NOT_LIST_ERROR,
    EMAIL_ATTACHMENTS_PARAM_DESCRIPTION,
)
from app.constants.log_tags import LogTag
from app.models.integrations.composio_hooks import ComposioToolCall, JsonSchemaNode
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

# Tool slug -> native upload param name swapped out of its schema; the only
# evidence, read by the before-hook, that attachments on a call is injected
# rather than the tool's own.
_swapped_upload_params: dict[str, str] = {}


class AttachmentDisplay(TypedDict):
    """Per-file metadata safe for display/logging (never the s3key)."""

    name: str
    mimetype: str


class _UploadedFile(BaseModel):
    """The display half of a resolved upload arg: a ComposioAttachment or an earlier hook's native-param value."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    mimetype: str | None = None

    def display(self) -> AttachmentDisplay:
        return {"name": self.name or "", "mimetype": self.mimetype or ""}


def _is_file_upload_node(node: JsonSchemaNode) -> bool:
    """Return True if node, an anyOf/oneOf/allOf variant, or its items carry file_uploadable.

    FileUploadable emits the marker onto the field's own schema node. Deliberately does not
    descend into properties: the modifier deletes the whole property it claims and the
    before-hook writes a bare {name, mimetype, s3key} back under it, so claiming a composite
    like message: {text, file} would delete a param the tool needs and hand it a bad shape.
    """
    if node.file_uploadable:
        return True
    for variants in (node.anyOf, node.oneOf, node.allOf):
        if variants and any(_is_file_upload_node(v) for v in variants):
            return True
    items = node.items
    if isinstance(items, JsonSchemaNode):
        return _is_file_upload_node(items)
    return bool(items) and any(_is_file_upload_node(i) for i in items)


def _looks_like_legacy_upload_param(native: JsonSchemaNode) -> bool:
    """Unmarked object carrying FileUploadable's s3key fingerprint.

    Deliberately NOT bare {"type": "object"}: Graph-style passthrough
    objects (OUTLOOK_ADD_MAIL_ATTACHMENT's contentBytes/contentType shape) are
    also bare objects, and swapping one would corrupt the call. An unmarked
    object is only claimed when it carries the s3key the uploader produces.
    """
    return native.properties is not None and "s3key" in native.properties


def find_native_upload_param(schema: Tool) -> str | None:
    """Name of the tool's native file-upload param, or None if it has none.

    The marker is looked for under *every* property, not just one called
    attachment: Composio names the param per tool, so a name check would
    silently skip every toolkit that picked a different one.
    """
    input_params = JsonSchemaNode.parse(schema.input_parameters)
    props = input_params.properties if input_params else None
    if props is None:
        return None
    if FRIENDLY_UPLOAD_PARAM in props:
        return None
    for name, prop in props.items():
        if _is_file_upload_node(prop):
            return name
    # Legacy fallback: marker presence is unverifiable offline, so an
    # s3key-fingerprinted object at the conventional param name still swaps
    # (logged); remove once live-verified.
    native = props.get(NATIVE_UPLOAD_PARAM)
    if native is not None and _looks_like_legacy_upload_param(native):
        log.debug(
            f"{LogTag.COMPOSIO} Swapping unmarked attachment param",
        )
        return NATIVE_UPLOAD_PARAM
    return None


@register_schema_modifier()
def file_upload_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Expose friendly attachments instead of Composio's raw upload param.

    Runs for every tool but only acts on genuine file-upload params
    (file_uploadable marker, or the legacy s3key shape). Scalar ids,
    Graph-style passthrough objects, Slack blocks/strings, and already-swapped
    schemas pass through untouched.
    """
    native_param = find_native_upload_param(schema)
    if native_param is None:
        return schema
    input_params = JsonSchemaNode.parse(schema.input_parameters)
    assert input_params is not None  # narrowed by find_native_upload_param
    props = input_params.properties
    assert props is not None  # narrowed by find_native_upload_param
    props.pop(native_param)
    # Built fresh per call from AttachmentReference, so a field change reaches
    # every tool with no second edit (and no shared-mutable default).
    props[FRIENDLY_UPLOAD_PARAM] = JsonSchemaNode.model_validate(
        attachment_references_param_schema(EMAIL_ATTACHMENTS_PARAM_DESCRIPTION)
    )
    if input_params.required and native_param in input_params.required:
        input_params.required.remove(native_param)
    schema.input_parameters = input_params.as_schema()
    _swapped_upload_params[tool] = native_param
    return schema


def _display_from_native(native: object) -> list[AttachmentDisplay]:
    """Display metadata off an already-resolved native upload arg."""
    items = native if isinstance(native, list) else [native]
    return [
        _UploadedFile.model_validate(item).display() for item in items if isinstance(item, dict)
    ]


def resolve_tool_attachments(
    tool: str, toolkit: str, params: ToolExecuteParams, *, native_param: str
) -> list[AttachmentDisplay]:
    """Turn friendly attachments references into the tool's native upload arg, in place.

    Collapses a single file to a bare object (Composio accepts one FileUploadable or a list).
    Raises HookAbortError rather than running the tool with a missing file — a silently
    attachment-less send is data loss — so callers must already know attachments is the param
    this module injected. Order-independent: whichever hook runs first consumes attachments.
    """
    call = ComposioToolCall.model_validate(params)
    arguments = call.arguments
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

    if not call.user_id:
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
            call.user_id, references, tool=tool, toolkit=toolkit
        )
    except AppError as exc:
        raise HookAbortError(exc.message) from exc

    arguments[native_param] = resolved[0] if len(resolved) == 1 else resolved
    del arguments[FRIENDLY_UPLOAD_PARAM]
    # `arguments` is the call view's copy of the bag: the rewrite reaches the
    # tool only through this write-back.
    params["arguments"] = arguments
    return [_UploadedFile.model_validate(a).display() for a in resolved]


def swapped_upload_param(tool: str) -> str | None:
    """Return the native upload param this module swapped out of tool's schema, if any.

    The single source of truth for that name: Composio names the param per tool,
    so any caller that hardcodes one is guessing. None means we never swapped
    this tool, and an attachments argument on it is the tool's own.
    """
    return _swapped_upload_params.get(tool)


@register_before_hook()
def file_upload_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Resolve friendly attachments on the tools whose schema we swapped.

    A tool this module never swapped is left untouched — its attachments
    argument, if any, belongs to the tool and rewriting it would corrupt the
    call. For the tools we did swap, a reference that fails to resolve aborts
    via HookAbortError (re-raised by the registry, never swallowed).
    """
    native_param = swapped_upload_param(tool)
    if native_param is None:
        return params
    display = resolve_tool_attachments(tool, toolkit, params, native_param=native_param)
    if display:
        log.set(attachment_count=len(display))  # pragma: no mutate
    return params
