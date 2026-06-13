"""Read the built-in SKILL.md library from disk and group skills by target.

Single source of truth for what gets materialized into the per-user
integrations/ and skills/ trees on the JuiceFS workspace. The body the
agent reads via `cat` is byte-identical to the SKILL.md authored in
``apps/api/app/agents/skills/builtin/<slug>/``; the frontmatter is
parsed once at load time so we know each skill's name, description,
and target subagent.

Used by:
  - ``system_docs.integration_skills_block`` to list available skills
    in the subagent's dynamic context.
  - ``storage.sessions.materialize_user_integrations`` to write the
    actual skill.md bodies + per-integration prompt.md into the user's
    workspace.
  - ``scripts/materialize_user_workspace.py`` as a prod-callable CLI
    that lays the same tree down for a given user, idempotently.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
import re

from shared.py.wide_events import log

# Skills live as siblings in source: apps/api/app/agents/skills/builtin/<slug>/SKILL.md.
# Resolved relative to this file so prod (the docker image), tests, and the dev
# server all pick up the same library.
_BUILTIN_ROOT = Path(__file__).resolve().parent.parent / "skills" / "builtin"

# Filename of the materialized skill body inside each slug dir. Shared by the
# materializer (storage.sessions.skills) and the index (skills.discovery) so the
# path the agent is told to read always matches the file actually on disk.
SKILL_BODY_FILENAME = "skill.md"

# Frontmatter `target` values use a `<provider>_agent` convention plus the
# special "executor" target for general-purpose skills. Map them to the
# subagent id used by the registry/integrations service so the FS layout
# (`integrations/<id>/...`) matches the runtime identifier.
_TARGET_ALIASES = {
    # Special "general" bucket — not tied to a single integration.
    "executor": "executor",
}


def _target_to_subagent(target: str) -> str:
    if target in _TARGET_ALIASES:
        return _TARGET_ALIASES[target]
    if target.endswith("_agent"):
        return target[: -len("_agent")]
    return target


@dataclass(frozen=True)
class BuiltinSkill:
    """Parsed SKILL.md ready to be written into the workspace."""

    slug: str  # directory name (also the path slug under skills/)
    name: str  # frontmatter `name` (falls back to slug)
    description: str  # frontmatter `description`
    target: str  # frontmatter `target` (raw)
    subagent_id: str  # mapped subagent id (executor for general skills)
    body: str  # SKILL.md body without the frontmatter block
    # Sibling files bundled with the skill (templates/, reference.md, scripts/…),
    # as (path-relative-to-the-skill-dir, text-content) pairs. These ride the same
    # _system + symlink + memory-read path as the body. Text only — a skill that
    # needs a binary asset is out of scope for the in-memory model.
    resources: tuple[tuple[str, str], ...] = ()


# Input is a trusted, bounded builtin SKILL.md frontmatter block bundled in the
# repo — never user-supplied — so the lazy `.*?` cannot be driven into pathological
# backtracking by an adversary.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)  # NOSONAR python:S5852
# Forgiving YAML reader: builtins only ever use scalar key: value pairs and we
# don't want to depend on PyYAML in this hot path. The leading-whitespace gap is
# matched possessively (`\s*+`) so it never backtracks into the value group,
# keeping the match linear. Trailing whitespace is stripped by the caller.
_KV_RE = re.compile(r"^([A-Za-z_]\w*):\s*+(.+)$")


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        kv = _KV_RE.match(line)
        if kv:
            meta[kv.group(1)] = kv.group(2).strip().strip('"').strip("'")
    body = raw[match.end() :]
    return meta, body


def _load_resources(skill_dir: Path) -> tuple[tuple[str, str], ...]:
    """Read every sibling text file in the skill dir (templates/, reference.md,
    scripts/…) as ``(rel_path, content)`` pairs. ``SKILL.md`` is excluded — its
    body is captured separately. Non-UTF-8 files are skipped (the in-memory
    system-file model is text only)."""
    resources: list[tuple[str, str]] = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.name == "SKILL.md":
            continue
        # Skip build/junk artifacts (e.g. __pycache__/*.pyc, dotfiles) so a stray
        # local file never gets materialized + symlinked as a skill "resource".
        rel_parts = path.relative_to(skill_dir).parts
        if any(part == "__pycache__" or part.startswith(".") for part in rel_parts):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary asset — the in-memory system-file model is text only, so
            # skipping it is by design (see the docstring), not an error.
            continue
        except OSError as exc:
            # A repo-owned template/script that can't be read signals broken
            # packaging or image contents — surface it so the gap is detectable
            # at load time instead of as an opaque downstream docgen failure.
            log.warning(f"skill_loader: skipping unreadable resource {path}: {exc}")
            continue
        resources.append((path.relative_to(skill_dir).as_posix(), content))
    return tuple(resources)


def _load_one(skill_dir: Path) -> BuiltinSkill | None:
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.is_file():
        return None
    raw = skill_path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    name = meta.get("name", skill_dir.name)
    target = meta.get("target", "executor")
    return BuiltinSkill(
        slug=skill_dir.name,
        name=name,
        description=meta.get("description", ""),
        target=target,
        subagent_id=_target_to_subagent(target),
        body=body,
        resources=_load_resources(skill_dir),
    )


@lru_cache(maxsize=1)
def load_builtin_skills() -> tuple[BuiltinSkill, ...]:
    """Walk the SKILL.md library once and return parsed skills.

    Cached because the directory contents don't change at runtime — a code
    deploy is required to add/edit a builtin skill.

    Scale note: these bodies live in process memory (one copy per API replica).
    At the current scale (~30 builtin SKILL.md files, a few hundred KB) that is
    negligible and the fastest possible read. If the library ever grows to
    thousands of skills, switch to a Redis(TTL) -> Mongo/JuiceFS read-through
    cache instead of holding every body in each replica's RAM.
    """
    if not _BUILTIN_ROOT.is_dir():
        return ()
    skills: list[BuiltinSkill] = []
    for entry in sorted(_BUILTIN_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        skill = _load_one(entry)
        if skill is not None:
            skills.append(skill)
    return tuple(skills)


def skills_by_subagent() -> dict[str, list[BuiltinSkill]]:
    """Group skills by mapped subagent id.

    Keys are subagent ids (gmail, googlecalendar, …) plus the special
    "executor" key for general-purpose skills that don't belong to a single
    integration (e.g. create-artifacts, task-management).
    """
    grouped: dict[str, list[BuiltinSkill]] = {}
    for skill in load_builtin_skills():
        grouped.setdefault(skill.subagent_id, []).append(skill)
    return grouped


def integration_subagent_ids() -> Iterable[str]:
    """Subagent ids that own at least one skill (excluding executor)."""
    return tuple(sa for sa in sorted(skills_by_subagent()) if sa != "executor")


@lru_cache(maxsize=1)
def library_hash() -> str:
    """SHA-256 over every skill's (slug, target, body) — stable per deploy.

    Materializers compare this against a per-user marker on disk to skip the
    full rewrite when the library hasn't changed since the user last logged
    in. The hash is hex-truncated to 32 chars — collisions on a corpus of
    ~30 SKILL.md files are not a real concern, and the shorter hash keeps
    the on-disk marker readable when debugging.
    """
    digest = hashlib.sha256()
    for skill in load_builtin_skills():
        # Include every field that determines what gets written to disk.
        digest.update(skill.slug.encode("utf-8"))
        digest.update(b"\0")
        digest.update(skill.target.encode("utf-8"))
        digest.update(b"\0")
        digest.update(skill.body.encode("utf-8"))
        digest.update(b"\0")
        for rel, content in skill.resources:
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(content.encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()[:32]


__all__ = [
    "SKILL_BODY_FILENAME",
    "BuiltinSkill",
    "integration_subagent_ids",
    "library_hash",
    "load_builtin_skills",
    "skills_by_subagent",
]
