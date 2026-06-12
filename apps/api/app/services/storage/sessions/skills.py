"""SKILL.md catalog materialization.

Walks the in-memory skill registry (``app.agents.workspace.skill_loader``)
and writes the per-user ``integrations/<iid>/agent/skills/`` + ``skills/``
trees on JuiceFS (plus the ``integrations/GUIDE.md`` anchor). All writes are
hash-compared first — steady-state turns do zero I/O when the library hash and
connected-integration signature haven't changed. The root INDEX/GUIDE docs are
system files, materialized as symlinks by ``link_system_files_into_workspace``.

A separate ``.connected`` marker is dropped (or removed) under each
integration's ``agent/`` directory so the agent's prompt can tell, in a
single ``stat``, which integrations the user has actually connected.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.workspace.skill_loader import (
    SKILL_BODY_FILENAME,
    BuiltinSkill,
    skills_by_subagent,
)
from app.agents.workspace.system_docs import (
    INTEGRATIONS_GUIDE_MD,
)
from app.services.storage._vfs_common import matches_text
from app.services.storage.juicefs import ensure_safe_path_id
from shared.py.wide_events import log

SKILLS_HASH_MARKER = ".gaia/skills.v"
GUIDE_FILENAME = "GUIDE.md"


def read_text_or_none(path: Path) -> str | None:
    """Read a small marker file; return ``None`` if absent or unreadable."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


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


def _write_skill_dir(slug_dir: Path, skill: BuiltinSkill) -> int:
    """Write one skill's body + bundled resources, prune stale files.

    Returns the count of files actually (re)written.
    """
    written = 0
    slug_dir.mkdir(parents=True, exist_ok=True)
    target = slug_dir / SKILL_BODY_FILENAME
    if not matches_text(target, skill.body):
        target.write_text(skill.body, encoding="utf-8")
        written += 1
    # Also write the skill's bundled resources (templates/, reference.md,
    # scripts/, …) so multi-file skills work when the shared _system
    # subtree + symlinks are unavailable (the linker replaces these with
    # symlinks once the subtree exists). `rel` is always contained within
    # the skill dir (see skill_loader._load_resources), so no traversal.
    for rel, content in skill.resources:
        res = slug_dir / rel
        if not matches_text(res, content):
            res.parent.mkdir(parents=True, exist_ok=True)
            res.write_text(content, encoding="utf-8")
            written += 1
    # Drop fallback copies of resources that left the manifest (renamed or
    # removed) so a stale template can't outlive the registry change. Only
    # real files are pruned — symlinks are owned by link_system_files.
    expected = {SKILL_BODY_FILENAME, *(rel for rel, _ in skill.resources)}
    for existing in slug_dir.rglob("*"):
        if existing.is_symlink() or not existing.is_file():
            continue
        if existing.relative_to(slug_dir).as_posix() not in expected:
            existing.unlink(missing_ok=True)
    return written


def _write_connected_marker(agent_dir: Path, *, connected: bool) -> None:
    """Drop or remove the ``.connected`` marker under an integration's agent dir."""
    marker = agent_dir / ".connected"
    if connected:
        if not marker.exists():
            marker.write_text("", encoding="utf-8")
    elif marker.exists():
        marker.unlink()


def materialize_skills(user_root: Path, connected_ids: set[str]) -> int:
    """Write the SKILL.md catalog under ``integrations/`` and ``skills/``.

    Returns the count of skill bodies actually rewritten — useful for both
    metrics and "did anything change?" tests.
    """
    written = 0
    integrations_root = user_root / "integrations"
    integrations_root.mkdir(parents=True, exist_ok=True)
    if not matches_text(integrations_root / GUIDE_FILENAME, INTEGRATIONS_GUIDE_MD):
        (integrations_root / GUIDE_FILENAME).write_text(INTEGRATIONS_GUIDE_MD, encoding="utf-8")

    grouped = skills_by_subagent()
    for iid, skills in grouped.items():
        if iid == "executor" or not skills:
            continue
        agent_dir = integrations_root / iid / "agent"
        skills_dir = agent_dir / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        for skill in skills:
            written += _write_skill_dir(skills_dir / skill.slug, skill)
        _write_connected_marker(agent_dir, connected=iid in connected_ids)

    # Executor (general) skill bodies are NOT written here: they belong in the
    # /skills/<uid> overlay subtree (what the sandbox shows at /workspace/skills),
    # and link_system_files_into_workspace places them there as symlinks into the
    # shared _system copy. Writing them under /users/<uid>/skills would only land
    # in the shadowed subtree.
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
