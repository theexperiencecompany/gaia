"""Shared lifecycle for capturing background-executor tool events.

The executor runs as a detached asyncio task (spawned by call_executor).
Its tool events, and those of any subagent it spawns, are appended to
the stream's StreamSession.tool_events by make_redis_stream_writer.

Both the live chat path and the silent path (workflows, background tasks)
register the session, wait for the executor, drain the collected events into
grouped tool_data, and tear it down. Centralizing it here keeps one
implementation so chat and workflow runs render identically.
"""

from app.agents.core.background.session import (
    get_session,
)
from app.models.chat_models import ToolDataEntry
from app.services.chat.chunks import normalize_custom_event
from app.utils.stream_utils import (
    ToolDataEnvelope,
    absorb_collector_event,
    apply_outputs_to_tool_data,
    reconstruct_subagent_groups,
)


def drain_executor_tool_data(stream_id: str) -> list[ToolDataEntry]:
    """Drain the session's tool events into reconstructed tool_data.

    Non-destructive read. Mirrors the comms-graph accumulation path:
    tool_calls_data outputs are merged in, and subagent start/end pairs are
    grouped via reconstruct_subagent_groups. Only tool_calls_data entries
    get their output backfilled.
    """
    session = get_session(stream_id)
    if session is None or not session.tool_events:
        return []
    entries: list[ToolDataEntry] = []
    # The accumulator envelope is an open bag; only "tool_data" has a fixed
    # shape, and it's this list object throughout, rebound by
    # reconstruct_subagent_groups, hence the re-read at the end.
    accumulated: dict[str, object] = {"tool_data": entries}
    outputs: dict[str, str] = {}
    for evt in session.tool_events:
        # Hooks emit raw field payloads like {"email_fetch_data": [...]};
        # normalize to {"tool_data": {...}} or absorb_collector_event drops
        # them and the list card never persists.
        absorb_collector_event(normalize_custom_event(evt), accumulated, outputs)
    apply_outputs_to_tool_data(entries, outputs, only_tool_name="tool_calls_data")
    reconstruct_subagent_groups(accumulated)
    return ToolDataEnvelope.model_validate(accumulated).tool_data
