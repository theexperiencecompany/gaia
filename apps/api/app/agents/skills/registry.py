"""
Skill Registry - MongoDB-backed CRUD for installed skills.

Tracks which skills are installed per user, their VFS paths,
and whether they're enabled/disabled. The actual skill content
lives in VFS; this collection stores the index.
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from app.agents.skills.models import InstalledSkill, SkillMetadata, SkillSource
from app.config.loggers import app_logger as logger

COLLECTION_NAME = "skills"


def _get_collection():
    from app.db.mongodb.collections import _get_collection

    return _get_collection(COLLECTION_NAME)


def _skill_to_doc(skill: InstalledSkill) -> dict:
    """Convert InstalledSkill to MongoDB document."""
    doc = skill.model_dump(exclude={"id"})
    doc["skill_metadata"] = skill.skill_metadata.model_dump()
    if skill.id:
        doc["_id"] = skill.id
    return doc


def _doc_to_skill(doc: dict) -> InstalledSkill:
    """Convert MongoDB document to InstalledSkill."""
    doc_copy = dict(doc)
    doc_copy["id"] = str(doc_copy.pop("_id"))
    doc_copy["skill_metadata"] = SkillMetadata(**doc_copy["skill_metadata"])
    doc_copy["source"] = SkillSource(doc_copy["source"])
    # Handle datetime strings
    for field in ("installed_at", "updated_at"):
        val = doc_copy.get(field)
        if isinstance(val, str):
            doc_copy[field] = datetime.fromisoformat(val)
    return InstalledSkill(**doc_copy)


async def install_skill(
    user_id: str,
    skill_metadata: SkillMetadata,
    vfs_path: str,
    source: SkillSource,
    source_url: Optional[str] = None,
    body_content: Optional[str] = None,
    files: Optional[List[str]] = None,
) -> InstalledSkill:
    """Register a newly installed skill in the registry.

    Args:
        user_id: Owner user ID
        skill_metadata: Parsed SKILL.md frontmatter
        vfs_path: VFS directory path where skill is stored
        source: How it was installed (github, inline, etc.)
        source_url: Original source URL for updates
        body_content: Cached SKILL.md markdown body
        files: List of files in the skill folder

    Returns:
        The created InstalledSkill with assigned ID
    """
    collection = _get_collection()

    # Check for duplicate by name + user_id + target
    existing = await collection.find_one(
        {
            "user_id": user_id,
            "skill_metadata.name": skill_metadata.name,
            "skill_metadata.target": skill_metadata.target,
        }
    )
    if existing:
        raise ValueError(
            f"Skill '{skill_metadata.name}' already installed for target "
            f"'{skill_metadata.target}'. Uninstall first or use a different name."
        )

    skill = InstalledSkill(
        id=str(uuid4()),
        user_id=user_id,
        skill_metadata=skill_metadata,
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
        f"[skills] Installed '{skill_metadata.name}' for user {user_id} "
        f"(target={skill_metadata.target}, source={source.value})"
    )
    return skill


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


async def get_skill(user_id: str, skill_id: str) -> Optional[InstalledSkill]:
    """Get a single installed skill by ID."""
    collection = _get_collection()
    doc = await collection.find_one({"_id": skill_id, "user_id": user_id})
    return _doc_to_skill(doc) if doc else None


async def get_skill_by_name(
    user_id: str, skill_name: str, target: Optional[str] = None
) -> Optional[InstalledSkill]:
    """Get an installed skill by name (and optionally target)."""
    collection = _get_collection()
    query: dict = {"user_id": user_id, "skill_metadata.name": skill_name}
    if target:
        query["skill_metadata.target"] = target
    doc = await collection.find_one(query)
    return _doc_to_skill(doc) if doc else None


async def list_skills(
    user_id: str,
    target: Optional[str] = None,
    enabled_only: bool = False,
) -> List[InstalledSkill]:
    """List installed skills for a user.

    Args:
        user_id: Owner user ID
        target: Filter by target (global, executor, subagent ID)
        enabled_only: Only return enabled skills

    Returns:
        List of installed skills
    """
    collection = _get_collection()
    query: dict = {"user_id": user_id}
    if target:
        query["skill_metadata.target"] = target
    if enabled_only:
        query["enabled"] = True

    cursor = collection.find(query).sort("installed_at", -1)
    docs = await cursor.to_list(length=500)
    return [_doc_to_skill(doc) for doc in docs]


async def get_skills_for_agent(user_id: str, agent_name: str) -> List[InstalledSkill]:
    """Get all enabled skills available to a specific agent.

    Returns skills where target is:
    - "global" (available to all agents)
    - Matching the agent_name exactly (e.g., "github", "gmail")

    For executor, also includes "executor" target.

    Args:
        user_id: Owner user ID
        agent_name: Agent name (executor, gmail, github, slack, etc.)

    Returns:
        List of enabled skills available to this agent
    """
    collection = _get_collection()

    # Build target list: always include global
    targets = ["global"]
    if agent_name == "executor":
        targets.append("executor")
    else:
        # For subagents, also match their specific target
        targets.append(agent_name)
        # Strip _agent suffix if present (e.g., "gmail_agent" -> "gmail")
        if agent_name.endswith("_agent"):
            targets.append(agent_name.removesuffix("_agent"))

    query = {
        "user_id": user_id,
        "enabled": True,
        "skill_metadata.target": {"$in": targets},
    }

    cursor = collection.find(query).sort("installed_at", -1)
    docs = await cursor.to_list(length=500)
    return [_doc_to_skill(doc) for doc in docs]


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
