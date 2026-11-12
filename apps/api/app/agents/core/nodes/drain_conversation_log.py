"""The comms pre-model hook that hands a running attempt the later log entries the step absorbed into it.

The conversation runner opens one feed per attempt and names it in the run's
configurable; a comms run without that key (every run the runner did not start)
leaves the hook inert. Fed messages are staged under INJECTED_MESSAGES_KEY, so
the model node commits them with its response.
"""

from collections.abc import Sequence
from typing import cast

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

from app.models.agent_models import agent_configurable
from app.override.langgraph_bigtool.utils import INJECTED_MESSAGES_KEY, State

# In-process like executor sessions: the attempt and its graph run share one event loop.
_FEEDS: dict[str, list[AnyMessage]] = {}


def open_feed(run_id: str) -> None:
    """Start an empty feed for one comms attempt."""
    _FEEDS[run_id] = []


def feed(run_id: str, messages: Sequence[AnyMessage]) -> None:
    """Queue messages for the attempt's next model call."""
    _FEEDS[run_id].extend(messages)


def close_feed(run_id: str) -> None:
    """Drop the attempt's feed; anything still queued never reaches the model."""
    _FEEDS.pop(run_id, None)


async def drain_conversation_log_hook(
    state: State, config: RunnableConfig, store: BaseStore
) -> State:
    """Append the messages fed to this attempt since its last model call."""
    del store
    run_id = agent_configurable(config).get("comms_run")
    queued = _FEEDS.get(run_id) if run_id is not None else None
    if not queued:
        return state
    injected = list(queued)
    queued.clear()
    return cast(
        State,
        {
            **state,
            "messages": [*state.get("messages", []), *injected],
            INJECTED_MESSAGES_KEY: injected,
        },
    )
