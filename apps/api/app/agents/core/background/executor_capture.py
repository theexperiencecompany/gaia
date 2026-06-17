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
from app.constants.agents import RETURNED_TO_FRONTEND_MARKER
from app.constants.cache import EXECUTOR_WAIT_TIMEOUT
from app.models.chat_models import tool_fields
from app.utils.stream_utils import (
    absorb_collector_event,
    apply_outputs_to_tool_data,
    normalize_custom_event,
    reconstruct_subagent_groups,
)
from shared.py.wide_events import log


def register_executor_capture(stream_id: str, voice_mode: bool = False) -> asyncio.Event:
    """Register the stream session that captures executor tool events.

    Must run before the comms agent executes so ``call_executor``'s background
    task can append events to the session. ``voice_mode`` marks the stream so the
    executor's finalize step publishes a TTS-only ``voice_tts`` frame with its
    narrated answer for the voice agent to speak. Returns the done-event.
    """
    session = create_session(stream_id, RunKind.LIVE)
    session.voice_mode = voice_mode
    return session.done_event


# The timeout cannot move to callers: this function owns the graceful
# catch-and-drain semantics (log + return so collected events still flush).
async def await_executor_done(
    stream_id: str,
    timeout: float = EXECUTOR_WAIT_TIMEOUT,  # NOSONAR python:S7483
) -> None:
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
        async with asyncio.timeout(timeout):
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
        # Hooks (e.g. GMAIL_FETCH_EMAILS) emit raw field payloads like
        # {"email_fetch_data": [...]}; normalize them to {"tool_data": {...}}
        # before absorbing, or absorb_collector_event drops them and the list
        # card never persists onto the background-executor message.
        absorb_collector_event(normalize_custom_event(evt), accumulated, outputs)
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
        f"{RETURNED_TO_FRONTEND_MARKER}\n"
        "These native cards are already on the user's screen this turn:\n"
        f"{body}\n"
        "They visually render the RAW items, so don't re-type those items "
        "row-by-row and don't re-emit them as OpenUI — that literal duplication "
        "is the ONLY thing to avoid here.\n"
        "The cards are visual aids, NOT your reply. You still owe the user the "
        "ANSWER in your own voice — the substance the executor produced: what it "
        "found, grouped and counted, the few items that actually matter (and "
        'why), and the natural next step. This synthesis is never "card '
        'contents"; suppressing it because a card exists is the worst failure '
        "you can have.\n"
        "Match the depth to the work: a quick outcome gets a line or two; a "
        "large, comprehensive result (a full triage, a multi-item analysis) gets "
        "a real structured rundown — never a one-liner. Replying just \"here's "
        'the list 👇" with no substance, when the executor did real work, fails '
        "the user. Point them to the card for the granular rows AFTER you've "
        "actually delivered the gist.\n"
        "CRITICAL EXCEPTION — LONG-FORM DELIVERABLE: if the executor's result is "
        "itself a finished written piece (a research report, an article, an "
        "analysis, a document), that is the ANSWER, not raw card rows. The cards "
        "above were just the research/loading steps along the way. Deliver the "
        "deliverable IN FULL per the long-form rule — every section, point, and "
        "citation — and do NOT compress it to a 'here's the breakdown' summary. "
        "This note never authorizes shrinking a report; it only stops you "
        "re-typing rows a card already lists.\n"
    )


def teardown_executor_capture(stream_id: str) -> None:
    """Drop the stream's session and everything it holds.

    Safe to call multiple times.
    """
    teardown_session(stream_id)
