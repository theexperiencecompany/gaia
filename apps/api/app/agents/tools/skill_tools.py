"""
Skill Management Tools - LangChain tools for the skills subagent.

These tools handle installing, creating, listing, and managing skills.
The skills subagent is delegated to via handoff when the user wants to
manage their installed skills.
"""

from typing import Annotated

from app.config.loggers import app_logger as logger
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


def _get_user_id(config: RunnableConfig) -> str:
    """Extract user_id from config metadata."""
    metadata = config.get("metadata", {}) if config else {}
    user_id = metadata.get("user_id")
    if not user_id:
        raise ValueError("User ID not found in configuration")
    return user_id


@tool
async def install_skill_from_github(
    config: RunnableConfig,
    repo_url: Annotated[
        str,
        "GitHub repo reference. Examples: 'anthropics/skills', "
        "'https://github.com/owner/repo/tree/main/skills/my-skill', "
        "'owner/repo/skills/my-skill'",
    ],
    skill_path: Annotated[
        str,
        "Path within the repo to the skill folder (e.g., 'skills/pdf-processing'). "
        "Optional if the repo URL already includes the path.",
    ] = "",
    target: Annotated[
        str,
        "Where to make the skill available: 'executor', "
        "or a subagent agent_name like 'gmail_agent', 'github_agent', 'slack_agent'. "
        "Leave empty to use the target from SKILL.md.",
    ] = "",
) -> str:
    """Install a skill from a GitHub repository.

    Downloads the skill folder (SKILL.md + any scripts/resources) from GitHub,
    stores it in the user's virtual filesystem, and registers it for use by agents.

    Examples:
      install_skill_from_github("anthropics/skills", "skills/pdf-processing")
      install_skill_from_github("https://github.com/user/repo/tree/main/my-skill")
      install_skill_from_github("owner/repo/skills/email-templates", target="gmail_agent")
    """
    from app.agents.skills.installer import install_from_github

    user_id = _get_user_id(config)

    try:
        installed = await install_from_github(
            user_id=user_id,
            repo_url=repo_url,
            skill_path=skill_path if skill_path else None,
            target_override=target if target else None,
        )

        files_info = (
            f" ({len(installed.files)} files)" if len(installed.files) > 1 else ""
        )
        return (
            f"Installed skill '{installed.name}' successfully{files_info}.\n"
            f"- Target: {installed.target}\n"
            f"- Description: {installed.description}\n"
            f"- Location: {installed.vfs_path}/SKILL.md\n"
            f"- Source: {installed.source_url}"
        )
    except ValueError as e:
        return f"Failed to install skill: {e}"
    except Exception as e:
        logger.error(f"[skills] GitHub install error: {e}")
        return f"Error installing skill from GitHub: {e}"


@tool
async def create_skill(
    config: RunnableConfig,
    name: Annotated[
        str,
        "Skill name in kebab-case (e.g., 'email-templates', 'pr-review'). "
        "Lowercase letters, numbers, and hyphens only.",
    ],
    description: Annotated[
        str,
        "Clear description of what the skill does and when to use it. "
        "This is how agents decide whether to activate the skill.",
    ],
    instructions: Annotated[
        str,
        "Detailed markdown instructions for the agent to follow. "
        "Include step-by-step procedures, examples, and guidelines.",
    ],
    target: Annotated[
        str,
        "Where to make the skill available: 'executor', "
        "or a subagent agent_name like 'gmail_agent', 'github_agent', 'slack_agent'.",
    ] = "executor",
) -> str:
    """Create a new custom skill from scratch.

    Generates a SKILL.md file from the provided components and stores it
    in the user's virtual filesystem.

    Use this when the user wants to teach GAIA a new procedure, workflow,
    or set of instructions that should be reusable.

    Examples:
      create_skill("standup-format", "Format daily standup messages...",
                    "# Daily Standup\\n1. What I did yesterday...", target="slack_agent")
      create_skill("code-review", "Review PRs following team guidelines...",
                    "# Code Review Checklist\\n...", target="github_agent")
    """
    from app.agents.skills.installer import install_from_inline

    user_id = _get_user_id(config)

    try:
        installed = await install_from_inline(
            user_id=user_id,
            name=name,
            description=description,
            instructions=instructions,
            target=target,
        )

        return (
            f"Created skill '{installed.name}' successfully.\n"
            f"- Target: {installed.target}\n"
            f"- Location: {installed.vfs_path}/SKILL.md\n"
            f"- The skill is now active and will be available to the {target} agent."
        )
    except ValueError as e:
        return f"Failed to create skill: {e}"
    except Exception as e:
        logger.error(f"[skills] Inline create error: {e}")
        return f"Error creating skill: {e}"


