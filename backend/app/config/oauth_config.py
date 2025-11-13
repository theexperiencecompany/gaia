"""
OAuth Integration Configuration

Single source of truth for all OAuth integration configurations in GAIA.
Defines integrations, scopes, display properties, and relationships.

OAuthScope: Defines OAuth permission scopes with URL and description.
Used for: Backend permission validation, frontend permission displays.

OAuthIntegration: Core integration definition with fields:
- id: Unique identifier for API endpoints, database records, frontend routing
- name: Human-readable name for frontend UI and user messages
- description: Detailed explanation for integration cards and settings pages
- icons: List of icon URLs for frontend UI components and different display sizes
- category: Groups integrations for frontend filtering, slash commands, settings organization
- provider: OAuth provider for flow routing, token management, API client selection
- scopes: Required permissions for OAuth authorization and validation
- available: Feature flag for frontend display logic and API availability
- oauth_endpoints: Custom OAuth URLs for non-standard providers
- is_special: Marks unified integrations for special frontend handling
- display_priority: Numeric sort order for frontend lists and dropdowns
- included_integrations: Child integration IDs for unified integrations
- short_name: Quick access identifier for slash commands and convenience functions

IntegrationConfigResponse: API model that converts backend fields to frontend camelCase.

Used by:
- google_scope_dependencies.py: Permission validation
- integration_checker.py: User permission checking
- oauth.py router: OAuth flows and status endpoints
- Frontend components: Integration cards, settings, slash commands
- Services: API client setup and token management

Integration types:
- Individual: Single service with own scopes (gmail, google_calendar)
- Unified: Multiple services with combined scopes (google_workspace)
- Coming soon: Placeholder with available=False (github, figma)
"""

from functools import cache
from typing import Dict, List, Optional

from app.models.oauth_models import (
    ComposioConfig,
    OAuthIntegration,
    OAuthScope,
    TriggerConfig,
)

