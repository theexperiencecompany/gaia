"""System-owned workspace files — one logical copy for ALL users.

``INDEX.md``, the per-area ``GUIDE.md`` docs, and the built-in skill bodies are
authored by GAIA and identical for every user. This module is the single
enumeration of them — each one's canonical ``/workspace``-relative path and its
body (already in process memory) — so the same list can drive:

  - the ``read`` tool's memory fast-path (serve these without touching JuiceFS),
  - writing the shared ``_system`` subtree once (no per-user duplication),
  - symlinking them into each user's workspace.

Bodies come from ``operational_docs`` / ``skill_loader`` (process memory; see the
scale notes there). Paths use the SAME constants the materializers write, so this
list can never drift from what lands on JuiceFS.
"""

from __future__ import annotations

from functools import lru_cache
from typing import NamedTuple

from app.agents.workspace.skill_loader import (
    SKILL_BODY_FILENAME,
    BuiltinSkill,
    load_builtin_skills,
)
from app.agents.workspace.system_docs import (
    GAIA_TASKS_GUIDE_MD,
    INDEX_MD,
    INTEGRATIONS_GUIDE_MD,
    SESSIONS_GUIDE_MD,
    USER_TODOS_GUIDE_MD,
)

# Subagent id for general (non-integration) builtin skills.
_EXECUTOR_SUBAGENT = "executor"


class SystemFile(NamedTuple):
    """A system-owned file: its /workspace-relative path and in-memory body."""

    rel_path: str
    body: str


# Static docs that anchor the workspace. Paths match what write_user_root_docs /
# the gaia-tasks + user-todos materializers write, so reads stay consistent.
_STATIC_DOCS: list[tuple[str, str]] = [
    ("INDEX.md", INDEX_MD),
    ("sessions/GUIDE.md", SESSIONS_GUIDE_MD),
    ("integrations/GUIDE.md", INTEGRATIONS_GUIDE_MD),
    ("gaia-tasks/GUIDE.md", GAIA_TASKS_GUIDE_MD),
    ("todos/GUIDE.md", USER_TODOS_GUIDE_MD),
]


def builtin_skill_rel_path(skill: BuiltinSkill) -> str:
    """``/workspace``-relative path of a builtin skill body — matches materialize_skills."""
    if skill.subagent_id == _EXECUTOR_SUBAGENT:
        return f"skills/{skill.slug}/{SKILL_BODY_FILENAME}"
    return f"integrations/{skill.subagent_id}/agent/skills/{skill.slug}/{SKILL_BODY_FILENAME}"


def system_files() -> list[SystemFile]:
    """Every system-owned file (static docs + builtin skill bodies)."""
    files = [SystemFile(path, body) for path, body in _STATIC_DOCS]
    files.extend(
        SystemFile(builtin_skill_rel_path(skill), skill.body) for skill in load_builtin_skills()
    )
    return files


@lru_cache(maxsize=1)
def _body_index() -> dict[str, str]:
    # Built once per deploy (builtins + docs are static at runtime, same as
    # load_builtin_skills' own cache).
    return {f.rel_path: f.body for f in system_files()}


def system_file_body(workspace_rel_path: str) -> str | None:
    """Return the in-memory body for a system file (path relative to /workspace), else None.

    This is the read tool's memory fast-path: a system path is served from RAM,
    never the sandbox or JuiceFS. Anything not system-owned returns None and
    falls through to the per-user JuiceFS read.
    """
    return _body_index().get(workspace_rel_path)


__all__ = [
    "SystemFile",
    "builtin_skill_rel_path",
    "system_file_body",
    "system_files",
]
