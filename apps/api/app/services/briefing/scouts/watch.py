"""Replay a scout's frozen calls with no model, and read their results into signals."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from langchain_core.tools import BaseTool

from app.models.playbook_models import PlaybookBody, PlaybookStep
from app.models.scout_models import Signal, SignalSource
from app.services.briefing.scouts.extract import extract_signals
from app.services.briefing.scouts.tools import ScoutIntegration
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.services.workflow.playbook.runner import replay_calls
from app.services.workflow.playbook.tool_space import ToolSpace
from app.utils.errors import AppError


@dataclass(frozen=True, slots=True)
class _ScoutReplay:
    """A scout's frozen calls, as the playbook runner replays them."""

    user_id: str
    description: str
    steps: Sequence[PlaybookStep]
    log_fields: dict[str, str] = field(default_factory=dict)


def read_only_space(tools: dict[str, BaseTool]) -> ToolSpace:
    """Return the only space a scout's calls run in: the integration's read-only tools."""
    return ToolSpace(tools=tools, runtime=None, subagent_id=None)


@dataclass(frozen=True, slots=True)
class FrozenWatch:
    """One integration's frozen calls and where their results hold items."""

    integration: ScoutIntegration
    playbook: PlaybookBody
    sources: Sequence[SignalSource]


async def watch(
    user: PlaybookUser,
    user_id: str,
    frozen: FrozenWatch,
    tools: dict[str, BaseTool],
    now: datetime,
) -> list[Signal]:
    """Replay the frozen calls and return the signals their results hold.

    Raises AppError when a call fails and PlaceholderError when a result changed shape.
    """
    integration = frozen.integration
    replay = await replay_calls(
        _ScoutReplay(
            user_id=user_id,
            description=frozen.playbook.description,
            steps=frozen.playbook.steps,
            log_fields={"scout_integration_id": integration.integration_id},
        ),
        user=user,
        conversation_id=f"scout-{integration.integration_id}-{user_id}-{uuid4().hex[:6]}",
        space=read_only_space(tools),
    )
    if replay.failure is not None:
        raise AppError(
            message=f"scout replay for {integration.integration_id} stopped",
            why=replay.failure,
            fix="relearn the scout against the app's current tools",
        )
    return extract_signals(integration, frozen.sources, replay.values, now)