# Define all integrations dynamically
OAUTH_INTEGRATIONS: List[OAuthIntegration] = [
    # Individual Google integrations
    OAuthIntegration(
        id="google_calendar",
        name="Google Calendar",
        description="Schedule meetings and manage your calendar events",
        category="productivity",
        provider="google",
        scopes=[
            OAuthScope(
                scope="https://www.googleapis.com/auth/calendar.events",
                description="Create and manage calendar events",
            ),
            OAuthScope(
                scope="https://www.googleapis.com/auth/calendar.readonly",
                description="View calendar events",
            ),
        ],
        short_name="calendar",
        managed_by="self",
    ),
    OAuthIntegration(
        id="google_docs",
        name="Google Docs",
        description="Create and edit documents in your workspace",
        category="productivity",
        provider="google",
        scopes=[
            OAuthScope(
                scope="https://www.googleapis.com/auth/documents",
                description="Create and edit documents",
            ),
        ],
        short_name="docs",
        managed_by="self",
    ),
    OAuthIntegration(
        id="gmail",
        name="Gmail",
        description="Manage emails, compose messages, and organize your inbox",
        category="communication",
        provider="gmail",
        scopes=[
            OAuthScope(
                scope="https://www.googleapis.com/auth/gmail.modify",
                description="Read, compose, and send emails",
            )
        ],
        short_name="gmail",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_svLPDmjcTVMX", toolkit="GMAIL"
        ),
        associated_triggers=[
            TriggerConfig(
                slug="GMAIL_NEW_GMAIL_MESSAGE",
                name="New Gmail Message",
                description="Triggered when a new Gmail message arrives",
                config={"labelIds": "INBOX", "user_id": "me", "interval": 1},
            )
        ],
    ),
    # Composio integrations
    OAuthIntegration(
        id="notion",
        name="Notion",
        description="Manage pages, databases, and workspace content",
        category="productivity",
        provider="notion",
        scopes=[],
        available=True,
        short_name="notion",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_DR3IWp9-Kezl", toolkit="NOTION"
        ),
    ),
    OAuthIntegration(
        id="twitter",
        name="Twitter",
        description="Post tweets, read timelines, and manage your account",
        category="social",
        provider="twitter",
        scopes=[],
        available=True,
        short_name="twitter",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_vloH3fnhIeUa", toolkit="TWITTER"
        ),
    ),
    OAuthIntegration(
        id="google_sheets",
        name="Google Sheets",
        description="Create, read, and update spreadsheets",
        category="productivity",
        provider="google_sheets",
        scopes=[],
        available=True,
        short_name="sheets",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_18I3fRfWyXDu", toolkit="GOOGLE_SHEETS"
        ),
    ),
    OAuthIntegration(
        id="linkedin",
        name="LinkedIn",
        description="Share posts and engage with your professional network",
        category="social",
        provider="linkedin",
        scopes=[],
        available=True,
        short_name="linkedin",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_GMeJBELf3z_m", toolkit="LINKEDIN"
        ),
    ),
    OAuthIntegration(
        id="github",
        name="GitHub",
        description="Manage repositories, issues, pull requests, and automate your development workflow",
        category="productivity",
        provider="github",
        scopes=[],
        available=True,
        short_name="github",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_y2VK4j0ATiZo", toolkit="GITHUB"
        ),
    ),
    OAuthIntegration(
        id="reddit",
        name="Reddit",
        description="Post content, manage comments, and engage with communities on Reddit",
        category="social",
        provider="reddit",
        scopes=[],
        available=True,
        short_name="reddit",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_7-hfiMVLhcDN", toolkit="REDDIT"
        ),
    ),
    OAuthIntegration(
        id="airtable",
        name="Airtable",
        description="Create and manage bases, tables, and records with AI-powered automation",
        category="productivity",
        provider="airtable",
        scopes=[],
        available=True,
        short_name="airtable",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_QPtQsXnIYm4C", toolkit="AIRTABLE"
        ),
    ),
    OAuthIntegration(
        id="linear",
        name="Linear",
        description="Manage issues, projects, and track development progress with AI assistance",
        category="productivity",
        provider="linear",
        scopes=[],
        available=True,
        short_name="linear",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_mnrcEhhTXPVS", toolkit="LINEAR"
        ),
    ),
    OAuthIntegration(
        id="slack",
        name="Slack",
        description="Send messages, manage channels, and automate team communication",
        category="communication",
        provider="slack",
        scopes=[],
        available=True,
        short_name="slack",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_acm0K6K_kWxY", toolkit="SLACK"
        ),
    ),
    OAuthIntegration(
        id="hubspot",
        name="HubSpot",
        description="Manage CRM contacts, deals, and automate sales and marketing workflows",
        category="productivity",
        provider="hubspot",
        scopes=[],
        available=True,
        short_name="hubspot",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_rcnwYp1PRCVr", toolkit="HUBSPOT"
        ),
    ),
    OAuthIntegration(
        id="google_tasks",
        name="Google Tasks",
        description="Create, manage, and organize your tasks and to-do lists",
        category="productivity",
        provider="google_tasks",
        scopes=[],
        available=True,
        short_name="tasks",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_xPSnVjKyHCDb", toolkit="GOOGLETASKS"
        ),
    ),
    OAuthIntegration(
        id="todoist",
        name="Todoist",
        description="Manage tasks, projects, and productivity workflows with advanced task management",
        category="productivity",
        provider="todoist",
        scopes=[],
        available=True,
        short_name="todoist",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_TOjltL3O2kEB", toolkit="TODOIST"
        ),
    ),
    # OAuthIntegration(
    #     id="microsoft_teams",
    #     name="Microsoft Teams",
    #     description="Collaborate with teams, send messages, manage channels, and automate team workflows",
    #     category="communication",
    #     provider="microsoft_teams",
    #     scopes=[],
    #     available=True,
    #     short_name="teams",
    #     managed_by="composio",
    #     composio_config=ComposioConfig(
    #         auth_config_id="ac_0kzvAbsi2xu3", toolkit="MICROSOFTTEAMS"
    #     ),
    # ),
    # OAuthIntegration(
    #     id="zoom",
    #     name="Zoom",
    #     description="Create and manage Zoom meetings, webinars, and video conferencing",
    #     category="communication",
    #     provider="zoom",
    #     scopes=[],
    #     available=True,
    #     short_name="zoom",
    #     managed_by="composio",
    #     composio_config=ComposioConfig(
    #         auth_config_id="ac_fABNBG17lf2A", toolkit="ZOOM"
    #     ),
    # ),
    OAuthIntegration(
        id="google_meet",
        name="Google Meet",
        description="Schedule and manage video meetings with Google Meet",
        category="communication",
        provider="google_meet",
        scopes=[],
        available=True,
        short_name="meet",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_GsHKAmsiGvz1", toolkit="GOOGLEMEET"
        ),
    ),
    OAuthIntegration(
        id="google_maps",
        name="Google Maps",
        description="Search locations, get directions, and manage place information",
        category="productivity",
        provider="google_maps",
        scopes=[],
        available=True,
        short_name="maps",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_vy6NqsFlzLuO", toolkit="GOOGLEMAPS"
        ),
    ),
    OAuthIntegration(
        id="asana",
        name="Asana",
        description="Manage projects, tasks, and team workflows with comprehensive project management",
        category="productivity",
        provider="asana",
        scopes=[],
        available=True,
        short_name="asana",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_gF2RuhulKw3I", toolkit="ASANA"
        ),
    ),
    OAuthIntegration(
        id="trello",
        name="Trello",
        description="Organize projects with boards, lists, and cards for visual task management",
        category="productivity",
        provider="trello",
        scopes=[],
        available=True,
        short_name="trello",
        managed_by="composio",
        composio_config=ComposioConfig(
            auth_config_id="ac_nMjBqOcjLTGW", toolkit="TRELLO"
        ),
    ),
]


@cache
def get_integration_by_id(integration_id: str) -> Optional[OAuthIntegration]:
    """Get an integration by its ID."""
    return next((i for i in OAUTH_INTEGRATIONS if i.id == integration_id), None)


@cache
def get_integration_scopes(integration_id: str) -> List[str]:
    """Get the OAuth scopes for a specific integration."""
    integration = get_integration_by_id(integration_id)
    if not integration:
        return []
    return [scope.scope for scope in integration.scopes]


@cache
def get_short_name_mapping() -> Dict[str, str]:
    """Get mapping of short names to integration IDs for convenience functions."""
    return {i.short_name: i.id for i in OAUTH_INTEGRATIONS if i.short_name}


@cache
def get_composio_social_configs() -> Dict[str, ComposioConfig]:
    """Generate COMPOSIO_SOCIAL_CONFIGS dynamically from integrations managed by Composio."""
    configs = {}
    for integration in OAUTH_INTEGRATIONS:
        if integration.managed_by == "composio" and integration.composio_config:
            configs[integration.provider] = integration.composio_config
    return configs


@cache
def get_integration_by_config(auth_config_id: str) -> Optional[OAuthIntegration]:
    """Get an integration by its Composio auth config ID."""
    return next(
        (
            i
            for i in OAUTH_INTEGRATIONS
            if i.composio_config and i.composio_config.auth_config_id == auth_config_id
        ),
        None,
    )
