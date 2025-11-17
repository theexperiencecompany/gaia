#!/usr/bin/env python3
# ruff: noqa: S108
# mypy: ignore-errors
"""
Script to generate realistic workflows for user testing and visualization.

This script creates:
- Personal workflows (explore workflows)
- Community workflows (public marketplace)
- Proper tool and integration usage
- Realistic execution counts
- Various categories and triggers

Usage:
    # Generate workflows
    python scripts/generate_workflows.py --generate --user-id 6887aac50ab42839de0edfe1

    # Delete workflows
    python scripts/generate_workflows.py --delete --user-id 6887aac50ab42839de0edfe1

    # Both (delete then generate)
    python scripts/generate_workflows.py --both --user-id 6887aac50ab42839de0edfe1
"""

import argparse
import asyncio

# Add the backend directory to Python path
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from motor.motor_asyncio import AsyncIOMotorClient

# MongoDB connection
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = "GAIA"  # Use uppercase to match existing database

# Available tool categories with their representative tools
TOOL_CATEGORIES = {
    "search": {
        "tools": ["web_search_tool", "fetch_webpages"],
        "integration": None,
    },
    "documents": {
        "tools": ["query_file", "generate_document"],
        "integration": None,
    },
    "notifications": {
        "tools": ["send_notification", "schedule_notification"],
        "integration": None,
    },
    "productivity": {
        "tools": [
            "create_todo",
            "update_todo",
            "list_todos",
            "create_reminder",
            "list_reminders",
        ],
        "integration": None,
    },
    "goal_tracking": {
        "tools": ["create_goal", "update_goal", "list_goals", "track_progress"],
        "integration": None,
    },
    "memory": {
        "tools": ["store_memory", "recall_memory", "search_memories"],
        "integration": None,
    },
    "development": {
        "tools": ["execute_code", "create_flowchart"],
        "integration": None,
    },
    "creative": {
        "tools": ["generate_image"],
        "integration": None,
    },
    "weather": {
        "tools": ["get_weather"],
        "integration": None,
    },
    "google_calendar": {
        "tools": [
            "GOOGLECALENDAR_CREATE_EVENT",
            "GOOGLECALENDAR_LIST_EVENTS",
            "GOOGLECALENDAR_UPDATE_EVENT",
            "GOOGLECALENDAR_DELETE_EVENT",
        ],
        "integration": "google_calendar",
    },
    "google_docs": {
        "tools": [
            "GOOGLEDOCS_CREATE_DOCUMENT",
            "GOOGLEDOCS_UPDATE_DOCUMENT",
            "GOOGLEDOCS_GET_DOCUMENT",
        ],
        "integration": "google_docs",
    },
    "GMAIL": {
        "tools": [
            "GMAIL_SEND_EMAIL",
            "GMAIL_SEARCH_EMAILS",
            "GMAIL_GET_EMAIL",
            "GMAIL_CREATE_DRAFT",
            "GMAIL_REPLY_TO_EMAIL",
        ],
        "integration": "GMAIL",
    },
    "NOTION": {
        "tools": [
            "NOTION_CREATE_PAGE",
            "NOTION_UPDATE_PAGE",
            "NOTION_SEARCH_NOTION_PAGE",
            "NOTION_CREATE_DATABASE",
            "NOTION_QUERY_DATABASE",
        ],
        "integration": "NOTION",
    },
    "TWITTER": {
        "tools": [
            "TWITTER_CREATION_OF_A_POST",
            "TWITTER_GET_USER_MENTIONS",
            "TWITTER_SEARCH_RECENT_TWEETS",
        ],
        "integration": "TWITTER",
    },
    "LINKEDIN": {
        "tools": ["LINKEDIN_CREATE_POST", "LINKEDIN_GET_PROFILE"],
        "integration": "LINKEDIN",
    },
    "GITHUB": {
        "tools": [
            "GITHUB_CREATE_ISSUE",
            "GITHUB_LIST_ISSUES",
            "GITHUB_CREATE_PR",
            "GITHUB_GET_REPO_INFO",
        ],
        "integration": "GITHUB",
    },
    "SLACK": {
        "tools": [
            "SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL",
            "SLACK_GET_MESSAGES_FROM_A_CHANNEL",
        ],
        "integration": "SLACK",
    },
    "GOOGLESHEETS": {
        "tools": [
            "GOOGLESHEETS_BATCH_UPDATE_VALUES",
            "GOOGLESHEETS_CREATE_SPREADSHEET",
            "GOOGLESHEETS_GET_SPREADSHEET_DATA",
        ],
        "integration": "GOOGLESHEETS",
    },
    "LINEAR": {
        "tools": ["LINEAR_CREATE_ISSUE", "LINEAR_UPDATE_ISSUE", "LINEAR_LIST_ISSUES"],
        "integration": "LINEAR",
    },
    "HUBSPOT": {
        "tools": [
            "HUBSPOT_CREATE_CONTACT",
            "HUBSPOT_CREATE_DEAL",
            "HUBSPOT_GET_CONTACT",
        ],
        "integration": "HUBSPOT",
    },
    "ASANA": {
        "tools": ["ASANA_CREATE_TASK", "ASANA_UPDATE_TASK", "ASANA_GET_TASKS"],
        "integration": "ASANA",
    },
    "TRELLO": {
        "tools": [
            "TRELLO_CREATE_A_NEW_CARD",
            "TRELLO_UPDATE_CARD",
            "TRELLO_GET_BOARDS",
        ],
        "integration": "TRELLO",
    },
}

