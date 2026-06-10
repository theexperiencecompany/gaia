"""
Skill Discovery Service - Generate available skills text for agent prompts.

This module implements the "progressive disclosure" model from the Agent Skills spec:
  Level 1: Only name + description + location injected into system prompt
  Level 2: Agent reads full SKILL.md via the `read` tool (on-demand)
  Level 3: Agent reads referenced files via `read` / `bash` (on-demand)

The agent activates a skill by reading its file with the `read` tool (which reads
host-side from JuiceFS — no sandbox spin-up); skill bodies are materialized into
the user's workspace.

Two sources are merged into the one "Available Skills:" listing:
  - Built-in skills — shipped in the repo, loaded into process memory by
    skill_loader (NOT stored in Mongo). Surfaced straight from memory here.
  - User/system skills — installed per user, stored in MongoDB and queried by
    get_skills_for_agent().

If the builtin library ever grows to thousands of skills, move the memory read to
a Redis(TTL) -> Mongo/JuiceFS read-through cache (see load_builtin_skills).

Caching: get_available_skills_text is cached in Redis (12h TTL).
Invalidation is handled by @CacheInvalidator decorators in registry.py.
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
from app.decorators.caching import Cacheable
from shared.py.wide_events import log

# Subagent id for executor-target builtins (matches skill_loader's mapping and
# the `subagent_id or "executor"` fallback in subagent_helpers).
_EXECUTOR_AGENT_NAME = "executor"


def _builtin_entries(agent_name: str) -> list[tuple[str, str, str]]:
    """Return ``(name, description, location)`` for builtins targeting ``agent_name``.

    Builtins are not stored in Mongo, so the Mongo-backed ``get_skills_for_agent``
    never returned them — the index was silently empty of the entire builtin
    library. We surface them straight from process memory. The location mirrors
    exactly what ``storage.sessions.skills`` materializes on JuiceFS, so the
    ``read(location)`` the agent is told to call actually resolves.
    """
    entries: list[tuple[str, str, str]] = []
    for skill in load_builtin_skills():
        if skill.subagent_id != agent_name:
            continue
        # Built from the same helper the materializer uses, so the location the
        # agent is told to read() always matches the file actually on disk.
        location = f"{WORKSPACE_ROOT}/{builtin_skill_rel_path(skill)}"
        entries.append((skill.name, skill.description, location))
    return entries


@Cacheable(key_pattern=SKILLS_TEXT_CACHE_KEY, ttl=SKILLS_TEXT_CACHE_TTL)
async def get_available_skills_text(
    user_id: str,
    agent_name: str,
) -> str:
    """Generate plain text skills listing for injection into agent system prompt.

    Merges builtin skills (process memory) with user/system skills (MongoDB) for
    the given agent_name. Each entry includes a location the `read` tool can open.
    Results are cached in Redis (12h TTL).

    Args:
        user_id: Owner user ID
        agent_name: Agent name as-is from SubAgentConfig.agent_name
                    (executor, gmail_agent, github_agent, etc.)

    Returns:
        Plain text string for system prompt injection, or empty string if no skills
    """
    log.set(user_id=user_id, agent_name=agent_name, skill_op="get_available_skills_text")

    # Builtins come from process memory and are always available. Only the
    # executor needs them merged here: integration subagents already get their
    # builtins via system_docs.integration_skills_block, so merging there too
    # would list them twice. Fetch first so a Mongo hiccup can't hide them.
    builtins = _builtin_entries(agent_name) if agent_name == _EXECUTOR_AGENT_NAME else []
    try:
        user_skills = await get_skills_for_agent(user_id, agent_name)
    except Exception as e:
        log.warning(f"[skills] Failed to load user skills for {agent_name}: {e}")
        user_skills = []

    if not builtins and not user_skills:
        return ""

    log.set(skill_count=len(builtins) + len(user_skills))
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
