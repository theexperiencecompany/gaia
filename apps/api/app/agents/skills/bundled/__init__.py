"""
Bundled Skills - System-level skills that ship with the codebase.

These skills are available to all users and are loaded from the filesystem
at startup. They provide out-of-the-box capabilities for common subagent tasks
like GitHub PR creation, Twitter DMs, Notion page lookup, etc.

The skills are exposed via VFS paths under /system/skills/ which are readable
by all users. This allows testing VFS + skills together.

Directory structure (source files):
    app/agents/skills/bundled/
    ├── github/
    │   └── create-pr/
    │       └── SKILL.md
    ├── twitter/
    │   └── send-dm/
    │       └── SKILL.md
    └── notion/
        └── find-items/
            └── SKILL.md

VFS paths (how agents access them):
    /system/skills/github/create-pr/SKILL.md
    /system/skills/twitter/send-dm/SKILL.md
    /system/skills/notion/find-items/SKILL.md
"""

from functools import lru_cache
from pathlib import Path
from typing import List

from app.agents.skills.models import SkillMetadata
from app.agents.skills.parser import parse_skill_md
from app.services.vfs.path_resolver import get_system_skill_path

BUNDLED_SKILLS_DIR = Path(__file__).parent


class BundledSkill:
    """A skill bundled with the codebase (not user-installed)."""

    def __init__(
        self,
        skill_metadata: SkillMetadata,
        body_content: str,
        relative_path: str,
    ):
        self.skill_metadata = skill_metadata
        self.body_content = body_content
        self.relative_path = relative_path
        self.target = skill_metadata.target
        self.name = skill_metadata.name
        self.description = skill_metadata.description

    def to_xml_element(self) -> str:
        """Generate XML element for this skill (includes inline instructions)."""
        target = self.target or "global"
        location = get_system_skill_path(target, self.name) + "/SKILL.md"

        return f"""<skill>
    <name>{self.name}</name>
    <description>{self.description}</description>
    <target>{target}</target>
    <location>{location}</location>
    <instructions>
{self.body_content}
    </instructions>
</skill>"""


def _load_bundled_skills() -> List[BundledSkill]:
    """Scan the bundled skills directory and load all SKILL.md files."""
    skills: List[BundledSkill] = []
    base_dir = BUNDLED_SKILLS_DIR

    if not base_dir.exists():
        return skills

    for skill_dir in base_dir.rglob("*"):
        if not skill_dir.is_dir():
            continue

        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            continue

        try:
            content = skill_md_path.read_text(encoding="utf-8")
            metadata, body = parse_skill_md(content)

            relative_path = skill_md_path.relative_to(base_dir).parent.as_posix()

            skills.append(
                BundledSkill(
                    skill_metadata=metadata,
                    body_content=body,
                    relative_path=relative_path,
                )
            )
        except Exception as e:
            import logging

            logging.warning(f"Failed to load bundled skill at {skill_md_path}: {e}")

    return skills


@lru_cache(maxsize=1)
def get_all_bundled_skills() -> List[BundledSkill]:
    """Get all bundled skills (cached)."""
    return _load_bundled_skills()


def get_bundled_skills_for_agent(agent_name: str) -> List[BundledSkill]:
    """Get bundled skills available to a specific agent.

    Args:
        agent_name: Agent name (e.g., 'github', 'gmail', 'executor', 'twitter')

    Returns:
        List of bundled skills available to this agent
    """
    all_skills = get_all_bundled_skills()
    agent_name = agent_name.lower().replace("_agent", "")

    matching_skills = []
    for skill in all_skills:
        target = (skill.target or "global").lower()

        if target == "global":
            matching_skills.append(skill)
        elif target == agent_name:
            matching_skills.append(skill)
        elif target == "executor" and agent_name in ("executor", "comms"):
            matching_skills.append(skill)

    return matching_skills


def get_bundled_skills_xml(agent_name: str) -> str:
    """Generate XML for bundled skills available to an agent.

    Args:
        agent_name: Agent name to get skills for

    Returns:
        XML string with <bundled_skills> block, or empty string if none
    """
    skills = get_bundled_skills_for_agent(agent_name)

    if not skills:
        return ""

    skills_xml = "\n".join(skill.to_xml_element() for skill in skills)

    return f"""<bundled_skills>
{skills_xml}
</bundled_skills>"""
