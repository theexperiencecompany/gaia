"""Render a user's active tracked todos as signal-matching prompt context.

Extracted from ``tracked_todo_service`` so the trigger dispatch path can build this
context without importing the todo lifecycle: the lifecycle now tears down trigger
subscriptions, which imports the trigger stack back, and the two together were a
genuine import cycle. This module reads todos and their notes facet and nothing else, so
both sides can depend on it.
"""

import re

from app.constants.todos import FACET_NOTES, GAIA_TRACKED_LABEL
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument
from app.services.todo_canvas_storage import build_vfs_label, read_facet
from shared.py.wide_events import log

# Capture everything under the "## Key Details" heading up to the next "## "
# heading (or end of text). A tempered greedy token — "any char that does not
# begin a new section" — avoids a reluctant quantifier entirely.
_KEY_DETAILS_RE = re.compile(r"## Key Details\n((?:(?!\n## ).)*)", re.DOTALL)
_KEY_DETAILS_MAX_LINES = 5
_SIGNAL_CONTEXT_TODO_LIMIT = 15


async def _extract_canvas_key_details(doc: TodoDocument, user_id: str) -> str:
    """Pull the Key Details section text from a tracked todo's notes (empty on miss)."""
    try:
        notes = await read_facet(doc.id, user_id, FACET_NOTES)
    except Exception as e:
        log.warning("tracked_todo.notes_read_failed", todo_id=doc.id, error=str(e))
        return ""
    if not notes:
        return ""
    match = _KEY_DETAILS_RE.search(notes)
    return match.group(1).strip() if match else ""


def _format_signal_entry(doc: TodoDocument, key_details: str) -> str:
    """Render one tracked todo as a signal-matching context bullet (+ indented key details)."""
    # Legacy docs still carry the deprecated tracked label until the assignee
    # backfill has run everywhere; it is bookkeeping, never agent context.
    labels = [lbl for lbl in doc.labels if lbl != GAIA_TRACKED_LABEL]
    labels_str = f" [{', '.join(labels)}]" if labels else ""
    entry = f'- "{doc.title}"{labels_str} (ID: {doc.id}, vfs: {build_vfs_label(doc.id)})'
    if key_details:
        for dl in key_details.split("\n")[:_KEY_DETAILS_MAX_LINES]:
            entry += f"\n    {dl.strip()}"
    return entry


async def get_signal_matching_context(user_id: str) -> str:
    """Compact tracked todos summary optimized for signal matching.

    Includes key IDs (thread_ids, email addresses, event_ids) so the agent can
    match incoming signals to relevant todos.
    """
    docs = await todo_repository.list_active_tracked(user_id, limit=_SIGNAL_CONTEXT_TODO_LIMIT)
    if not docs:
        return ""

    lines = [
        _format_signal_entry(doc, await _extract_canvas_key_details(doc, user_id)) for doc in docs
    ]
    return "ACTIVE TRACKED TODOS (check if incoming signal relates to any):\n" + "\n".join(lines)
