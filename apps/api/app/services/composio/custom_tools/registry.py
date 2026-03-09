from typing import Callable, Dict, List

from app.agents.tools.integrations.calendar_tool import (
    register_calendar_custom_tools,
)
from app.agents.tools.integrations.google_docs_tool import (
    register_google_docs_custom_tools,
)
from app.agents.tools.integrations.google_maps_tool import (
    register_google_maps_custom_tools,
)
from app.agents.tools.integrations.google_meet_tool import (
    register_google_meet_custom_tools,
)
from app.agents.tools.integrations.google_sheets_tool import (
    register_google_sheets_custom_tools,
)
from app.agents.tools.integrations.google_tasks_tool import (
    register_google_tasks_custom_tools,
)
from app.agents.tools.integrations.instagram_tool import (
    register_instagram_custom_tools,
)
from app.agents.tools.integrations.linear_tool import (
    register_linear_custom_tools,
)
from app.agents.tools.integrations.linkedin_tool import (
    register_linkedin_custom_tools,
)
from app.agents.tools.integrations.notion_tool import (
    register_notion_custom_tools,
)
from app.agents.tools.integrations.reddit_tool import (
    register_reddit_custom_tools,
)
from app.agents.tools.integrations.twitter_tool import (
    register_twitter_custom_tools,
)
from app.agents.tools.integrations.slack_tool import (
    register_slack_custom_tools,
)
from app.agents.tools.integrations.github_tool import (
    register_github_custom_tools,
)
from app.agents.tools.integrations.hubspot_tool import (
    register_hubspot_custom_tools,
)
from app.agents.tools.integrations.airtable_tool import (
    register_airtable_custom_tools,
)
from app.agents.tools.integrations.asana_tool import (
    register_asana_custom_tools,
)
from app.agents.tools.integrations.clickup_tool import (
    register_clickup_custom_tools,
)
from app.agents.tools.integrations.trello_tool import (
    register_trello_custom_tools,
)
from app.agents.tools.integrations.todoist_tool import (
    register_todoist_custom_tools,
)
from app.agents.tools.integrations.microsoft_teams_tool import (
    register_microsoft_teams_custom_tools,
)
from app.agents.tools.integrations.urgency_tool import (
    register_urgency_custom_tools,
)
from shared.py.wide_events import log
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
        self._register_toolkit("google_maps", register_google_maps_custom_tools)
        self._register_toolkit("googlemeet", register_google_meet_custom_tools)
        self._register_toolkit("googlesheets", register_google_sheets_custom_tools)
        self._register_toolkit("googletasks", register_google_tasks_custom_tools)
        self._register_toolkit("instagram", register_instagram_custom_tools)
        self._register_toolkit("notion", register_notion_custom_tools)
        self._register_toolkit("linkedin", register_linkedin_custom_tools)
        self._register_toolkit("twitter", register_twitter_custom_tools)
        self._register_toolkit("linear", register_linear_custom_tools)
        self._register_toolkit("reddit", register_reddit_custom_tools)
        self._register_toolkit("slack", register_slack_custom_tools)
        self._register_toolkit("github", register_github_custom_tools)
        self._register_toolkit("hubspot", register_hubspot_custom_tools)
        self._register_toolkit("airtable", register_airtable_custom_tools)
        self._register_toolkit("asana", register_asana_custom_tools)
        self._register_toolkit("clickup", register_clickup_custom_tools)
        self._register_toolkit("trello", register_trello_custom_tools)
        self._register_toolkit("todoist", register_todoist_custom_tools)
        self._register_toolkit("microsoft_teams", register_microsoft_teams_custom_tools)
        self._register_toolkit("gaia", register_urgency_custom_tools)

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

        log.set(
            custom_tools_toolkit=toolkit,
            custom_tools_registered_count=len(tool_names),
            custom_tools_names=tool_names,
        )
        log.info(f"Registered {len(tool_names)} custom tools for {toolkit} toolkit")

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
