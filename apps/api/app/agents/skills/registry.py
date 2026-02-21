"""
Skill Registry - MongoDB-backed CRUD for installed skills.

Tracks which skills are installed per user, their VFS paths,
and whether they're enabled/disabled. The actual skill content
lives in VFS; this collection stores the index.

Flat schema: all skill fields (name, description, target, etc.) are
top-level document fields. System skills use user_id="system".

Caching: get_skills_for_agent is cached in Redis (12h TTL).
Write operations (install/uninstall/enable/disable) invalidate
both the per-agent user skills cache and the composed skills text cache.
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from app.agents.skills.models import Skill, SkillSource
from app.config.loggers import app_logger as logger
from app.constants.cache import (
    USER_SKILLS_CACHE_KEY,
    USER_SKILLS_CACHE_TTL,
)
from app.decorators.caching import Cacheable, CacheInvalidator

COLLECTION_NAME = "skills"

# Invalidation patterns for write operations — clears all agent variants for the user
_SKILLS_INVALIDATION_PATTERNS = [
    "skills:user:{user_id}:agent:*",
    "skills:text:{user_id}:*",
]


def _get_collection():
    from app.db.mongodb.collections import _get_collection

    return _get_collection(COLLECTION_NAME)


def _skill_to_doc(skill: Skill) -> dict:
    """Convert Skill to MongoDB document (flat schema)."""
    doc = skill.model_dump(exclude={"id"})
    if skill.id:
        doc["_id"] = skill.id
    return doc


def _doc_to_skill(doc: dict) -> Skill:
    """Convert MongoDB document to Skill (flat schema)."""
    doc_copy = dict(doc)
    doc_copy["id"] = str(doc_copy.pop("_id"))
    doc_copy["source"] = SkillSource(doc_copy["source"])
    # Handle datetime strings
    for field in ("installed_at", "updated_at"):
        val = doc_copy.get(field)
        if isinstance(val, str):
            doc_copy[field] = datetime.fromisoformat(val)
    return Skill(**doc_copy)


@CacheInvalidator(key_patterns=_SKILLS_INVALIDATION_PATTERNS)
async def install_skill(
    user_id: str,
    name: str,
    description: str,
    target: str,
    vfs_path: str,
    source: SkillSource,
    source_url: Optional[str] = None,
    body_content: Optional[str] = None,
    files: Optional[List[str]] = None,
    auto_invoke: bool = True,
    license: Optional[str] = None,
    compatibility: Optional[str] = None,
    metadata: Optional[dict[str, str]] = None,
    allowed_tools: Optional[List[str]] = None,
) -> Skill:
    """Register a newly installed skill in the registry.

    Args:
        user_id: Owner user ID (or "system" for system skills)
        name: Skill name (kebab-case)
        description: What the skill does
        target: Target agent (executor, gmail_agent, github_agent, etc.)
        vfs_path: VFS directory path where skill is stored
        source: How it was installed (github, inline, etc.)
        source_url: Original source URL for updates
        body_content: Cached SKILL.md markdown body
        files: List of files in the skill folder
        auto_invoke: Whether the agent can auto-activate this skill
        license: License name or reference
        compatibility: Environment requirements
        metadata: Arbitrary key-value metadata
        allowed_tools: Pre-approved tools

    Returns:
        The created Skill with assigned ID
    """
    collection = _get_collection()

    # Check for duplicate by name + user_id + target
    existing = await collection.find_one(
        {
            "user_id": user_id,
            "name": name,
            "target": target,
        }
    )
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
        auto_invoke=auto_invoke,
        license=license,
        compatibility=compatibility,
        metadata=metadata or {},
        allowed_tools=allowed_tools or [],
        vfs_path=vfs_path,
        source=source,
        source_url=source_url,
        body_content=body_content,
        files=files or [],
        enabled=True,
        installed_at=datetime.now(timezone.utc),
    )

    doc = _skill_to_doc(skill)
    await collection.insert_one(doc)

    logger.info(
        f"[skills] Installed '{name}' for user {user_id} "
        f"(target={target}, source={source.value})"
    )
    return skill


@CacheInvalidator(key_patterns=_SKILLS_INVALIDATION_PATTERNS)
async def uninstall_skill(user_id: str, skill_id: str) -> bool:
    """Remove a skill from the registry.

    Does NOT delete VFS files — caller is responsible for cleanup.

    Args:
        user_id: Owner user ID
        skill_id: Skill document ID

    Returns:
        True if deleted, False if not found
    """
    collection = _get_collection()
    result = await collection.delete_one({"_id": skill_id, "user_id": user_id})
    if result.deleted_count > 0:
        logger.info(f"[skills] Uninstalled skill {skill_id} for user {user_id}")
        return True
    return False


async def get_skill(user_id: str, skill_id: str) -> Optional[Skill]:
    """Get a single installed skill by ID."""
    collection = _get_collection()
    doc = await collection.find_one({"_id": skill_id, "user_id": user_id})
    return _doc_to_skill(doc) if doc else None


async def get_skill_by_name(
    user_id: str, skill_name: str, target: Optional[str] = None
) -> Optional[Skill]:
    """Get an installed skill by name (and optionally target)."""
    collection = _get_collection()
    query: dict = {"user_id": user_id, "name": skill_name}
    if target:
        query["target"] = target
    doc = await collection.find_one(query)
    return _doc_to_skill(doc) if doc else None


async def list_skills(
    user_id: str,
    target: Optional[str] = None,
    enabled_only: bool = False,
) -> List[Skill]:
    """List installed skills for a user.

    Args:
        user_id: Owner user ID
        target: Filter by target (executor, subagent agent_name)
        enabled_only: Only return enabled skills

    Returns:
        List of installed skills
    """
    collection = _get_collection()
    query: dict = {"user_id": user_id}
    if target:
        query["target"] = target
    if enabled_only:
        query["enabled"] = True

    cursor = collection.find(query).sort("installed_at", -1)
    docs = await cursor.to_list(length=500)
    return [_doc_to_skill(doc) for doc in docs]


@Cacheable(key_pattern=USER_SKILLS_CACHE_KEY, ttl=USER_SKILLS_CACHE_TTL)
async def get_skills_for_agent(user_id: str, agent_name: str) -> List[Skill]:
    """Get all enabled skills available to a specific agent.

    Returns skills where target matches the agent_name exactly.
    Includes both user skills (user_id matches) and system skills
    (user_id="system") in a single unified query.

    Results are cached in Redis (12h TTL). Invalidated when skills are
    installed/uninstalled/enabled/disabled.

    Args:
        user_id: Owner user ID
        agent_name: Agent name as-is from SubAgentConfig.agent_name
                    (executor, gmail_agent, github_agent, etc.)

    Returns:
        List of enabled skills available to this agent
    """
    collection = _get_collection()

    query = {
        "enabled": True,
        "target": agent_name,
        "$or": [
            {"user_id": user_id},
            {"user_id": "system"},
        ],
    }

    cursor = collection.find(query).sort("installed_at", -1)
    docs = await cursor.to_list(length=500)
    return [_doc_to_skill(doc) for doc in docs]


@CacheInvalidator(key_patterns=_SKILLS_INVALIDATION_PATTERNS)
async def enable_skill(user_id: str, skill_id: str) -> bool:
    """Enable a skill."""
    collection = _get_collection()
    result = await collection.update_one(
        {"_id": skill_id, "user_id": user_id},
        {
            "$set": {
                "enabled": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    return result.modified_count > 0


@CacheInvalidator(key_patterns=_SKILLS_INVALIDATION_PATTERNS)
async def disable_skill(user_id: str, skill_id: str) -> bool:
    """Disable a skill without uninstalling."""
    collection = _get_collection()
    result = await collection.update_one(
        {"_id": skill_id, "user_id": user_id},
        {
            "$set": {
                "enabled": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    return result.modified_count > 0
