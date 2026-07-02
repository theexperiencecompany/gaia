"""
Graph manager module to handle LangGraph initialization and hold multiple graph instances.

This module helps avoid circular imports between app.api.v1 and app.agents.agent.
"""

from typing import Any

from app.constants.log_tags import LogTag
from app.core.lazy_loader import providers
from shared.py.wide_events import log


class GraphUnavailableError(RuntimeError):
    """Raised when an agent graph cannot be retrieved from its lazy provider."""

    def __init__(self, graph_name: str, reason: str) -> None:
        super().__init__(
            f"Agent graph '{graph_name}' is unavailable: {reason}. See the "
            f"\"[STARTUP] Failed to initialize provider '{graph_name}'\" log "
            "for the root cause."
        )
        self.graph_name = graph_name


class GraphManager:
    @classmethod
    async def get_graph(cls, graph_name: str = "default_graph") -> Any:
        """Get the graph instance by name.

        Raises:
            GraphUnavailableError: if the provider is not registered, raised
                during initialization, or returned None.
        """
        log.info(f"{LogTag.AGENT} Attempting to get graph '{graph_name}'")
        try:
            graph = await providers.aget(graph_name)
        except KeyError as e:
            log.error(
                f"{LogTag.AGENT} Graph provider '{graph_name}' not registered in lazy providers: {e}"
            )
            raise GraphUnavailableError(graph_name, "its provider is not registered") from e
        except Exception as e:
            log.error(f"{LogTag.AGENT} Error retrieving graph '{graph_name}': {e}", exc_info=True)
            raise GraphUnavailableError(
                graph_name, f"its provider raised during initialization ({e})"
            ) from e
        if graph is None:
            log.error(
                f"{LogTag.AGENT} Graph '{graph_name}' returned None from lazy provider - this means the provider function failed or returned None"
            )
            raise GraphUnavailableError(
                graph_name, "its provider failed to initialize or returned None"
            )
        log.info(f"{LogTag.AGENT} Successfully retrieved graph '{graph_name}' from lazy provider")
        return graph