# Workflow templates with realistic scenarios
WORKFLOW_TEMPLATES = [
    # Productivity & Task Management
    {
        "title": "Daily Morning Routine Automation",
        "description": "Start your day right by checking weather, reviewing calendar events, and getting your top priorities for the day",
        "categories": ["weather", "google_calendar", "productivity"],
        "use_case_categories": ["Knowledge Workers", "featured"],
        "trigger_type": "schedule",
        "cron": "0 7 * * *",  # 7 AM daily
    },
    {
        "title": "Weekly Team Standup Digest",
        "description": "Compile a weekly summary of team progress, pending tasks, and send it via Slack every Monday morning",
        "categories": ["productivity", "SLACK", "goal_tracking"],
        "use_case_categories": ["Business & Ops", "Engineering", "featured"],
        "trigger_type": "schedule",
        "cron": "0 9 * * 1",  # 9 AM Monday
    },
    {
        "title": "Email Newsletter Compilation",
        "description": "Search for important emails, extract key information, and compile into a weekly newsletter document",
        "categories": ["GMAIL", "documents", "google_docs"],
        "use_case_categories": ["Marketing", "Business & Ops"],
        "trigger_type": "schedule",
        "cron": "0 18 * * 5",  # 6 PM Friday
    },
    # Content Creation & Social Media
    {
        "title": "Social Media Content Scheduler",
        "description": "Create and schedule engaging posts across Twitter and LinkedIn with relevant hashtags and optimal timing",
        "categories": ["creative", "TWITTER", "LINKEDIN"],
        "use_case_categories": ["Marketing", "Founders", "featured"],
        "trigger_type": "schedule",
        "cron": "0 10 * * *",  # 10 AM daily
    },
    {
        "title": "Blog Post to Social Media",
        "description": "Take a new blog post URL, summarize it, create engaging social media posts, and share on multiple platforms",
        "categories": ["search", "creative", "TWITTER", "LINKEDIN"],
        "use_case_categories": ["Marketing", "Founders"],
        "trigger_type": "manual",
    },
    {
        "title": "Weekly Content Performance Report",
        "description": "Analyze social media engagement, create performance visualizations, and send report to Slack",
        "categories": ["TWITTER", "LINKEDIN", "documents", "SLACK"],
        "use_case_categories": ["Marketing", "Business & Ops"],
        "trigger_type": "schedule",
        "cron": "0 9 * * 1",  # 9 AM Monday
    },
    # Development & GitHub
    {
        "title": "Daily Code Review Digest",
        "description": "Fetch pending pull requests, summarize changes, and send notifications to team members",
        "categories": ["GITHUB", "notifications", "SLACK"],
        "use_case_categories": ["Engineering", "featured"],
        "trigger_type": "schedule",
        "cron": "0 9 * * 1-5",  # 9 AM weekdays
    },
    {
        "title": "Bug Report to Linear Issue",
        "description": "Convert GitHub issues labeled as 'bug' into Linear tasks with proper priority and assignment",
        "categories": ["GITHUB", "LINEAR"],
        "use_case_categories": ["Engineering"],
        "trigger_type": "schedule",
        "cron": "0 */3 * * *",  # Every 3 hours
    },
    {
        "title": "Sprint Planning Assistant",
        "description": "Gather open issues, analyze priorities, create sprint board, and schedule planning meeting",
        "categories": ["GITHUB", "LINEAR", "google_calendar", "SLACK"],
        "use_case_categories": ["Engineering", "Business & Ops"],
        "trigger_type": "manual",
    },
    # CRM & Sales
    {
        "title": "New Lead Follow-up Automation",
        "description": "When new contact is added to HubSpot, send personalized welcome email and create follow-up tasks",
        "categories": ["HUBSPOT", "GMAIL", "productivity"],
        "use_case_categories": ["Founders", "Business & Ops", "featured"],
        "trigger_type": "manual",
    },
    {
        "title": "Weekly Sales Pipeline Report",
        "description": "Generate comprehensive sales report from HubSpot, create visualizations, and share with team",
        "categories": ["HUBSPOT", "documents", "google_docs", "SLACK"],
        "use_case_categories": ["Founders", "Business & Ops"],
        "trigger_type": "schedule",
        "cron": "0 9 * * 1",  # 9 AM Monday
    },
    {
        "title": "Deal Closure Celebration",
        "description": "When deal is marked as closed-won, send congratulations to Slack, update spreadsheet, and schedule celebration",
        "categories": ["HUBSPOT", "SLACK", "GOOGLESHEETS", "google_calendar"],
        "use_case_categories": ["Founders", "Business & Ops"],
        "trigger_type": "manual",
    },
    # Documentation & Knowledge Management
    {
        "title": "Meeting Notes to Notion",
        "description": "Extract action items from meeting transcripts, create structured Notion pages, and assign tasks",
        "categories": ["documents", "NOTION", "productivity"],
        "use_case_categories": ["Knowledge Workers", "Business & Ops"],
        "trigger_type": "manual",
    },
    {
        "title": "Documentation Update Reminder",
        "description": "Check for outdated documentation, send reminders to owners, and track update progress",
        "categories": ["NOTION", "GITHUB", "SLACK", "productivity"],
        "use_case_categories": ["Engineering", "Knowledge Workers"],
        "trigger_type": "schedule",
        "cron": "0 10 * * 3",  # 10 AM Wednesday
    },
    {
        "title": "Knowledge Base Article Generator",
        "description": "Search for common questions in Slack, compile answers, and create comprehensive Notion articles",
        "categories": ["SLACK", "search", "NOTION", "creative"],
        "use_case_categories": ["Knowledge Workers", "Business & Ops"],
        "trigger_type": "manual",
    },
    # Personal Productivity
    {
        "title": "Weekly Goal Review and Planning",
        "description": "Review completed goals, analyze progress, set new goals for the week, and send motivational summary",
        "categories": ["goal_tracking", "memory", "notifications"],
        "use_case_categories": ["Knowledge Workers", "Students", "featured"],
        "trigger_type": "schedule",
        "cron": "0 9 * * 0",  # 9 AM Sunday
    },
    {
        "title": "Focus Time Scheduler",
        "description": "Block calendar for deep work, mute notifications, create focused task list, and log work session",
        "categories": ["google_calendar", "productivity", "memory"],
        "use_case_categories": ["Knowledge Workers", "Students"],
        "trigger_type": "manual",
    },
    {
        "title": "Evening Wind-down Routine",
        "description": "Review completed tasks, update tomorrow's priorities, send summary email, and set reminders",
        "categories": ["productivity", "GMAIL", "notifications", "memory"],
        "use_case_categories": ["Knowledge Workers"],
        "trigger_type": "schedule",
        "cron": "0 18 * * 1-5",  # 6 PM weekdays
    },
    # Data & Analytics
    {
        "title": "Weekly Metrics Dashboard",
        "description": "Compile data from multiple sources, create comprehensive spreadsheet, generate charts, and share insights",
        "categories": ["GOOGLESHEETS", "documents", "creative", "SLACK"],
        "use_case_categories": ["Business & Ops", "Founders"],
        "trigger_type": "schedule",
        "cron": "0 9 * * 1",  # 9 AM Monday
    },
    {
        "title": "Expense Tracking Automation",
        "description": "Parse expense emails, categorize spending, update tracking spreadsheet, and generate monthly reports",
        "categories": ["GMAIL", "GOOGLESHEETS", "documents"],
        "use_case_categories": ["Business & Ops", "Founders"],
        "trigger_type": "schedule",
        "cron": "0 9 1 * *",  # 9 AM first of month
    },
    # Project Management
    {
        "title": "Sprint Retrospective Facilitator",
        "description": "Collect feedback from team, organize insights, create Trello board for action items, schedule follow-up",
        "categories": ["SLACK", "TRELLO", "documents", "google_calendar"],
        "use_case_categories": ["Engineering", "Business & Ops"],
        "trigger_type": "manual",
    },
    {
        "title": "Project Status Update Generator",
        "description": "Gather progress from Asana, Linear, and GitHub, compile status report, and send to stakeholders",
        "categories": ["ASANA", "LINEAR", "GITHUB", "documents", "GMAIL"],
        "use_case_categories": ["Business & Ops", "Engineering"],
        "trigger_type": "schedule",
        "cron": "0 16 * * 5",  # 4 PM Friday
    },
    {
        "title": "Deadline Reminder System",
        "description": "Check upcoming deadlines across all project management tools, send reminders, and update priorities",
        "categories": ["ASANA", "TRELLO", "LINEAR", "notifications", "productivity"],
        "use_case_categories": ["Business & Ops", "Engineering"],
        "trigger_type": "schedule",
        "cron": "0 9 * * *",  # 9 AM daily
    },
    # Research & Learning
    {
        "title": "Daily Tech News Digest",
        "description": "Search for trending tech news, filter by interests, summarize articles, and send personalized digest",
        "categories": ["search", "documents", "notifications"],
        "use_case_categories": ["Students", "Engineering", "Knowledge Workers"],
        "trigger_type": "schedule",
        "cron": "0 8 * * *",  # 8 AM daily
    },
    {
        "title": "Research Paper Summarizer",
        "description": "Fetch research papers on specific topics, generate summaries, store in Notion with key insights",
        "categories": ["search", "documents", "NOTION", "memory"],
        "use_case_categories": ["Students", "Knowledge Workers"],
        "trigger_type": "manual",
    },
    {
        "title": "Learning Progress Tracker",
        "description": "Track completed courses, update learning goals, celebrate milestones, and plan next steps",
        "categories": ["goal_tracking", "memory", "notifications", "documents"],
        "use_case_categories": ["Students", "Knowledge Workers"],
        "trigger_type": "manual",
    },
    # Communication & Collaboration
    {
        "title": "Team Announcement Broadcaster",
        "description": "Take an announcement, format for different platforms, post to Slack, email, and team channels",
        "categories": ["SLACK", "GMAIL", "documents"],
        "use_case_categories": ["Business & Ops", "Marketing"],
        "trigger_type": "manual",
    },
    {
        "title": "Meeting Follow-up Automation",
        "description": "After calendar event ends, send thank you emails, share notes, create action items, and schedule follow-ups",
        "categories": ["google_calendar", "GMAIL", "productivity", "documents"],
        "use_case_categories": ["Business & Ops", "Knowledge Workers", "featured"],
        "trigger_type": "schedule",
        "cron": "0 * * * *",  # Every hour
    },
    {
        "title": "Onboarding Workflow for New Team Members",
        "description": "Create onboarding checklist, send welcome email, schedule introduction calls, add to relevant channels",
        "categories": [
            "productivity",
            "GMAIL",
            "google_calendar",
            "SLACK",
            "documents",
        ],
        "use_case_categories": ["Business & Ops"],
        "trigger_type": "manual",
    },
    # Creative & Content
    {
        "title": "Image Gallery Creator",
        "description": "Generate themed images based on prompts, organize in folders, create gallery document with descriptions",
        "categories": ["creative", "documents", "google_docs"],
        "use_case_categories": ["Marketing", "Founders"],
        "trigger_type": "manual",
    },
    {
        "title": "Video Script Generator",
        "description": "Research topic, generate script outline, create detailed scenes, format for production, save to Notion",
        "categories": ["search", "creative", "documents", "NOTION"],
        "use_case_categories": ["Marketing", "Founders"],
        "trigger_type": "manual",
    },
    # Health & Wellness
    {
        "title": "Daily Wellness Check-in",
        "description": "Send wellness prompts, collect responses, track patterns, provide insights and encouragement",
        "categories": ["notifications", "memory", "goal_tracking"],
        "use_case_categories": ["Knowledge Workers"],
        "trigger_type": "schedule",
        "cron": "0 20 * * *",  # 8 PM daily
    },
    {
        "title": "Exercise Routine Planner",
        "description": "Plan weekly exercise schedule, add to calendar, set reminders, track completion and progress",
        "categories": ["google_calendar", "notifications", "goal_tracking", "memory"],
        "use_case_categories": ["Knowledge Workers"],
        "trigger_type": "schedule",
        "cron": "0 9 * * 0",  # 9 AM Sunday
    },
]


