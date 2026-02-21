"""
Skill Discovery Service - Generate available skills text for agent prompts.

This module implements the "progressive disclosure" model from the Agent Skills spec:
  Level 1: Only name + description + location injected into system prompt
  Level 2: Agent reads full SKILL.md via vfs_read (on-demand)
  Level 3: Agent reads referenced files via vfs_read/vfs_cmd (on-demand)

The agent uses existing VFS tools (vfs_read, vfs_cmd) to activate skills —
no special-purpose tools needed.

All skills (system + user) live in the same MongoDB collection and are
queried together by get_skills_for_agent() in registry.py.

Caching: get_available_skills_text is cached in Redis (12h TTL).
Invalidation is handled by @CacheInvalidator decorators in registry.py.
"""

from typing import List

from app.agents.skills.models import Skill
from app.agents.skills.registry import get_skills_for_agent
from app.config.loggers import app_logger as logger
from app.constants.cache import (
    SKILLS_TEXT_CACHE_KEY,
    SKILLS_TEXT_CACHE_TTL,
)
from app.decorators.caching import Cacheable


@Cacheable(key_pattern=SKILLS_TEXT_CACHE_KEY, ttl=SKILLS_TEXT_CACHE_TTL)
async def get_available_skills_text(
    user_id: str,
    agent_name: str,
) -> str:
    """Generate plain text skills listing for injection into agent system prompt.

    Queries MongoDB for both user and system skills matching the agent_name
    (unified query via $or). Each skill includes a location for VFS access.
    Results are cached in Redis (12h TTL).

    Args:
        user_id: Owner user ID
        agent_name: Agent name as-is from SubAgentConfig.agent_name
                    (executor, gmail_agent, github_agent, etc.)

    Returns:
        Plain text string for system prompt injection, or empty string if no skills
    """
    try:
        skills = await get_skills_for_agent(user_id, agent_name)

        if not skills:
            return ""

        return _format_skills(skills)

    except Exception as e:
        logger.warning(f"[skills] Failed to generate skills text for {agent_name}: {e}")
        return ""


def _format_skills(skills: List[Skill]) -> str:
    """Format skills as plain text for prompt injection."""
    lines = ["Available Skills:"]

    for skill in skills:
        location = f"{skill.vfs_path}/SKILL.md"

        lines.append(f"- {skill.name}: {skill.description}")
        lines.append(f"  Location: {location}")

        extra_files = [f for f in (skill.files or []) if f != "SKILL.md"]
        if extra_files:
            files_str = ", ".join(extra_files[:10])
            lines.append(f"  Resources: {files_str}")

    return "\n".join(lines)