@tool
async def list_installed_skills(
    config: RunnableConfig,
    target: Annotated[
        str,
        "Filter by target: 'executor', or a subagent agent_name. "
        "Leave empty to show all skills.",
    ] = "",
) -> str:
    """List all installed skills for the current user.

    Shows skill name, description, target, status (enabled/disabled),
    source, and VFS location.
    """
    from app.agents.skills.registry import list_skills

    user_id = _get_user_id(config)

    try:
        skills = await list_skills(
            user_id=user_id,
            target=target if target else None,
        )

        if not skills:
            filter_msg = f" for target '{target}'" if target else ""
            return f"No skills installed{filter_msg}."

        lines = [f"Installed skills ({len(skills)}):"]
        for skill in skills:
            status = "enabled" if skill.enabled else "disabled"
            source = skill.source.value
            lines.append(
                f"\n- **{skill.name}** [{status}]\n"
                f"  Description: {skill.description}\n"
                f"  Target: {skill.target} | Source: {source}\n"
                f"  Location: {skill.vfs_path}/SKILL.md"
            )
            if skill.source_url:
                lines.append(f"  Source URL: {skill.source_url}")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[skills] List error: {e}")
        return f"Error listing skills: {e}"


@tool
async def manage_skill(
    config: RunnableConfig,
    skill_name: Annotated[
        str,
        "Name of the skill to manage (e.g., 'pr-review', 'email-templates')",
    ],
    action: Annotated[
        str,
        "Action to perform: 'enable', 'disable', or 'uninstall'",
    ],
) -> str:
    """Enable, disable, or uninstall a skill.

    - enable: Activate a disabled skill so agents can use it
    - disable: Deactivate a skill without removing it
    - uninstall: Completely remove the skill and its files
    """
    from app.agents.skills.installer import uninstall_skill_full
    from app.agents.skills.registry import (
        disable_skill,
        enable_skill,
        get_skill_by_name,
    )

    user_id = _get_user_id(config)

    try:
        # Find skill by name
        skill = await get_skill_by_name(user_id, skill_name)
        if not skill or not skill.id:
            return f"Skill '{skill_name}' not found. Use list_installed_skills to see available skills."

        if action == "enable":
            success = await enable_skill(user_id, skill.id)
            return f"Skill '{skill_name}' {'enabled' if success else 'was already enabled'}."

        elif action == "disable":
            success = await disable_skill(user_id, skill.id)
            return f"Skill '{skill_name}' {'disabled' if success else 'was already disabled'}."

        elif action == "uninstall":
            success = await uninstall_skill_full(user_id, skill.id)
            if success:
                return f"Skill '{skill_name}' uninstalled and files removed."
            return f"Failed to uninstall skill '{skill_name}'."

        else:
            return (
                f"Unknown action '{action}'. Use 'enable', 'disable', or 'uninstall'."
            )

    except Exception as e:
        logger.error(f"[skills] Manage error: {e}")
        return f"Error managing skill: {e}"


# Export tools list for registry
tools = [
    install_skill_from_github,
    create_skill,
    list_installed_skills,
    manage_skill,
]
