"""
Graph manager module to handle LangGraph initialization and hold multiple graph instances.

This module helps avoid circular imports between app.api.v1 and app.agents.agent.
"""

from typing import Any

from shared.py.wide_events import log
from app.core.lazy_loader import providers


class GraphManager:
    @classmethod
    def set_graph(cls, graph_instance: Any, graph_name: str = "default_graph"):
        """Set a graph instance with the given name."""
        providers.register(graph_name, loader_func=lambda: graph_instance)

    @classmethod
    async def get_graph(cls, graph_name: str = "default_graph") -> Any:
        """Get the graph instance by name."""
        log.info(f"Attempting to get graph '{graph_name}'")
        try:
            graph = await providers.aget(graph_name)
            if graph is not None:
                log.info(
                    f"Successfully retrieved graph '{graph_name}' from lazy provider"
                )
                return graph
            else:
                log.error(
                    f"Graph '{graph_name}' returned None from lazy provider - this means the provider function failed or returned None"
                )
                return None
        except KeyError as e:
            log.error(
                f"Graph provider '{graph_name}' not registered in lazy providers: {e}"
            )
            return None
        except Exception as e:
            log.error(f"Error retrieving graph '{graph_name}': {e}", exc_info=True)
            return None
