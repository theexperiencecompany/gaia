"""Shared lifecycle for capturing background-executor tool events.

The executor runs as a detached asyncio task (spawned by ``call_executor``).
Its tool events, and those of any subagent it hands off to, are appended to
the stream's ``StreamSession.tool_events`` by ``make_redis_stream_writer``.

Both the live chat path and the silent path (workflows, background tasks)
register the session, wait for the executor, drain the collected events into
grouped ``tool_data``, and tear it down. Centralizing it here keeps one
implementation so chat and workflow runs render identically.
"""

import asyncio
from typing import Any

from app.agents.core.background.session import (
    RunKind,
    create_session,
    get_session,
    teardown_session,
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
    """Register the stream session that captures executor tool events.

    Must run before the comms agent executes so ``call_executor``'s background
    task can append events to the session. Returns the done-event.
    """
    return create_session(stream_id, RunKind.LIVE).done_event


async def await_executor_done(stream_id: str) -> None:
    """Block until the background executor for this stream signals completion.

    No-op when no executor was spawned for the stream. On timeout, logs and
    returns so the caller can still drain whatever events were collected.
    """
    if not was_executor_spawned(stream_id):
        return
    session = get_session(stream_id)
    if session is None:
        return
    log.info("Waiting for executor completion", stream_id=stream_id)
    try:
        async with asyncio.timeout(EXECUTOR_WAIT_TIMEOUT):
            await session.done_event.wait()
    except TimeoutError:
        log.warning("Timed out waiting for executor — draining anyway", stream_id=stream_id)


def drain_executor_tool_data(stream_id: str) -> list[dict[str, Any]]:
    """Drain the session's tool events into reconstructed tool_data.

    Non-destructive read. Mirrors the comms-graph accumulation path:
    ``tool_calls_data`` outputs are merged in, and subagent start/end pairs are
    grouped into ``subagent_group`` entries via ``reconstruct_subagent_groups``.
    Only ``tool_calls_data`` entries get their output backfilled — the message
    owns those, while subagent groups carry their own outputs from the session.
    """
    session = get_session(stream_id)
    if session is None or not session.tool_events:
        return []
    accumulated: dict[str, Any] = {"tool_data": []}
    outputs: dict[str, str] = {}
    for evt in session.tool_events:
        absorb_collector_event(evt, accumulated, outputs)
    apply_outputs_to_tool_data(accumulated["tool_data"], outputs, only_tool_name="tool_calls_data")
    reconstruct_subagent_groups(accumulated)
    return accumulated.get("tool_data", [])


def build_returned_to_frontend_note(stream_id: str) -> str:
    """Build a note telling comms which native cards already rendered this turn.

    Sourced from the executor's emitted tool events (the same session +
    ``tool_fields`` source of truth as ``OPENUI_SUPPRESSED_TOOLS``), so it states
    what was RETURNED to the frontend — not a claim about DOM rendering.

    MUST be called before the session is torn down (and, for live streams,
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
    """Drop the stream's session and everything it holds.

    Safe to call multiple times.
    """
    teardown_session(stream_id)
