"""
Skill Registry - repository-backed CRUD for installed skills.

Tracks which skills are installed per user, their VFS paths, and whether they're
enabled/disabled. The actual skill content lives in VFS; the ``skills`` collection
stores the index (see ``SkillsRepository``). System skills use user_id="system".

Caching: get_skills_for_agent is cached in Redis (12h TTL). Write operations
(install/uninstall/enable/disable) invalidate both the per-agent user skills cache
and the composed skills text cache.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.agents.skills.models import Skill, SkillSource, SkillUpdate
from app.constants.cache import (
    USER_SKILLS_CACHE_KEY,
    USER_SKILLS_CACHE_TTL,
)
from app.constants.log_tags import LogTag
from app.db.repositories.skills import skill_repository
from app.decorators.caching import Cacheable, CacheInvalidator
from shared.py.wide_events import SkillContext, log

# Invalidation patterns for write operations — clears all agent variants for the user
_SKILLS_INVALIDATION_PATTERNS = [
    "skills:user:{user_id}:agent:*",
    # Must track the version prefix in SKILLS_TEXT_CACHE_KEY; without the
    # ``v2:`` segment this glob never matches the cached key, so the skills
    # listing would stay stale for the full TTL after an install/uninstall.
    "skills:text:v2:{user_id}:*",
]


@CacheInvalidator(key_patterns=_SKILLS_INVALIDATION_PATTERNS)
async def install_skill(
    user_id: str,
    name: str,
    description: str,
    target: str,
    vfs_path: str,
    source: SkillSource,
    source_url: str | None = None,
    body_content: str | None = None,
    files: list[str] | None = None,
    skill_license: str | None = None,
    compatibility: str | None = None,
    metadata: dict[str, str] | None = None,
    allowed_tools: list[str] | None = None,
) -> Skill:
    """Register a newly installed skill in the registry.

    Returns the created Skill with its assigned ID. Raises ``ValueError`` if a
    skill with the same name already exists for the same target.
    """
    log.set(
        user_id=user_id,
        skill=SkillContext(operation="install", skill_name=name),
    )

    # Check for duplicate by name + user_id + target
    existing = await skill_repository.find_by_name(user_id, name, target)
    if existing:
        raise ValueError(
            f"Skill '{name}' already installed for target "
            f"'{target}'. Uninstall first or use a different name."
        )

    skill = Skill(
        id=str(uuid4()),
        user_id=user_id,
        name=name,
        description=description,
        target=target,
        license=skill_license,
        compatibility=compatibility,
        metadata=metadata or {},
        allowed_tools=allowed_tools or [],
        vfs_path=vfs_path,
        source=source,
        source_url=source_url,
        body_content=body_content,
        files=files or [],
        enabled=True,
        installed_at=datetime.now(UTC),
    )

    await skill_repository.create(skill)

    log.info(
        f"{LogTag.SKILLS} Installed skill for user",
        skill_name=name,
        user_id=user_id,
        target=target,
        source=source.value,
    )
    return skill


@CacheInvalidator(key_patterns=_SKILLS_INVALIDATION_PATTERNS)
async def uninstall_skill(user_id: str, skill_id: str) -> bool:
    """Remove a skill from the registry. Does NOT delete VFS files — caller cleans up."""
    log.set(user_id=user_id, skill=SkillContext(operation="delete", skill_id=skill_id))
    deleted = await skill_repository.delete_for_user(skill_id, user_id)
    log.set_ns("skill", success=deleted)
    if deleted:
        log.info(f"{LogTag.SKILLS} Uninstalled skill", skill_id=skill_id, user_id=user_id)
    return deleted


async def get_skill(user_id: str, skill_id: str) -> Skill | None:
    """Get a single installed skill by ID."""
    return await skill_repository.get_for_user(skill_id, user_id)


async def get_skill_by_name(
    user_id: str, skill_name: str, target: str | None = None
) -> Skill | None:
    """Get an installed skill by name (and optionally target)."""
    return await skill_repository.find_by_name(user_id, skill_name, target)


async def list_skills(
    user_id: str,
    target: str | None = None,
    enabled_only: bool = False,
) -> list[Skill]:
    """List installed skills for a user (optionally by target / enabled-only)."""
    return await skill_repository.list_for_user(user_id, target=target, enabled_only=enabled_only)


@Cacheable(key_pattern=USER_SKILLS_CACHE_KEY, ttl=USER_SKILLS_CACHE_TTL)
async def get_skills_for_agent(user_id: str, agent_name: str) -> list[Skill]:
    """Get all enabled skills available to a specific agent.

    Returns skills where target matches the agent_name exactly. Includes both
    user skills and system skills (user_id="system"). Cached in Redis (12h TTL),
    invalidated on install/uninstall/enable/disable.
    """
    log.set(user_id=user_id, agent_name=agent_name, skill=SkillContext(operation="get"))
    skills = await skill_repository.for_agent(user_id, agent_name)
    log.set_ns("skill", result_count=len(skills))
    return skills


@CacheInvalidator(key_patterns=_SKILLS_INVALIDATION_PATTERNS)
async def enable_skill(user_id: str, skill_id: str) -> bool:
    """Enable a skill."""
    return await skill_repository.set_enabled(user_id, skill_id, True)


@CacheInvalidator(key_patterns=_SKILLS_INVALIDATION_PATTERNS)
async def disable_skill(user_id: str, skill_id: str) -> bool:
    """Disable a skill without uninstalling."""
    return await skill_repository.set_enabled(user_id, skill_id, False)


@CacheInvalidator(key_patterns=_SKILLS_INVALIDATION_PATTERNS)
async def update_skill(user_id: str, skill_id: str, fields: dict[str, Any]) -> Skill | None:
    """Patch metadata fields on an existing skill and return the updated record.

    Always stamps ``updated_at``. Scoped to ``{_id, user_id}`` so a user can only
    edit their own skills. Returns None if no matching skill exists.
    """
    log.set(user_id=user_id, skill=SkillContext(skill_id=skill_id))
    updated = await skill_repository.patch(user_id, skill_id, update=SkillUpdate(**fields))
    log.set_ns("skill", success=updated is not None)
    if updated is not None:
        log.info(f"{LogTag.SKILLS} Updated skill", skill_id=skill_id, user_id=user_id)
    return updated