def generate_workflow_id() -> str:
    """Generate a workflow ID."""
    return f"wf_{uuid.uuid4().hex[:12]}"


def generate_step_id(step_num: int) -> str:
    """Generate a step ID."""
    return f"step_{step_num}"


def create_workflow_steps(
    categories: List[str], num_steps: Optional[int] = None
) -> List[Dict[str, Any]]:
    """Create realistic workflow steps based on categories."""
    if num_steps is None:
        num_steps = random.randint(3, 6)

    steps = []
    available_tools = []

    # Collect all tools from selected categories
    for category in categories:
        if category in TOOL_CATEGORIES:
            available_tools.extend(
                [(tool, category) for tool in TOOL_CATEGORIES[category]["tools"]]
            )

    # If not enough tools, use what we have
    num_steps = min(num_steps, len(available_tools))

    # Select random tools
    selected_tools = random.sample(available_tools, num_steps)

    # Step templates for more realistic descriptions
    step_templates = {
        "search": [
            (
                "Research and gather information",
                "Search the web for relevant information about {topic}",
            ),
            ("Fetch webpage content", "Extract and analyze content from {url}"),
            ("Find resources", "Locate and compile relevant resources and references"),
        ],
        "documents": [
            ("Create document", "Generate a comprehensive document with {content}"),
            ("Query files", "Search through files to find relevant information"),
            ("Generate report", "Compile findings into a structured report"),
        ],
        "GMAIL": [
            ("Send email", "Compose and send email to {recipients} about {subject}"),
            ("Search emails", "Find emails matching criteria: {query}"),
            ("Create draft", "Prepare email draft for review before sending"),
            ("Reply to email", "Send thoughtful reply to {sender}"),
        ],
        "google_calendar": [
            ("Create event", "Schedule {event_type} event on {date}"),
            ("List events", "Retrieve upcoming events for {timeframe}"),
            ("Update event", "Modify event details and notify attendees"),
            ("Check availability", "Find optimal meeting time for all participants"),
        ],
        "SLACK": [
            ("Send message", "Post update to {channel} channel"),
            ("Get messages", "Retrieve recent messages from {channel}"),
            ("Notify team", "Send notification to relevant team members"),
        ],
        "NOTION": [
            ("Create page", "Create new Notion page with {content}"),
            ("Update page", "Modify existing Notion page with new information"),
            ("Search pages", "Find Notion pages matching {criteria}"),
            ("Query database", "Retrieve entries from {database} based on filters"),
        ],
        "productivity": [
            ("Create task", "Add new task: {task_name} with priority {priority}"),
            ("Update task", "Mark task as completed and update progress"),
            ("List tasks", "Retrieve all pending tasks for {timeframe}"),
            ("Set reminder", "Create reminder for {task} at {time}"),
        ],
        "goal_tracking": [
            ("Track progress", "Update progress on goal: {goal_name}"),
            ("Create goal", "Set new goal with measurable targets"),
            ("Review goals", "Analyze progress and adjust timelines"),
        ],
        "creative": [
            ("Generate image", "Create image based on prompt: {prompt}"),
            ("Design visual", "Generate visual asset for {purpose}"),
        ],
        "memory": [
            ("Store information", "Save important information for future reference"),
            ("Recall memory", "Retrieve previously stored information about {topic}"),
            ("Search memories", "Find relevant memories matching {query}"),
        ],
        "notifications": [
            ("Send notification", "Send notification about {event}"),
            ("Schedule notification", "Plan future notification for {time}"),
        ],
        "GITHUB": [
            ("Create issue", "Open new issue in {repo} with details"),
            ("List issues", "Fetch open issues from {repo}"),
            ("Create PR", "Submit pull request with changes"),
        ],
        "TWITTER": [
            ("Create post", "Compose and publish tweet about {topic}"),
            ("Search tweets", "Find tweets matching {query}"),
            ("Get mentions", "Retrieve recent mentions and interactions"),
        ],
        "LINKEDIN": [
            ("Create post", "Publish professional post about {topic}"),
            ("Get profile", "Retrieve profile information for {user}"),
        ],
        "HUBSPOT": [
            ("Create contact", "Add new contact with details"),
            ("Create deal", "Set up new deal in pipeline"),
            ("Get contact", "Retrieve contact information"),
        ],
        "LINEAR": [
            ("Create issue", "Create new issue with {title}"),
            ("Update issue", "Modify issue status and details"),
            ("List issues", "Get all issues for {project}"),
        ],
        "GOOGLESHEETS": [
            ("Update spreadsheet", "Add data to {spreadsheet}"),
            ("Create spreadsheet", "Generate new spreadsheet with {data}"),
            ("Get data", "Retrieve data from {spreadsheet}"),
        ],
        "google_docs": [
            ("Create document", "Generate Google Doc with {content}"),
            ("Update document", "Modify existing document with new sections"),
            ("Get document", "Retrieve document content from {doc_id}"),
        ],
        "weather": [
            ("Get weather", "Fetch current weather for {location}"),
        ],
        "development": [
            ("Execute code", "Run code snippet to {purpose}"),
            ("Create flowchart", "Generate flowchart diagram for {process}"),
        ],
        "ASANA": [
            ("Create task", "Add task to {project}"),
            ("Update task", "Modify task details and assignment"),
            ("Get tasks", "Retrieve tasks from {project}"),
        ],
        "TRELLO": [
            ("Create card", "Add new card to {board}"),
            ("Update card", "Move card and update details"),
            ("Get boards", "List all available boards"),
        ],
    }

    for i, (tool_name, category) in enumerate(selected_tools):
        templates = step_templates.get(
            category, [("Perform action", "Execute {tool} to complete step")]
        )
        template = random.choice(templates)

        steps.append(
            {
                "id": generate_step_id(i),
                "title": template[0],
                "tool_name": tool_name,
                "tool_category": category,
                "description": template[1],
                "tool_inputs": {},
                "order": i,
                "executed_at": None,
                "result": None,
            }
        )

    return steps


