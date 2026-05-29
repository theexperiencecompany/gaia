"""SKILL.md catalog materialization + user-root docs.

Walks the in-memory skill registry (``app.agents.workspace.skill_loader``)
and writes the per-user ``integrations/<iid>/agent/skills/`` + ``skills/``
trees on JuiceFS, alongside the INDEX/GUIDE markdown files that anchor the
workspace. All writes are hash-compared first — steady-state turns do
zero I/O when the library hash and connected-integration signature haven't
changed.

A separate ``.connected`` marker is dropped (or removed) under each
integration's ``agent/`` directory so the agent's prompt can tell, in a
single ``stat``, which integrations the user has actually connected.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.workspace.skill_loader import skills_by_subagent
from app.agents.workspace.system_docs import (
    INDEX_MD,
    INTEGRATIONS_GUIDE_MD,
    SESSIONS_GUIDE_MD,
)
from app.services.storage.juicefs import ensure_safe_path_id
from shared.py.wide_events import log

SKILLS_HASH_MARKER = ".gaia/skills.v"


def matches_text(path: Path, expected: str) -> bool:
    """Cheap "do we need to rewrite this file?" check.

    Treats decode errors as "doesn't match" so corrupted bytes get rewritten
    rather than silently kept.
    """
    try:
        return path.read_text(encoding="utf-8") == expected
    except (OSError, UnicodeDecodeError):
        return False


def read_text_or_none(path: Path) -> str | None:
    """Read a small marker file; return ``None`` if absent or unreadable."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def write_user_root_docs(user_root: Path) -> None:
    """Idempotently write ``INDEX.md`` and ``sessions/GUIDE.md``."""
    index = user_root / "INDEX.md"
    if not matches_text(index, INDEX_MD):
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(INDEX_MD, encoding="utf-8")
    sessions_guide = user_root / "sessions" / "GUIDE.md"
    if not matches_text(sessions_guide, SESSIONS_GUIDE_MD):
        sessions_guide.parent.mkdir(parents=True, exist_ok=True)
        sessions_guide.write_text(SESSIONS_GUIDE_MD, encoding="utf-8")


def read_skills_marker(user_root: Path) -> str | None:
    """Return the recorded library-hash marker, or ``None`` if absent."""
    marker = user_root / SKILLS_HASH_MARKER
    if not marker.exists():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def write_skills_marker(user_root: Path, value: str) -> None:
    """Stamp the library-hash marker. Creates parent dirs as needed."""
    marker = user_root / SKILLS_HASH_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(value, encoding="utf-8")


def materialize_skills(user_root: Path, connected_ids: set[str]) -> int:
    """Write the SKILL.md catalog under ``integrations/`` and ``skills/``.

    Returns the count of skill bodies actually rewritten — useful for both
    metrics and "did anything change?" tests.
    """
    written = 0
    integrations_root = user_root / "integrations"
    integrations_root.mkdir(parents=True, exist_ok=True)
    if not matches_text(integrations_root / "GUIDE.md", INTEGRATIONS_GUIDE_MD):
        (integrations_root / "GUIDE.md").write_text(INTEGRATIONS_GUIDE_MD, encoding="utf-8")

    grouped = skills_by_subagent()
    for iid, skills in grouped.items():
        if iid == "executor" or not skills:
            continue
        agent_dir = integrations_root / iid / "agent"
        skills_dir = agent_dir / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        for skill in skills:
            slug_dir = skills_dir / skill.slug
            slug_dir.mkdir(parents=True, exist_ok=True)
            target = slug_dir / "skill.md"
            if not matches_text(target, skill.body):
                target.write_text(skill.body, encoding="utf-8")
                written += 1
        marker = agent_dir / ".connected"
        if iid in connected_ids:
            if not marker.exists():
                marker.write_text("", encoding="utf-8")
        elif marker.exists():
            marker.unlink()

    for skill in grouped.get("executor", []):
        slug_dir = user_root / "skills" / skill.slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        target = slug_dir / "skill.md"
        if not matches_text(target, skill.body):
            target.write_text(skill.body, encoding="utf-8")
            written += 1
    return written


def materialize_instructions(user_root: Path, instructions: dict[str, str]) -> int:
    """Write per-user custom instructions under ``integrations/<id>/agent/``.

    ``instructions`` maps integration id → markdown body (already filtered to
    non-empty by the service). Each lands at
    ``integrations/<id>/agent/instructions.md`` as a read-only projection of the
    ``integration_instructions`` MongoDB collection — the same Mongo-is-truth
    contract as the skill bodies beside it. Stale files (instructions the user
    cleared) are removed so the projection never outlives its source.

    Returns the count of files actually rewritten.
    """
    written = 0
    integrations_root = user_root / "integrations"
    for iid, content in instructions.items():
        if not content:
            continue
        # Backstop: iid is user/agent-supplied. Refuse anything that isn't a
        # single safe path component so a crafted id (e.g. "../../<victim>")
        # cannot escape the user's integrations/ root and write elsewhere on the
        # shared mount. Skip the bad entry rather than aborting the bootstrap.
        try:
            ensure_safe_path_id(iid, label="integration_id")
        except ValueError:
            log.warning(f"Skipping unsafe integration_id in instructions projection: {iid!r}")
            continue
        agent_dir = integrations_root / iid / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        target = agent_dir / "instructions.md"
        if not matches_text(target, content):
            target.write_text(content, encoding="utf-8")
            written += 1

    # Drop projections whose source instruction was cleared since the last sync.
    if integrations_root.is_dir():
        for agent_dir in integrations_root.glob("*/agent"):
            iid = agent_dir.parent.name
            stale = agent_dir / "instructions.md"
            if iid not in instructions and stale.exists():
                stale.unlink()

    return written
