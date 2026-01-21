"""
Stream Utilities - Shared helpers for LangGraph streaming.

This module provides reusable functions for processing LangGraph stream events,
particularly for extracting and formatting tool call data.

Used by:
- execute_graph_streaming() in agent_helpers.py (main agent)
- execute_subagent_stream() in subagent_runner.py (subagents via handoff/executor)
- call_subagent() in subagent_runner.py (direct subagent calls for testing)
"""

from typing import Optional

from app.utils.agent_utils import format_tool_call_entry


async def extract_tool_entries_from_update(
    state_update: dict,
    emitted_tool_calls: set[str],
    integration_metadata: Optional[dict] = None,
) -> list[tuple[str, dict]]:
    """
    Extract tool_data entries from a LangGraph state update.

    Processes the nested structure of state updates to find tool calls
    and format them for frontend streaming. Handles deduplication via
    the emitted_tool_calls set.

    Args:
        state_update: State update dict from LangGraph 'updates' stream.
                      Expected structure: {"messages": [AIMessage with tool_calls, ...]}
        emitted_tool_calls: Set of already-emitted tool_call_ids.
                            Modified in place to track new emissions.
        integration_metadata: Optional dict with {icon_url, integration_id, name}
                              for custom MCP integrations. If provided, applied
                              to all tool entries.

    Returns:
        List of (tool_call_id, tool_entry) tuples for tool calls that haven't
        been emitted yet. Each tool_entry is ready for streaming to frontend.

    Example:
        >>> entries = await extract_tool_entries_from_update(
        ...     state_update={"messages": [ai_message_with_tools]},
        ...     emitted_tool_calls=set(),
        ...     integration_metadata={"icon_url": "...", "name": "Gmail"},
        ... )
        >>> for tc_id, entry in entries:
        ...     stream_writer({"tool_data": entry})
    """
    entries: list[tuple[str, dict]] = []

    if not isinstance(state_update, dict) or "messages" not in state_update:
        return entries

    for msg in state_update["messages"]:
        if not hasattr(msg, "tool_calls") or not msg.tool_calls:
            continue

        for tc in msg.tool_calls:
            tc_id = tc.get("id")
            if not tc_id or tc_id in emitted_tool_calls:
                continue

            # Format tool call as tool_data entry
            tool_entry = await format_tool_call_entry(
                tc,
                icon_url=(
                    integration_metadata.get("icon_url")
                    if integration_metadata
                    else None
                ),
                integration_id=(
                    integration_metadata.get("integration_id")
                    if integration_metadata
                    else None
                ),
                integration_name=(
                    integration_metadata.get("name") if integration_metadata else None
                ),
            )

            if tool_entry:
                entries.append((tc_id, tool_entry))
                emitted_tool_calls.add(tc_id)

    return entries