def create_trigger_config(
    trigger_type: str, cron: Optional[str] = None
) -> Dict[str, Any]:
    """Create trigger configuration."""
    config = {
        "type": trigger_type,
        "enabled": True,
    }

    if trigger_type == "schedule" and cron:
        config["cron_expression"] = cron
        config["timezone"] = "America/New_York"
        # Calculate next run (simplified)
        config["next_run"] = (
            datetime.now(timezone.utc) + timedelta(hours=random.randint(1, 24))
        ).isoformat()

    return config


async def generate_workflows(
    user_id: str, num_personal: int = 30, num_community: int = 20, num_explore: int = 25
):
    """Generate personal, community, and explore workflows."""
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    workflows_collection = db.workflows

    workflows = []
    workflow_ids = {
        "personal": [],
        "community": [],
        "explore": [],
    }

    print(
        f"Generating {num_personal} personal, {num_community} community, and {num_explore} explore workflows..."
    )

    # Generate personal workflows
    for i in range(num_personal):
        template = random.choice(WORKFLOW_TEMPLATES)
        workflow_id = generate_workflow_id()
        workflow_ids["personal"].append(workflow_id)

        # Randomize some aspects
        is_activated = random.choice([True, True, True, False])  # 75% activated

        workflow = {
            "_id": workflow_id,
            "id": workflow_id,
            "user_id": user_id,
            "title": template["title"],
            "description": template["description"],
            "steps": create_workflow_steps(template["categories"]),
            "trigger_config": create_trigger_config(
                template.get("trigger_type", "manual"), template.get("cron")
            ),
            "activated": is_activated,
            "is_public": False,
            "created_by": None,
            "current_step_index": 0,
            "execution_logs": [],
            "error_message": None,
            "total_executions": random.randint(0, 50) if is_activated else 0,
            "successful_executions": random.randint(0, 45) if is_activated else 0,
            "last_executed_at": (
                datetime.now(timezone.utc) - timedelta(days=random.randint(0, 30))
            ).isoformat()
            if is_activated and random.random() > 0.3
            else None,
            "created_at": (
                datetime.now(timezone.utc) - timedelta(days=random.randint(1, 90))
            ).isoformat(),
            "updated_at": (
                datetime.now(timezone.utc) - timedelta(days=random.randint(0, 30))
            ).isoformat(),
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "repeat": template.get("cron")
            if template.get("trigger_type") == "schedule"
            else None,
        }

        workflows.append(workflow)
        print(
            f"  [{i + 1}/{num_personal}] Created personal workflow: {template['title']}"
        )

    # Generate community workflows (public marketplace)
    for i in range(num_community):
        template = random.choice(WORKFLOW_TEMPLATES)
        workflow_id = generate_workflow_id()
        workflow_ids["community"].append(workflow_id)

        # Community workflows have higher execution counts
        total_execs = random.randint(50, 500)
        successful_execs = int(total_execs * random.uniform(0.85, 0.98))

        workflow = {
            "_id": workflow_id,
            "id": workflow_id,
            "user_id": user_id,  # All created by the same user
            "title": f"{template['title']} (Community Edition)",
            "description": f"{template['description']} - A proven workflow shared by the community.",
            "steps": create_workflow_steps(template["categories"]),
            "trigger_config": create_trigger_config(
                "manual"
            ),  # Community workflows default to manual
            "activated": True,
            "is_public": True,
            "created_by": user_id,
            "current_step_index": 0,
            "execution_logs": [],
            "error_message": None,
            "total_executions": total_execs,
            "successful_executions": successful_execs,
            "last_executed_at": (
                datetime.now(timezone.utc) - timedelta(hours=random.randint(1, 72))
            ).isoformat(),
            "created_at": (
                datetime.now(timezone.utc) - timedelta(days=random.randint(30, 180))
            ).isoformat(),
            "updated_at": (
                datetime.now(timezone.utc) - timedelta(days=random.randint(0, 14))
            ).isoformat(),
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "repeat": None,
        }

        workflows.append(workflow)
        print(
            f"  [{i + 1}/{num_community}] Created community workflow: {template['title']}"
        )

    # Generate explore workflows (featured/showcase workflows)
    for i in range(num_explore):
        template = random.choice(WORKFLOW_TEMPLATES)
        workflow_id = generate_workflow_id()
        workflow_ids["explore"].append(workflow_id)

        # Explore workflows have moderate execution counts and are public but not "community" (different UI)
        total_execs = random.randint(100, 1000)
        successful_execs = int(total_execs * random.uniform(0.90, 0.99))

        workflow = {
            "_id": workflow_id,
            "id": workflow_id,
            "user_id": user_id,  # All created by the same user
            "title": template["title"],
            "description": template["description"],
            "steps": create_workflow_steps(template["categories"]),
            "trigger_config": create_trigger_config("manual"),
            "activated": True,
            "is_public": True,
            "is_explore": True,  # New field to identify explore workflows
            "use_case_categories": template.get(
                "use_case_categories", ["featured"]
            ),  # Store categories for filtering
            "created_by": user_id,
            "current_step_index": 0,
            "execution_logs": [],
            "error_message": None,
            "total_executions": total_execs,
            "successful_executions": successful_execs,
            "last_executed_at": (
                datetime.now(timezone.utc) - timedelta(hours=random.randint(1, 48))
            ).isoformat(),
            "created_at": (
                datetime.now(timezone.utc) - timedelta(days=random.randint(60, 365))
            ).isoformat(),
            "updated_at": (
                datetime.now(timezone.utc) - timedelta(days=random.randint(0, 7))
            ).isoformat(),
            "scheduled_at": datetime.now(timezone.utc).isoformat(),
            "repeat": None,
        }

        workflows.append(workflow)
        print(
            f"  [{i + 1}/{num_explore}] Created explore workflow: {template['title']}"
        )

    # Insert all workflows
    if workflows:
        result = await workflows_collection.insert_many(workflows)
        print(f"\n✓ Successfully inserted {len(result.inserted_ids)} workflows")
        print(f"  - Personal workflows: {len(workflow_ids['personal'])}")
        print(f"  - Community workflows: {len(workflow_ids['community'])}")
        print(f"  - Explore workflows: {len(workflow_ids['explore'])}")

    client.close()
    return workflow_ids


