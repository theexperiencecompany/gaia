"""Shared lifecycle for capturing background-executor tool events.

The executor runs as a detached asyncio task (spawned by ``call_executor``).
Its tool events, and those of any subagent it hands off to, are appended to a
per-``stream_id`` collector by ``make_redis_stream_writer``.

Both the live chat path and the silent path (workflows, background tasks)
register that collector, wait for the executor, drain it into grouped
``tool_data``, and tear it down. Centralizing it here keeps one implementation
so chat and workflow runs render identically.
"""

import asyncio
from typing import Any

from app.agents.core.background.inbox import (
    deregister_bg_subagent_results,
    deregister_executor_done_event,
    deregister_executor_spawned,
    deregister_pending_subagents,
    deregister_tool_event_collector,
    get_executor_done_event,
    get_tool_event_collector,
    register_executor_done_event,
    register_tool_event_collector,
    was_executor_spawned,
)
from app.constants.cache import EXECUTOR_WAIT_TIMEOUT
from app.models.chat_models import tool_fields
from app.utils.stream_utils import (
    absorb_collector_event,
    apply_outputs_to_tool_data,
    reconstruct_subagent_groups,
)
from shared.py.wide_events import log


def register_executor_capture(stream_id: str) -> asyncio.Event:
    """Register the done-event and tool-event collector for a stream.

    Must run before the comms agent executes so ``call_executor``'s background
    task can append events to the collector. Returns the done-event.
    """
    done_event = register_executor_done_event(stream_id)
    register_tool_event_collector(stream_id)
    return done_event


async def await_executor_done(stream_id: str) -> None:
    """Block until the background executor for this stream signals completion.

    No-op when no executor was spawned for the stream. On timeout, logs and
    returns so the caller can still drain whatever events were collected.
    """
    if not was_executor_spawned(stream_id):
        return
    done_event = get_executor_done_event(stream_id)
    if done_event is None:
        return
    log.info("Waiting for executor completion", stream_id=stream_id)
    try:
        async with asyncio.timeout(EXECUTOR_WAIT_TIMEOUT):
            await done_event.wait()
    except TimeoutError:
        log.warning("Timed out waiting for executor — draining anyway", stream_id=stream_id)


def drain_executor_tool_data(stream_id: str) -> list[dict[str, Any]]:
    """Drain the executor tool-event collector into reconstructed tool_data.

    Mirrors the comms-graph accumulation path: ``tool_calls_data`` outputs are
    merged in, and subagent start/end pairs are grouped into ``subagent_group``
    entries via ``reconstruct_subagent_groups``. Only ``tool_calls_data``
    entries get their output backfilled — the message owns those, while
    subagent groups carry their own outputs from the collector.
    """
    collector = get_tool_event_collector(stream_id)
    if not collector:
        return []
    accumulated: dict[str, Any] = {"tool_data": []}
    outputs: dict[str, str] = {}
    for evt in collector:
        absorb_collector_event(evt, accumulated, outputs)
    apply_outputs_to_tool_data(accumulated["tool_data"], outputs, only_tool_name="tool_calls_data")
    reconstruct_subagent_groups(accumulated)
    return accumulated.get("tool_data", [])


def build_returned_to_frontend_note(stream_id: str) -> str:
    """Build a note telling comms which native cards already rendered this turn.

    Sourced from the executor's emitted tool events (the same collector +
    ``tool_fields`` source of truth as ``OPENUI_SUPPRESSED_TOOLS``), so it states
    what was RETURNED to the frontend — not a claim about DOM rendering.

    MUST be called before the collector is torn down (and, for live streams,
    before ``done_event`` is set, since the chat stream drains + tears down in
    parallel). Returns "" when nothing card-worthy was emitted.
    """
    entries = drain_executor_tool_data(stream_id)
    summary: list[str] = []
    for entry in entries:
        name = entry.get("tool_name")
        if name not in tool_fields:
            continue  # excludes tool_calls_data / subagent_group (loading rows)
        data = entry.get("data")
        count = len(data) if isinstance(data, list) else 1
        # Derive a readable label from the field name so it never drifts from
        # the tool_fields source of truth (e.g. "email_fetch_data" -> "email fetch").
        noun = name.removesuffix("_data").replace("_", " ") or "items"
        summary.append(f"  - {name} ({count} {noun})")

    if not summary:
        return ""

    body = "\n".join(summary)
    return (
        "[RETURNED_TO_FRONTEND]\n"
        "The data below is ALREADY shown to the user as native cards this turn:\n"
        f"{body}\n"
        "Do NOT restate or list their contents, and do NOT emit OpenUI for them. "
        'A brief conversational lead-in is fine (e.g. "here\'s your week 👇"), '
        "but never enumerate the items the card already shows.\n"
    )


def teardown_executor_capture(stream_id: str) -> None:
    """Deregister all per-stream executor orchestration state.

    Safe to call multiple times.
    """
    deregister_executor_done_event(stream_id)
    deregister_tool_event_collector(stream_id)
    deregister_pending_subagents(stream_id)
    deregister_executor_spawned(stream_id)
    deregister_bg_subagent_results(stream_id)
