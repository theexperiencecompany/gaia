from typing import Callable, Dict, List

from app.agents.tools.calendar_tool import (
    register_calendar_custom_tools,
)
from app.agents.tools.google_docs_tool import (
    register_google_docs_custom_tools,
)
from app.agents.tools.google_sheets_tool import (
    register_google_sheets_custom_tools,
)
from app.agents.tools.linear_tool import (
    register_linear_custom_tools,
)
from app.agents.tools.linkedin_tool import (
    register_linkedin_custom_tools,
)
from app.agents.tools.notion_tool import (
    register_notion_custom_tools,
)
from app.agents.tools.twitter_tool import (
    register_twitter_custom_tools,
)
from app.config.loggers import app_logger as logger
from app.services.composio.custom_tools.gmail_tools import (
    register_gmail_custom_tools,
)
from composio import Composio


class CustomToolsRegistry:
    """
    Registry for managing custom Composio tools across toolkits.

    Usage:
        # In ComposioService.__init__:
        custom_tools_registry.initialize(composio)

        # When getting tools:
        custom_tool_names = custom_tools_registry.get_tool_names("gmail")
    """

    def __init__(self) -> None:
        self._composio: Composio | None = None
        self._tools_by_toolkit: Dict[str, List[str]] = {}
        self._registered_toolkits: set = set()

    def initialize(self, composio: Composio) -> None:
        """
        Initialize the registry with Composio client and register all custom tools.

        Args:
            composio: The Composio client instance
        """
        self._composio = composio

        self._register_all_tools()

    def _register_all_tools(self) -> None:
        """Register all custom tools for all toolkits."""
        if self._composio is None:
            raise RuntimeError("Registry not initialized. Call initialize() first.")

        self._register_toolkit("gmail", register_gmail_custom_tools)
        self._register_toolkit("googlecalendar", register_calendar_custom_tools)
        self._register_toolkit("googledocs", register_google_docs_custom_tools)
        self._register_toolkit("googlesheets", register_google_sheets_custom_tools)
        self._register_toolkit("notion", register_notion_custom_tools)
        self._register_toolkit("linkedin", register_linkedin_custom_tools)
        self._register_toolkit("twitter", register_twitter_custom_tools)
        self._register_toolkit("linear", register_linear_custom_tools)

    def _register_toolkit(
        self,
        toolkit: str,
        register_func: Callable[["Composio"], List[str]],
    ) -> None:
        """
        Register custom tools for a specific toolkit.

        Args:
            toolkit: The toolkit name (e.g., 'gmail')
            register_func: Function that registers tools and returns their names
        """
        if self._composio is None:
            raise RuntimeError("Registry not initialized. Call initialize() first.")

        if toolkit in self._registered_toolkits:
            return

        tool_names = register_func(self._composio)
        self._tools_by_toolkit[toolkit.lower()] = tool_names
        self._registered_toolkits.add(toolkit)

        logger.info(f"Registered {len(tool_names)} custom tools for {toolkit} toolkit")

    def get_tool_names(self, toolkit: str) -> List[str]:
        """
        Get list of custom tool names for a specific toolkit.

        Args:
            toolkit: The toolkit name (e.g., 'gmail', 'slack')

        Returns:
            List of custom tool names, or empty list if none exist
        """
        return self._tools_by_toolkit.get(toolkit.lower(), [])

    def get_all_tool_names(self) -> List[str]:
        """Get all registered custom tool names across all toolkits."""
        all_tools = []
        for tools in self._tools_by_toolkit.values():
            all_tools.extend(tools)
        return all_tools

    def get_registered_toolkits(self) -> List[str]:
        """Get list of toolkits that have custom tools registered."""
        return list(self._registered_toolkits)

    @property
    def is_initialized(self) -> bool:
        """Check if the registry has been initialized."""
        return self._composio is not None


custom_tools_registry = CustomToolsRegistry()
