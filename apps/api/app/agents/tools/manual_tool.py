"""The ``read_manual`` tool — read GAIA's own operating manual from memory.

Unlike ``read`` / ``bash`` (which execute inside the E2B sandbox and therefore
pay a microVM spin-up/resume), this returns app-owned manual content directly
from the API process — no sandbox involved. Use it for GAIA's own docs; reserve
``read`` for the user's actual files and code.
"""

from __future__ import annotations

from langchain_core.tools import tool

from app.agents.workspace.operational_docs import ManualTopic, get_manual, manual_index_text
from shared.py.wide_events import log


@tool
async def read_manual(topic: ManualTopic) -> str:
    """Read one topic of GAIA's own operating manual (no sandbox spin-up).

    Use this to refresh on how GAIA works or how to do a self-management task,
    instead of ``cat``-ing a file (which would spin up the sandbox). Topics:

    - ``integrations`` — connect/configure integrations; per-integration custom
      instructions ("remember this for Gmail").
    - ``tracked-todos`` — create/search/update/schedule/complete tracked todos;
      canvas conventions; recurrence; institutional memory.
    - ``user-todos`` — the user's own todo list and external task providers.
    - ``sessions-and-artifacts`` — working in a session; producing artifacts.
    - ``notifications`` — notification channels and delivery.

    Pass one of the topic names above; returns that topic's full doc. Passing an
    unknown topic returns the list of valid topics.
    """
    doc = get_manual(topic)
    if doc is None:
        log.set(tool={"name": "read_manual", "topic": topic, "found": False})
        return f"Unknown manual topic: {topic!r}.\n\n{manual_index_text()}"
    log.set(tool={"name": "read_manual", "topic": doc.name, "found": True})
    return doc.body


tools = [read_manual]
