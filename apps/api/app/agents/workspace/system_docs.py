"""On-disk workspace docs (INDEX.md + per-category GUIDE.md).

These are the projections materialized into each user's workspace so the
filesystem is self-describing for anyone who `ls`/`cat`s it. The *canonical*
prose now lives in ``operational_docs.py`` (the single source of truth the
agent also receives by injection / ``read_manual``); this module is a thin
on-disk view over it, plus ``INDEX_MD`` (the FS map) and the per-subagent
skills listing.

One source of truth: the per-category guide bodies below are re-exported from
``operational_docs`` so the on-disk copy never diverges from what the agent is
told in-context.
"""

from __future__ import annotations

from app.agents.workspace.operational_docs import (
    INTEGRATIONS_DOC,
    SESSIONS_ARTIFACTS_DOC,
    TRACKED_TODOS_DOC,
    USER_TODOS_DOC,
)
from app.agents.workspace.skill_loader import skills_by_subagent

INDEX_MD = """# /workspace — your operating environment

This is your persistent root inside the sandbox. Everything you create
here survives across conversations for this user.

## Top-level layout

    sessions/         per-conversation working trees (see sessions/GUIDE.md)
    integrations/     connected integrations: subagents, prompts, skills
                      (present only when the user has connected one)
    skills/           reusable agent skills (when present)
    todos/            the USER's own todo list (the things in their UI).
                      One folder per active user todo. (see todos/GUIDE.md)
    gaia-tasks/       YOUR (the agent's) work threads — institutional memory
                      of initiatives you've worked on. (see gaia-tasks/GUIDE.md)
    pinned/           cross-session files the user has pinned for reuse

## How to navigate

Before operating on any directory, read its `GUIDE.md`. It tells you what
that area is for, what is mutable vs read-only, and the action conventions
for that domain. If a directory has no `GUIDE.md`, default to treating its
contents as read-only and ask before modifying.

The conversation you're in right now has its working tree at:

    /workspace/sessions/<your-conversation-id>/

Start there for any task involving files the user attached or outputs you
need to surface back to them.
"""

# Per-category guides are the canonical operational docs, re-exported here so
# the on-disk GUIDE.md projection stays a single-source view (no duplication).
SESSIONS_GUIDE_MD = SESSIONS_ARTIFACTS_DOC
INTEGRATIONS_GUIDE_MD = INTEGRATIONS_DOC
GAIA_TASKS_GUIDE_MD = TRACKED_TODOS_DOC
USER_TODOS_GUIDE_MD = USER_TODOS_DOC


def integration_skills_block(subagent_id: str) -> str:
    """Markdown listing of a subagent's available skills, or "" if none."""
    skills = skills_by_subagent().get(subagent_id) or []
    if not skills:
        return ""
    base = f"/workspace/integrations/{subagent_id}/agent/skills"
    lines = [f"## Available skills for {subagent_id}"]
    lines.append(
        f"Read `{base}/<slug>/skill.md` before invoking the underlying tool. "
        "The body is the full recipe; the description below is a one-line "
        "trigger so you know which file to cat."
    )
    for skill in skills:
        desc = (skill.description or "").strip()
        suffix = f" — {desc}" if desc else ""
        lines.append(f"- **{skill.name}** (`{base}/{skill.slug}/skill.md`){suffix}")
    return "\n".join(lines)


__all__ = [
    "GAIA_TASKS_GUIDE_MD",
    "INDEX_MD",
    "INTEGRATIONS_GUIDE_MD",
    "SESSIONS_GUIDE_MD",
    "USER_TODOS_GUIDE_MD",
    "integration_skills_block",
]
