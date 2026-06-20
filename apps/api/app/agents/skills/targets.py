"""Skill targets - the places a skill can run.

A skill's ``target`` is either the general ``executor`` or a connected
integration subagent's ``agent_name``. The settings UI offers exactly these as
options, and the REST endpoints validate writes against them so a skill can
never be scoped to an integration the user hasn't connected.
"""

from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.skills.models import SkillTarget
from app.constants.skills import EXECUTOR_SUBAGENT_ID, EXECUTOR_TARGET_LABEL
from app.services.integrations.user_integrations import get_connected_integration_ids


async def get_skill_targets(user_id: str) -> list[SkillTarget]:
    """Return the skill targets available to a user.

    Always includes the executor (the general assistant). Adds one entry per
    connected integration that exposes a subagent, using the subagent registry
    as the single source of truth for its ``agent_name`` and display name.
    """
    targets: list[SkillTarget] = [
        SkillTarget(
            value=EXECUTOR_SUBAGENT_ID,
            label=EXECUTOR_TARGET_LABEL,
            icon=EXECUTOR_SUBAGENT_ID,
            connected=True,
        )
    ]

    connected_ids = await get_connected_integration_ids(user_id)
    for integration_id in sorted(connected_ids):
        subagent = get_subagent_by_id(integration_id)
        if not subagent or not subagent.config.has_subagent:
            continue
        targets.append(
            SkillTarget(
                value=subagent.config.agent_name,
                label=subagent.name,
                icon=subagent.id,
                connected=True,
            )
        )

    return targets
