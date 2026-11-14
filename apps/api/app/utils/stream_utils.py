"""Turn a LangGraph node update's tool calls into the tool_data cards a run streams."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.models.chat_models import ToolDataEntry
from app.utils.agent_utils import (
    IntegrationMetadata,
    NodeMessagesUpdate,
    ToolCallView,
    format_tool_call_entry,
)


async def extract_tool_entries_from_update(
    state_update: object,
    emitted_tool_calls: set[str],
    integration_metadata: IntegrationMetadata | None = None,
    user_id: str | None = None,
) -> list[tuple[str, ToolDataEntry]]:
    """Extract new tool_data entries from a LangGraph state update.

    Deduplicates against emitted_tool_calls (mutated in place). state_update
    is typed object since callers pass whatever a node yielded, which is
    not always a mapping — the isinstance guard below is load-bearing.
    user_id lets a per-user MCP tool's card resolve the integration it came from.
    """
    entries: list[tuple[str, ToolDataEntry]] = []

    if not isinstance(state_update, dict):
        return entries

    metadata = integration_metadata or IntegrationMetadata()
    for msg in NodeMessagesUpdate.model_validate(state_update).messages:
        if not isinstance(msg, AIMessage) or not msg.tool_calls:
            continue

        for tc in msg.tool_calls:
            tc_id = ToolCallView.model_validate(tc).id
            if not tc_id or tc_id in emitted_tool_calls:
                continue

            # Format tool call as tool_data entry
            tool_entry = await format_tool_call_entry(
                tc,
                icon_url=metadata.icon_url,
                integration_id=metadata.integration_id,
                integration_name=metadata.name,
                user_id=user_id,
            )

            if tool_entry:
                entries.append((tc_id, tool_entry))
                emitted_tool_calls.add(tc_id)

    return entries
