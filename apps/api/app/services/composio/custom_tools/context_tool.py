"""Provider registry and namespace helpers for context gathering.

Maps provider keys to their Composio CUSTOM_GATHER_CONTEXT tool slugs.
"""

from typing import Dict

# Flat registry: provider key → Composio tool slug
PROVIDER_TOOLS: Dict[str, str] = {
    "calendar": "GOOGLECALENDAR_CUSTOM_GATHER_CONTEXT",
    "gmail": "GMAIL_CUSTOM_GATHER_CONTEXT",
    "slack": "SLACK_CUSTOM_GATHER_CONTEXT",
    "notion": "NOTION_CUSTOM_GATHER_CONTEXT",
    "github": "GITHUB_CUSTOM_GATHER_CONTEXT",
    "linear": "LINEAR_CUSTOM_GATHER_CONTEXT",
    "google_tasks": "GOOGLETASKS_CUSTOM_GATHER_CONTEXT",
    "todoist": "TODOIST_CUSTOM_GATHER_CONTEXT",
    "asana": "ASANA_CUSTOM_GATHER_CONTEXT",
    "trello": "TRELLO_CUSTOM_GATHER_CONTEXT",
    "clickup": "CLICKUP_CUSTOM_GATHER_CONTEXT",
    "hubspot": "HUBSPOT_CUSTOM_GATHER_CONTEXT",
    "teams": "MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT",
    "google_docs": "GOOGLEDOCS_CUSTOM_GATHER_CONTEXT",
    "google_sheets": "GOOGLESHEETS_CUSTOM_GATHER_CONTEXT",
    "airtable": "AIRTABLE_CUSTOM_GATHER_CONTEXT",
    "google_maps": "GOOGLE_MAPS_CUSTOM_GATHER_CONTEXT",
    "google_meet": "GOOGLEMEET_CUSTOM_GATHER_CONTEXT",
    "instagram": "INSTAGRAM_CUSTOM_GATHER_CONTEXT",
    "linkedin": "LINKEDIN_CUSTOM_GATHER_CONTEXT",
    "reddit": "REDDIT_CUSTOM_GATHER_CONTEXT",
    "twitter": "TWITTER_CUSTOM_GATHER_CONTEXT",
}


def tool_namespace(tool_slug: str) -> str:
    """Derive Composio namespace from tool slug.

    E.g.: "GOOGLECALENDAR_CUSTOM_GATHER_CONTEXT" -> "googlecalendar"
          "MICROSOFT_TEAMS_CUSTOM_GATHER_CONTEXT" -> "microsoft_teams"
    """
    return tool_slug.removesuffix("_CUSTOM_GATHER_CONTEXT").lower()
