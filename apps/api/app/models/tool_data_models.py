"""The tool_data entry shape shared by stored messages, stream frames and log entries."""

from typing import Any, NotRequired

from typing_extensions import TypedDict


class ToolDataEntry(TypedDict):
    """Unified structure for tool execution data.

    Every key an emitter can stamp must be declared here. This TypedDict is the
    element type of ``MessageModel.tool_data``, and Pydantic drops undeclared
    keys on ``model_dump()`` — which is how a message reaches Mongo. An emitted
    key missing from this shape therefore survives the live SSE frame (the
    frontend parses those against its own loose schema) and silently vanishes
    from the stored turn, so the bug only ever appears on reload.

    ``data`` is deliberately open: every tool owns the shape it puts here (a
    calendar option list, an email thread, a rendered artifact), so the only
    honest constraint is "JSON the frontend's per-tool card knows how to read".
    Everything around it is closed.

    The frontend mirror is ``ToolDataEntrySchema`` in
    ``libs/shared/ts/src/chat/schema.ts``.
    """

    tool_name: str
    # Any on purpose (see above): it is JSON the tool owns, and the generated
    # TypeScript reads it as `unknown` — the honest type for every consumer to
    # narrow from.
    data: Any
    # Optional: emitters always stamp it, but legacy stored entries predate the
    # field, so a read must tolerate its absence rather than fail validation.
    timestamp: NotRequired[str | None]
    # Which card renders the entry, stamped by format_tool_call_entry, the HIL
    # frame, the reasoning absorber and rate-limit/artifact emitters; absent on
    # plain per-tool-field entries, which the frontend keys off tool_name alone.
    tool_category: NotRequired[str]
    # Tags an entry produced inside a delegated subagent, so
    # reconstruct_subagent_groups can fold it into that subagent's group.
    subagent_id: NotRequired[str]
    # MCP App UI metadata (resource_uri, csp, permissions) and the server that
    # serves it. Only tool_calls_data entries for MCP tools carry these; without
    # them a restored turn cannot re-fetch the iframe.
    mcp_ui: NotRequired[dict[str, Any] | None]
    mcp_server_url: NotRequired[str | None]
