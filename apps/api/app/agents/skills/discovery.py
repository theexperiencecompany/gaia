"""Skill Discovery Service - Generate available skills text for agent prompts.

Implements the "progressive disclosure" model from the Agent Skills spec:
name/description/location injected into the prompt, full SKILL.md and
referenced files read on-demand via read/bash. Two sources merge into one
"Available Skills:" listing: built-in skills (shipped in the repo, loaded
into process memory, NOT in Mongo) and user/system skills (installed per
user, MongoDB via get_skills_for_agent()). Cached in Redis (12h TTL);
invalidated by @CacheInvalidator decorators in registry.py.
"""

from app.agents.skills.models import Skill
from app.agents.skills.registry import get_skills_for_agent
from app.agents.workspace.paths import WORKSPACE_ROOT
from app.agents.workspace.skill_loader import load_builtin_skills
from app.agents.workspace.system_files import builtin_skill_rel_path
from app.constants.cache import (
    SKILLS_TEXT_CACHE_KEY,
    SKILLS_TEXT_CACHE_TTL,
)
from app.constants.log_tags import LogTag
from app.constants.skills import EXECUTOR_SUBAGENT_ID
from app.decorators.caching import Cacheable
from shared.py.wide_events import SkillContext, log


def _builtin_entries(agent_name: str) -> list[tuple[str, str, str]]:
    """Return (name, description, location) for builtins targeting agent_name.

    Builtins are not stored in Mongo, so get_skills_for_agent never returns
    them — surfaced straight from process memory instead. The location
    mirrors what storage.sessions.skills materializes on JuiceFS, so the
    agent's read(location) actually resolves.
    """
    entries: list[tuple[str, str, str]] = []
    for skill in load_builtin_skills():
        if skill.subagent_id != agent_name:
            continue
        # Same helper the materializer uses, so read() matches the disk file.
        location = f"{WORKSPACE_ROOT}/{builtin_skill_rel_path(skill)}"
        entries.append((skill.name, skill.description, location))
    return entries


@Cacheable(key_pattern=SKILLS_TEXT_CACHE_KEY, ttl=SKILLS_TEXT_CACHE_TTL)
async def get_available_skills_text(
    user_id: str,
    agent_name: str,
) -> str:
    """Generate plain text skills listing for injection into agent system prompt.

    Merges builtin skills (process memory) with user/system skills (MongoDB)
    for agent_name. Each entry includes a location the read tool can open.
    """
    log.set(user_id=user_id, agent_name=agent_name, skill=SkillContext(operation="get"))

    # Only the executor needs builtins merged here: activated integrations
    # already get theirs via system_docs.integration_skills_block, so merging
    # there too would list them twice. Fetch first so a Mongo hiccup can't hide them.
    builtins = _builtin_entries(agent_name) if agent_name == EXECUTOR_SUBAGENT_ID else []
    try:
        user_skills = await get_skills_for_agent(user_id, agent_name)
    except Exception as e:
        log.warning(
            f"{LogTag.SKILLS} Failed to load user skills",
            agent_name=agent_name,
            error_type=type(e).__name__,
            error=str(e),
        )
        user_skills = []

    if not builtins and not user_skills:
        return ""

    log.set_ns("skill", result_count=len(builtins) + len(user_skills))
    return _format_skills(builtins, user_skills)


def _format_skills(builtins: list[tuple[str, str, str]], user_skills: list[Skill]) -> str:
    """Format builtin + user skills as plain text for prompt injection."""
    lines = ["Available Skills:"]

    for name, description, location in builtins:
        lines.append(f"- {name}: {description}")
        lines.append(f"  Location: {location}")

    for skill in user_skills:
        location = f"{skill.vfs_path}/SKILL.md"
        lines.append(f"- {skill.name}: {skill.description}")
        lines.append(f"  Location: {location}")

        extra_files = [f for f in (skill.files or []) if f != "SKILL.md"]
        if extra_files:
            files_str = ", ".join(extra_files[:10])
            lines.append(f"  Resources: {files_str}")

    return "\n".join(lines)
