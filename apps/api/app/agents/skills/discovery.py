"""
Skill Discovery Service - Generate <available_skills> XML for agent prompts.

This module implements the "progressive disclosure" model from the Agent Skills spec:
  Level 1: Only name + description + location injected into system prompt (~50-100 tokens per skill)
  Level 2: Agent reads full SKILL.md via vfs_read (on-demand)
  Level 3: Agent reads referenced files via vfs_read/vfs_cmd (on-demand)

The agent uses existing VFS tools (vfs_read, vfs_cmd) to activate skills —
no special-purpose tools needed.
"""

from typing import List

from app.agents.skills.models import InstalledSkill
from app.agents.skills.registry import get_skills_for_agent
from app.config.loggers import app_logger as logger


async def get_available_skills_xml(
    user_id: str,
    agent_name: str,
) -> str:
    """Generate <available_skills> XML for injection into agent system prompt.

    Only includes enabled skills matching the agent's scope. Returns lightweight
    metadata (name + description + VFS location) per the progressive disclosure model.

    Args:
        user_id: Owner user ID
        agent_name: Agent name (executor, gmail_agent, github_agent, etc.)

    Returns:
        XML string for system prompt injection, or empty string if no skills
    """
    try:
        skills = await get_skills_for_agent(user_id, agent_name)

        if not skills:
            return ""

        return _format_skills_xml(skills)

    except Exception as e:
        logger.warning(f"[skills] Failed to generate skills XML for {agent_name}: {e}")
        return ""


def _format_skills_xml(skills: List[InstalledSkill]) -> str:
    """Format installed skills as <available_skills> XML.

    Follows the Agent Skills integration spec format with <location> field
    pointing to the SKILL.md path in VFS.
    """
    lines = ["<available_skills>"]

    for skill in skills:
        meta = skill.skill_metadata
        location = f"{skill.vfs_path}/SKILL.md"

        lines.append("  <skill>")
        lines.append(f"    <name>{_escape_xml(meta.name)}</name>")
        lines.append(f"    <description>{_escape_xml(meta.description)}</description>")
        lines.append(f"    <location>{_escape_xml(location)}</location>")

        # Include file listing so agent knows what resources exist
        extra_files = [f for f in skill.files if f != "SKILL.md"]
        if extra_files:
            files_str = ", ".join(extra_files[:10])
            lines.append(f"    <resources>{_escape_xml(files_str)}</resources>")

        lines.append("  </skill>")

    lines.append("</available_skills>")
    return "\n".join(lines)


def _escape_xml(text: str) -> str:
    """Basic XML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
