"""The deliverable facet of a tracked todo's canvas — what a recipient may see.

A canvas (``CANVAS_TEMPLATE`` in ``app/services/tracked_todo_service.py``) mixes
the result GAIA produced with the working memory it needed to produce it: the
``Key Details`` section holds email addresses, thread ids and calendar ids, and
the log/context sections narrate tool calls. Only the result belongs on a page
that anyone holding a heygaia.link can open, so this strips every working
section, every HTML comment and the duplicated ``# title`` line.

The working sections are a closed set named by the template; anything else the
agent wrote under its own heading (``## Draft reply``, ``## Findings``) is the
deliverable and is kept.
"""

import re

PRIVATE_CANVAS_SECTIONS = (
    "key details",
    "activity log",
    "timeline",
    "context",
    "learnings",
    "system log",
)

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def project_canvas_deliverable(canvas: str) -> str:
    """The canvas with its working sections, comments and title line removed."""
    kept: list[str] = []
    skipping = False
    for line in _HTML_COMMENT.sub("", canvas).splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            continue
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            skipping = heading.startswith(PRIVATE_CANVAS_SECTIONS)
        if not skipping:
            kept.append(line)
    return "\n".join(kept).strip()
