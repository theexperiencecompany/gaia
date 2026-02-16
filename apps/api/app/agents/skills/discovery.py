"""
Skill Discovery Service - Generate <available_skills> XML for agent prompts.

This module implements the "progressive disclosure" model from the Agent Skills spec:
  Level 1: Only name + description + location injected into system prompt (~50-100 tokens per skill)
  Level 2: Agent reads full SKILL.md via vfs_read (on-demand)
  Level 3: Agent reads referenced files via vfs_read/vfs_cmd (on-demand)

The agent uses existing VFS tools (vfs_read, vfs_cmd) to activate skills —
no special-purpose tools needed.

System skills are stored in /system/skills/ (read-only, available to all users).
User skills are stored in their personal VFS under /users/{user_id}/global/skills/custom/.
"""

from typing import List

import yaml  # type: ignore[import-untyped]
from app.agents.skills.models import InstalledSkill
from app.agents.skills.registry import get_skills_for_agent
from app.config.loggers import app_logger as logger
from app.services.vfs.mongo_vfs import MongoVFS

SYSTEM_SKILLS_ROOT = "/system/skills"


async def get_system_skills_for_agent(agent_name: str) -> List[dict]:
    """
    Get system skills available to a specific agent from VFS.

    Scans /system/skills/{target}/ directories and reads SKILL.md files.

    Args:
        agent_name: Agent name (github, gmail, twitter, executor, etc.)

    Returns:
        List of skill dicts with name, description, target, location
    """
    skills: List[dict] = []
    agent_name = agent_name.lower().replace("_agent", "")

    try:
        vfs = MongoVFS()

        # List all targets under /system/skills/
        try:
            targets = await vfs.list_dir(SYSTEM_SKILLS_ROOT, user_id="system")
        except Exception:
            return skills

        for target_dir in targets.items:
            if target_dir.node_type.value != "folder":
                continue

            target_name = target_dir.name

            # Check if this target matches the agent
            if target_name not in (agent_name, "global"):
                continue

            # List skills in this target directory
            try:
                skill_dirs = await vfs.list_dir(
                    f"{SYSTEM_SKILLS_ROOT}/{target_name}", user_id="system"
                )
            except Exception as e:
                logger.debug(f"[skills] Failed to list skills in {target_name}: {e}")
                continue

            for skill_dir in skill_dirs.items:
                if skill_dir.node_type.value != "folder":
                    continue

                skill_name = skill_dir.name
                skill_md_path = (
                    f"{SYSTEM_SKILLS_ROOT}/{target_name}/{skill_name}/SKILL.md"
                )

                # Read SKILL.md content
                try:
                    content = await vfs.append(skill_md_path, "", user_id="system")
                    if not content:
                        continue

                    # Parse frontmatter
                    name, description = _parse_skill_frontmatter(content)
                    if not name:
                        name = skill_name

                    skills.append(
                        {
                            "name": name,
                            "description": description or f"Skill: {skill_name}",
                            "target": target_name,
                            "location": skill_md_path,
                        }
                    )
                except Exception as e:
                    logger.debug(f"[skills] Failed to read {skill_md_path}: {e}")

    except Exception as e:
        logger.warning(f"[skills] Failed to get system skills: {e}")

    return skills


def _parse_skill_frontmatter(content: str) -> tuple[str | None, str | None]:
    """Parse name and description from SKILL.md frontmatter."""
    import re

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return None, None

    try:
        frontmatter = yaml.safe_load(match.group(1))
        if isinstance(frontmatter, dict):
            return frontmatter.get("name"), frontmatter.get("description")
    except Exception as e:
        logger.debug(f"[skills] Failed to parse YAML frontmatter: {e}")

    return None, None


async def get_available_skills_xml(
    user_id: str,
    agent_name: str,
) -> str:
    """Generate <available_skills> XML for injection into agent system prompt.

    Merges both user-installed skills (from MongoDB) and system skills
    (from /system/skills/ VFS). All skills use <location> for VFS access.

    Args:
        user_id: Owner user ID
        agent_name: Agent name (executor, gmail_agent, github_agent, etc.)

    Returns:
        XML string for system prompt injection, or empty string if no skills
    """
    try:
        # Get user-installed skills from MongoDB
        user_skills = await get_skills_for_agent(user_id, agent_name)

        # Get system skills from VFS
        system_skills = await get_system_skills_for_agent(agent_name)

        parts: List[str] = []

        # Add system skills first (they're read-only and available to all)
        if system_skills:
            parts.append(_format_system_skills_xml(system_skills))

        # Add user-installed skills
        if user_skills:
            parts.append(_format_skills_xml(user_skills))

        if not parts:
            return ""

        return "\n\n".join(parts)

    except Exception as e:
        logger.warning(f"[skills] Failed to generate skills XML for {agent_name}: {e}")
        return ""


def _format_system_skills_xml(skills: List[dict]) -> str:
    """Format system skills as <available_skills> XML."""
    lines = ["<available_skills>"]

    for skill in skills:
        name = skill.get("name", "unknown")
        description = skill.get("description", "")
        target = skill.get("target", "global")
        location = skill.get("location", "")

        lines.append("  <skill>")
        lines.append(f"    <name>{_escape_xml(name)}</name>")
        lines.append(f"    <description>{_escape_xml(description)}</description>")
        lines.append(f"    <target>{_escape_xml(target)}</target>")
        lines.append(f"    <location>{_escape_xml(location)}</location>")
        lines.append("  </skill>")

    lines.append("</available_skills>")
    return "\n".join(lines)


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
        extra_files = [f for f in (skill.files or []) if f != "SKILL.md"]
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
