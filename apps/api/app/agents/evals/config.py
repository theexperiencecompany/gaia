"""
Subagent Evaluation Configuration

Single source of truth for all subagent evaluation settings.
Add new subagents by extending SUBAGENT_CONFIGS list.
"""

from dataclasses import dataclass
from typing import Optional

from app.agents.prompts.subagent_prompts import (
    CALENDAR_AGENT_SYSTEM_PROMPT,
    GITHUB_AGENT_SYSTEM_PROMPT,
    GMAIL_AGENT_SYSTEM_PROMPT,
    LINKEDIN_AGENT_SYSTEM_PROMPT,
    NOTION_AGENT_SYSTEM_PROMPT,
    TWITTER_AGENT_SYSTEM_PROMPT,
)


@dataclass
class SubagentEvalConfig:
    """Configuration for evaluating a subagent."""

    id: str
    name: str
    agent_name: str
    integration_id: str
    dataset_name: str
    dataset_file: str
    prompt_name: str
    system_prompt: Optional[str] = None


SUBAGENT_CONFIGS: list[SubagentEvalConfig] = [
    SubagentEvalConfig(
        id="github",
        name="GitHub",
        agent_name="github_agent",
        integration_id="github",
        dataset_name="Github Capabilities",
        dataset_file="datasets/github.json",
        prompt_name="github_subagent_prompt",
        system_prompt=GITHUB_AGENT_SYSTEM_PROMPT,
    ),
    SubagentEvalConfig(
        id="gmail",
        name="Gmail",
        agent_name="gmail_agent",
        integration_id="gmail",
        dataset_name="Gmail Capabilities",
        dataset_file="datasets/gmail.json",
        prompt_name="gmail_subagent_prompt",
        system_prompt=GMAIL_AGENT_SYSTEM_PROMPT,
    ),
    SubagentEvalConfig(
        id="notion",
        name="Notion",
        agent_name="notion_agent",
        integration_id="notion",
        dataset_name="Notion Capabilities",
        dataset_file="datasets/notion.json",
        prompt_name="notion_subagent_prompt",
        system_prompt=NOTION_AGENT_SYSTEM_PROMPT,
    ),
    SubagentEvalConfig(
        id="calendar",
        name="Google Calendar",
        agent_name="google_calendar_agent",
        integration_id="googlecalendar",
        dataset_name="Google Calendar Capabilities",
        dataset_file="datasets/googlecalendar.json",
        prompt_name="calendar_subagent_prompt",
        system_prompt=CALENDAR_AGENT_SYSTEM_PROMPT,
    ),
    SubagentEvalConfig(
        id="twitter",
        name="Twitter",
        agent_name="twitter_agent",
        integration_id="twitter",
        dataset_name="Twitter Capabilities",
        dataset_file="datasets/twitter.json",
        prompt_name="twitter_subagent_prompt",
        system_prompt=TWITTER_AGENT_SYSTEM_PROMPT,
    ),
    SubagentEvalConfig(
        id="linkedin",
        name="LinkedIn",
        agent_name="linkedin_agent",
        integration_id="linkedin",
        dataset_name="LinkedIn Capabilities",
        dataset_file="datasets/linkedin.json",
        prompt_name="linkedin_subagent_prompt",
        system_prompt=LINKEDIN_AGENT_SYSTEM_PROMPT,
    ),
    SubagentEvalConfig(
        id="slack",
        name="Slack",
        agent_name="slack_agent",
        integration_id="slack",
        dataset_name="Slack Capabilities",
        dataset_file="datasets/slack.json",
        prompt_name="slack_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="reddit",
        name="Reddit",
        agent_name="reddit_agent",
        integration_id="reddit",
        dataset_name="Reddit Capabilities",
        dataset_file="datasets/reddit.json",
        prompt_name="reddit_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="trello",
        name="Trello",
        agent_name="trello_agent",
        integration_id="trello",
        dataset_name="Trello Capabilities",
        dataset_file="datasets/trello.json",
        prompt_name="trello_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="todoist",
        name="Todoist",
        agent_name="todoist_agent",
        integration_id="todoist",
        dataset_name="Todoist Capabilities",
        dataset_file="datasets/todoist.json",
        prompt_name="todoist_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="asana",
        name="Asana",
        agent_name="asana_agent",
        integration_id="asana",
        dataset_name="Asana Capabilities",
        dataset_file="datasets/asana.json",
        prompt_name="asana_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="linear",
        name="Linear",
        agent_name="linear_agent",
        integration_id="linear",
        dataset_name="Linear Capabilities",
        dataset_file="datasets/linear.json",
        prompt_name="linear_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="clickup",
        name="ClickUp",
        agent_name="clickup_agent",
        integration_id="clickup",
        dataset_name="ClickUp Capabilities",
        dataset_file="datasets/clickup.json",
        prompt_name="clickup_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="airtable",
        name="Airtable",
        agent_name="airtable_agent",
        integration_id="airtable",
        dataset_name="Airtable Capabilities",
        dataset_file="datasets/airtable.json",
        prompt_name="airtable_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="hubspot",
        name="HubSpot",
        agent_name="hubspot_agent",
        integration_id="hubspot",
        dataset_name="HubSpot Capabilities",
        dataset_file="datasets/hubspot.json",
        prompt_name="hubspot_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="google_sheets",
        name="Google Sheets",
        agent_name="google_sheets_agent",
        integration_id="googlesheets",
        dataset_name="Google Sheets Capabilities",
        dataset_file="datasets/google_sheets.json",
        prompt_name="google_sheets_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="google_meet",
        name="Google Meet",
        agent_name="google_meet_agent",
        integration_id="googlemeet",
        dataset_name="Google Meet Capabilities",
        dataset_file="datasets/googlemeet.json",
        prompt_name="google_meet_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="google_maps",
        name="Google Maps",
        agent_name="google_maps_agent",
        integration_id="google_maps",
        dataset_name="Google Maps Capabilities",
        dataset_file="datasets/google_maps.json",
        prompt_name="google_maps_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="google_tasks",
        name="Google Tasks",
        agent_name="google_tasks_agent",
        integration_id="googletasks",
        dataset_name="Google Tasks Capabilities",
        dataset_file="datasets/google_tasks.json",
        prompt_name="google_tasks_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="instagram",
        name="Instagram",
        agent_name="instagram_agent",
        integration_id="instagram",
        dataset_name="Instagram Capabilities",
        dataset_file="datasets/instagram.json",
        prompt_name="instagram_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="microsoft_teams",
        name="Microsoft Teams",
        agent_name="microsoft_teams_agent",
        integration_id="microsoft_teams",
        dataset_name="Microsoft Teams Capabilities",
        dataset_file="datasets/microsoft_teams.json",
        prompt_name="microsoft_teams_subagent_prompt",
    ),
    SubagentEvalConfig(
        id="zoom",
        name="Zoom",
        agent_name="zoom_agent",
        integration_id="zoom",
        dataset_name="Zoom Capabilities",
        dataset_file="datasets/zoom.json",
        prompt_name="zoom_subagent_prompt",
    ),
]


def get_config(subagent_id: str) -> Optional[SubagentEvalConfig]:
    """Get evaluation config for a subagent by ID."""
    for config in SUBAGENT_CONFIGS:
        if config.id == subagent_id:
            return config
    return None


def list_available_subagents() -> list[str]:
    """List all available subagent IDs for evaluation."""
    return [config.id for config in SUBAGENT_CONFIGS]
