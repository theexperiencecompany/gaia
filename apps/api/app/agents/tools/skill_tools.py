"""
Skill Management Tools - LangChain tools for the skills subagent.

These tools handle installing, creating, listing, and managing skills.
The skills subagent is delegated to via handoff when the user wants to
manage their installed skills.
"""

import json
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator

from app.agents.skills.installer import (
    install_from_github,
    install_from_inline,
    uninstall_skill_full,
)
from app.agents.skills.registry import (
    disable_skill,
    enable_skill,
    get_skill_by_name,
    list_skills,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


def _get_user_id(config: RunnableConfig) -> str:
    """Extract user_id from config metadata."""
    metadata = config.get("metadata", {}) if config else {}
    user_id = metadata.get("user_id")
    if not isinstance(user_id, str) or not user_id:
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
    log.set(tool={"name": "install_skill_from_github", "action": "install"})
    user_id = _get_user_id(config)

    try:
        installed = await install_from_github(
            user_id=user_id,
            repo_url=repo_url,
            skill_path=skill_path or None,
            target_override=target or None,
        )

        files_info = f" ({len(installed.files)} files)" if len(installed.files) > 1 else ""
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
        log.error(f"{LogTag.TOOL} GitHub install error", error_type=type(e).__name__)
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
    log.set(tool={"name": "create_skill", "action": "create"})
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
        log.error(f"{LogTag.TOOL} Inline create error", error_type=type(e).__name__)
        return f"Error creating skill: {e}"


@tool
async def list_installed_skills(
    config: RunnableConfig,
    target: Annotated[
        str,
        "Filter by target: 'executor', or a subagent agent_name. Leave empty to show all skills.",
    ] = "",
) -> str:
    """List all installed skills for the current user.

    Shows skill name, description, target, status (enabled/disabled),
    source, and VFS location.
    """
    log.set(tool={"name": "list_installed_skills", "action": "list"})
    user_id = _get_user_id(config)

    try:
        skills = await list_skills(
            user_id=user_id,
            target=target or None,
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
        log.error(f"{LogTag.TOOL} List error", error_type=type(e).__name__)
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
    log.set(tool={"name": "manage_skill", "action": action})
    user_id = _get_user_id(config)

    try:
        # Find skill by name
        skill = await get_skill_by_name(user_id, skill_name)
        if not skill or not skill.id:
            return f"Skill '{skill_name}' not found. Use list_installed_skills to see available skills."

        if action == "enable":
            success = await enable_skill(user_id, skill.id)
            return f"Skill '{skill_name}' {'enabled' if success else 'was already enabled'}."

        if action == "disable":
            success = await disable_skill(user_id, skill.id)
            return f"Skill '{skill_name}' {'disabled' if success else 'was already disabled'}."

        if action == "uninstall":
            uninstalled = await uninstall_skill_full(user_id, skill.id)
            if uninstalled:
                return f"Skill '{skill_name}' uninstalled and files removed."
            return f"Failed to uninstall skill '{skill_name}'."

        return f"Unknown action '{action}'. Use 'enable', 'disable', or 'uninstall'."

    except Exception as e:
        log.error(f"{LogTag.TOOL} Manage error", error_type=type(e).__name__)
        return f"Error managing skill: {e}"


class LearnedSkillStep(BaseModel):
    """One step in a learned skill: which tool to call, with what, and why."""

    goal: str = Field(
        description="What this step accomplishes (e.g. 'find the email thread', 'flag it as action-needed')"
    )
    tool: str = Field(description="Name of the tool to call (e.g. 'gmail_search', 'create_todo')")
    args: dict[str, Any] = Field(
        default_factory=dict,
        description="Example arguments for the tool, as a JSON object. Use template placeholders "
        'where values vary per run (e.g. {"email_id": "<the email id from step 1>"}).',
    )
    notes: str | None = Field(
        default=None,
        description="Optional guidance for this step: pitfalls, what to check before moving on, "
        "how to adapt the args.",
    )

    @field_validator("goal", "tool")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class LearnedSkillSpec(BaseModel):
    """Structured recipe for a reusable skill learned from a successful run."""

    name: str = Field(description="Skill name in kebab-case (lowercase letters, numbers, hyphens)")
    description: str = Field(
        description="What the skill does and WHEN to use it, so the agent knows when to activate "
        "it. Include trigger phrases."
    )
    target: str = Field(
        default="executor",
        description="Where to make the skill available: 'executor' or a subagent agent_name.",
    )
    when_to_use: str = Field(
        default="",
        description="Optional plain-language trigger conditions. Empty if covered by description.",
    )
    integrations: list[str] = Field(
        default_factory=list,
        description="Integration subagent ids the skill needs connected (e.g. ['gmail'], "
        "['github'], [] for none). These surface as prerequisites in the skill.",
    )
    steps: list[LearnedSkillStep] = Field(
        min_length=1,
        description="ORDERED steps that make up the skill. List them in the exact order they "
        "must run; each step names the tool to call and its arguments.",
    )


def _compose_learned_skill_md(spec: LearnedSkillSpec) -> str:
    """Compose the SKILL.md body (markdown instructions) from a structured spec."""
    lines: list[str] = []
    if spec.when_to_use:
        lines.append("## When to Activate")
        lines.append(spec.when_to_use.strip())
        lines.append("")

    if spec.integrations:
        lines.append("## Prerequisites")
        lines.append("These integrations must be connected for this skill to work:")
        for integration in spec.integrations:
            lines.append(f"- `{integration}`")
        lines.append("")

    lines.append("## Steps")
    for index, step in enumerate(spec.steps, start=1):
        lines.append(f"### Step {index}: {step.goal.strip()}")
        lines.append(f"Call `{step.tool}` with:")
        if step.args:
            lines.append("```json")
            lines.append(json.dumps(step.args, indent=2, ensure_ascii=False))
            lines.append("```")
        else:
            lines.append("- no arguments")
        if step.notes:
            lines.append("")
            lines.append(step.notes.strip())
        lines.append("")

    return "\n".join(lines).strip() + "\n"


@tool
async def save_learned_skill(
    config: RunnableConfig,
    spec: Annotated[
        LearnedSkillSpec,
        "A structured recipe for a reusable skill learned from a successful run. Provide the "
        "full ordered steps (each naming the tool to call and example args), which integrations "
        "must be connected, and when the skill should be used.",
    ],
) -> str:
    """Save a reusable skill learned from a successful multi-step run.

    Turns the winning tool sequence into a persistent skill the executor (or a
    subagent) can reuse next time, instead of re-deriving the approach from
    scratch. The skill is stored per-user, shows up in the agent's "Available
    Skills" listing, and is activated by reading its SKILL.md.

    Use this at the END of a task that took several tool calls to complete and
    that the user is likely to repeat (e.g. 'find my support requests', 'triage
    my inbox', 'digest this month's receipts'). Do NOT use it for one-off or
    trivial tasks. The `steps` you list should be the exact tool sequence that
    worked this run, with example args and any pitfalls you hit.
    """
    log.set(tool={"name": "save_learned_skill", "action": "save"})
    user_id = _get_user_id(config)

    try:
        body = _compose_learned_skill_md(spec)
        installed = await install_from_inline(
            user_id=user_id,
            name=spec.name,
            description=spec.description,
            instructions=body,
            target=spec.target,
            extra_metadata={"source": "learned", "learned_from_run": "1"},
        )
        return (
            f"Saved skill '{installed.name}' successfully.\n"
            f"- Target: {installed.target}\n"
            f"- Integrations: {', '.join(spec.integrations) if spec.integrations else 'none'}\n"
            f"- Steps: {len(spec.steps)}\n"
            f"- Location: {installed.vfs_path}/SKILL.md\n"
            f"- The skill is now active and will appear in the {spec.target} agent's "
            "Available Skills. Next time this task comes up, it runs the saved steps instead "
            "of re-deriving them."
        )
    except ValueError as e:
        log.set(tool={"name": "save_learned_skill", "action": "save", "error": "invalid_spec"})
        log.error(f"{LogTag.TOOL} Learned-skill save rejected", error=str(e), user_id=user_id)
        return "Failed to save skill: the recipe is invalid (check the name and step fields)."
    except Exception as e:
        log.set(tool={"name": "save_learned_skill", "action": "save", "error": "persist_failed"})
        log.error(f"{LogTag.TOOL} Learned-skill save error", error=str(e), user_id=user_id)
        return "Error saving skill: the skill could not be persisted. Try again."


# Export tools list for registry
tools = [
    install_skill_from_github,
    create_skill,
    save_learned_skill,
    list_installed_skills,
    manage_skill,
]