async def delete_workflows(user_id: str):
    """Delete all workflows for a specific user."""
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    workflows_collection = db.workflows

    print(f"Deleting workflows for user {user_id}...")

    # Delete all workflows owned by this user
    result = await workflows_collection.delete_many({"user_id": user_id})

    print(f"✓ Deleted {result.deleted_count} workflows")

    client.close()


async def show_statistics(user_id: str):
    """Show statistics about generated workflows."""
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    workflows_collection = db.workflows

    print(f"\n=== Workflow Statistics for User {user_id} ===")

    # Count workflows
    personal_count = await workflows_collection.count_documents(
        {"user_id": user_id, "is_public": False}
    )
    community_count = await workflows_collection.count_documents(
        {"user_id": user_id, "is_public": True, "is_explore": {"$ne": True}}
    )
    explore_count = await workflows_collection.count_documents(
        {"user_id": user_id, "is_explore": True}
    )

    print(f"\nTotal workflows: {personal_count + community_count + explore_count}")
    print(f"  - Personal: {personal_count}")
    print(f"  - Community: {community_count}")
    print(f"  - Explore: {explore_count}")

    # Count by trigger type
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$group": {"_id": "$trigger_config.type", "count": {"$sum": 1}}},
    ]
    trigger_stats = await workflows_collection.aggregate(pipeline).to_list(length=None)

    print("\nBy trigger type:")
    for stat in trigger_stats:
        print(f"  - {stat['_id']}: {stat['count']}")

    # Execution statistics
    pipeline = [
        {"$match": {"user_id": user_id}},
        {
            "$group": {
                "_id": None,
                "total_executions": {"$sum": "$total_executions"},
                "successful_executions": {"$sum": "$successful_executions"},
                "avg_executions": {"$avg": "$total_executions"},
            }
        },
    ]
    exec_stats = await workflows_collection.aggregate(pipeline).to_list(length=None)

    if exec_stats:
        stats = exec_stats[0]
        print("\nExecution statistics:")
        print(f"  - Total executions: {stats['total_executions']}")
        print(f"  - Successful executions: {stats['successful_executions']}")
        print(f"  - Average per workflow: {stats['avg_executions']:.2f}")
        if stats["total_executions"] > 0:
            success_rate = (
                stats["successful_executions"] / stats["total_executions"]
            ) * 100
            print(f"  - Success rate: {success_rate:.2f}%")

    # Category distribution
    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$unwind": "$steps"},
        {"$group": {"_id": "$steps.tool_category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    category_stats = await workflows_collection.aggregate(pipeline).to_list(length=None)

    print("\nTop tool categories used:")
    for stat in category_stats:
        print(f"  - {stat['_id']}: {stat['count']} steps")

    client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Generate or delete test workflows for GAIA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate workflows
  python scripts/generate_workflows.py --generate --user-id 6887aac50ab42839de0edfe1

  # Delete workflows
  python scripts/generate_workflows.py --delete --user-id 6887aac50ab42839de0edfe1

  # Delete then generate (clean slate)
  python scripts/generate_workflows.py --both --user-id 6887aac50ab42839de0edfe1

  # Custom numbers
  python scripts/generate_workflows.py --generate --user-id 6887aac50ab42839de0edfe1 --personal 50 --community 30

  # Show statistics only
  python scripts/generate_workflows.py --stats --user-id 6887aac50ab42839de0edfe1
        """,
    )

    parser.add_argument(
        "--user-id", required=True, help="User ID to generate/delete workflows for"
    )

    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--generate", action="store_true", help="Generate new workflows"
    )
    action_group.add_argument(
        "--delete", action="store_true", help="Delete existing workflows"
    )
    action_group.add_argument(
        "--both",
        action="store_true",
        help="Delete existing workflows then generate new ones",
    )
    action_group.add_argument(
        "--stats", action="store_true", help="Show workflow statistics"
    )

    parser.add_argument(
        "--personal",
        type=int,
        default=30,
        help="Number of personal workflows to generate (default: 30)",
    )

    parser.add_argument(
        "--community",
        type=int,
        default=20,
        help="Number of community workflows to generate (default: 20)",
    )

    parser.add_argument(
        "--explore",
        type=int,
        default=25,
        help="Number of explore workflows to generate (default: 25)",
    )

    args = parser.parse_args()

    async def run():
        if args.stats:
            await show_statistics(args.user_id)
        elif args.delete:
            await delete_workflows(args.user_id)
        elif args.both:
            await delete_workflows(args.user_id)
            await generate_workflows(
                args.user_id, args.personal, args.community, args.explore
            )
            await show_statistics(args.user_id)
        elif args.generate:
            await generate_workflows(
                args.user_id, args.personal, args.community, args.explore
            )
            await show_statistics(args.user_id)

    try:
        asyncio.run(run())
        print("\n✓ Operation completed successfully!")
    except KeyboardInterrupt:
        print("\n\n✗ Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
