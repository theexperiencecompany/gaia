"""Mutation-tool factory — one uniform wrapper for tools that change user state.

Every "expose a service as a tool" surface shares the same envelope: extract the
user from the run config, log the call, apply through the owning service,
capture analytics only AFTER the mutation succeeded, schedule a projection
resync, and turn failures into structured tool-result strings instead of
raising into the graph. This factory IS that envelope — a domain supplies only
its args schema and an ``apply`` coroutine of real business logic, so twenty
tool modules don't each re-derive it (and drift).

HIL note: tools built here are ordinary registry tools. Gating posture is
stamped at registration time (``Tool.always_gate``), never inside the wrapper.
"""

from collections.abc import Awaitable, Callable

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel

from app.constants.log_tags import LogTag
from app.models.agent_models import agent_configurable
from app.services.analytics_service import capture_context_event
from app.utils.errors import AppError
from shared.py.wide_events import log


def user_id_from_config(config: RunnableConfig | None) -> str | None:
    """The run's user id from configurable or metadata, else None."""
    configurable = agent_configurable(config) if config else {}
    metadata = config.get("metadata", {}) if config else {}
    user_id = configurable.get("user_id") or metadata.get("user_id")
    if not isinstance(user_id, str):
        return None
    return user_id.strip() or None


def define_mutation_tool(
    *,
    name: str,
    area: str,
    description: str,
    args_model: type[BaseModel],
    apply: Callable[..., Awaitable[str]],
    resync: Callable[[str], None] | None = None,
    event: str | None = None,
) -> BaseTool:
    """Build a state-changing tool around ``apply``.

    ``apply(user_id, **args)`` runs the real mutation through the owning
    service/repository and returns the agent-facing confirmation text; raise
    ``AppError`` (or anything else) to fail the call loud. ``event`` is captured
    with ``{"area": area}`` only on success. ``resync`` schedules the owning
    area's projection refresh, fire-and-forget.
    """

    @tool(name, description=description, args_schema=args_model)
    async def _mutation(config: RunnableConfig, **kwargs: object) -> str:
        log.set(tool={"name": name, "action": "mutate"}, surface={"area": area})
        user_id = user_id_from_config(config)
        if not user_id:
            return "Error: user authentication required."

        try:
            result = await apply(user_id, **kwargs)
        except AppError as e:
            detail = f"Error: {e.message}"
            if e.fix:
                detail += f" Fix: {e.fix}"
            return detail
        except Exception as e:
            log.error(
                f"{LogTag.TOOL} mutation failed",
                tool=name,
                error_type=type(e).__name__,
                error=str(e),
            )
            return f"Error: {name} did not complete ({type(e).__name__})."

        if event is not None:
            capture_context_event(event, {"area": area})
        if resync is not None:
            resync(user_id)
        return result

    return _mutation


__all__ = ["define_mutation_tool", "user_id_from_config"]
