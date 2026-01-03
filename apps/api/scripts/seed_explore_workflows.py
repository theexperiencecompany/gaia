#!/usr/bin/env python3
"""
Comprehensive seed script for explore/discover workflows - FIXED VERSION with real Composio tools.

This script seeds the workflows collection with curated workflows for the
Explore & Discover section, organized by categories:
- Productivity
- Engineering
- Founders
- Marketing
- Knowledge Workers
- Students

Each workflow uses REAL tools from:
- Composio integrations (GMAIL, GITHUB, NOTION, SLACK, LINEAR, etc.)
- Core GAIA tools (create_todo, add_memory, web_search_tool, generate_document, etc.)

Usage:
  cd backend
  python scripts/seed_explore_workflows_fixed.py
  python scripts/seed_explore_workflows_fixed.py --dry-run
  python scripts/seed_explore_workflows_fixed.py --force --clear-existing
"""

import argparse
import asyncio
import json
import random
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add the backend directory to Python path so we can import from app
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.db.mongodb.collections import workflows_collection  # noqa: E402
from app.models.workflow_models import TriggerConfig, TriggerType, WorkflowStep  # noqa: E402


def generate_run_count() -> tuple[int, int]:
    """Generate realistic run counts with some variance."""
    base_runs = random.choice(  # noqa: S311  # nosec B311
        [
            random.randint(800, 1200),  # noqa: S311  # nosec B311
            random.randint(1300, 1800),  # noqa: S311  # nosec B311
            random.randint(2100, 2800),  # noqa: S311  # nosec B311
            random.randint(3200, 4200),  # noqa: S311  # nosec B311
        ]
    )
    success_rate = random.uniform(0.88, 0.97)  # noqa: S311  # nosec B311
    successful_runs = int(base_runs * success_rate)
    return base_runs, successful_runs


def create_step(
    step_number: int,
    title: str,
    category: str,
    description: str,
) -> dict[str, Any]:
    """Helper to create a workflow step with the abstract schema."""
    return {
        "id": f"step_{step_number}",
        "title": title,
        "category": category,
        "description": description,
    }


def get_productivity_workflows() -> list[dict[str, Any]]:
    """Productivity workflows for inbox management and task organization."""
    workflows = []

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Smart Inbox Triage & Auto-Reply",
            "description": "Automatically classify incoming emails, draft intelligent replies for routine messages, schedule follow-ups for important items, and flag high-priority emails.",
            "categories": ["Productivity", "featured"],
            "trigger_config": {"type": "email", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Fetch and Classify Recent Emails",
                    "gmail",
                    "Retrieve unread emails from the last 24 hours",
                ),
                create_step(
                    2,
                    "Draft Smart Replies",
                    "gmail",
                    "Generate context-aware draft replies for routine emails",
                ),
                create_step(
                    3,
                    "Create Follow-up Tasks",
                    "productivity",
                    "Create prioritized todo items for emails requiring action",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Daily Task Overview",
            "description": "Get a comprehensive view of all tasks due today. Shows pending todos, upcoming deadlines, and prioritized action items.",
            "categories": ["Productivity"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 7 * * 1-5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Fetch Today's Tasks",
                    "productivity",
                    "Retrieve all todos and tasks due today or overdue",
                ),
                create_step(
                    2,
                    "Check Calendar Events",
                    "google_calendar",
                    "Review today's calendar events",
                ),
                create_step(
                    3,
                    "Create Daily Focus Note",
                    "memory",
                    "Generate a structured daily focus document with top priorities",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Email Subscription Cleanup",
            "description": "Find and archive promotional and subscription emails cluttering your inbox. Identifies newsletters and marketing emails from the past day.",
            "categories": ["Productivity"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Search Subscription Emails",
                    "gmail",
                    "Find subscription and promotional emails",
                ),
                create_step(
                    2,
                    "Archive Low Priority Emails",
                    "gmail",
                    "Move subscription emails to archive",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Email to Task Converter",
            "description": "Transform important unread emails into actionable tasks. Extracts key information from emails and creates structured todos.",
            "categories": ["Productivity", "featured"],
            "trigger_config": {"type": "email", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Identify Actionable Emails",
                    "gmail",
                    "Find unread emails that contain action items",
                ),
                create_step(
                    2,
                    "Create Structured Tasks",
                    "productivity",
                    "Generate detailed todos from email content",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Weekly Email Summary Digest",
            "description": "Summarize long email threads and extract action items automatically. Cuts through lengthy conversations to surface key decisions.",
            "categories": ["Productivity"],
            "trigger_config": {"type": "email", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Fetch Long Email Threads",
                    "gmail",
                    "Retrieve email threads with multiple messages",
                ),
                create_step(
                    2,
                    "Extract Action Items",
                    "productivity",
                    "Parse email content and create todos for action items",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    return workflows


def get_engineering_workflows() -> list[dict[str, Any]]:
    """Engineering workflows for developers and technical teams."""
    workflows = []

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Weekly Standup from GitHub Activity",
            "description": "Automatically generate standup notes from your GitHub commits, PRs, and issues from the past week. Creates a formatted summary ready for team meetings.",
            "categories": ["Engineering", "featured"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 9 * * 1",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Fetch GitHub Commits",
                    "github",
                    "Retrieve all commits from the past week",
                ),
                create_step(
                    2,
                    "Get PR Activity",
                    "github",
                    "Fetch pull requests you've created or reviewed this week",
                ),
                create_step(
                    3,
                    "Create Notion Summary",
                    "notion",
                    "Generate a formatted weekly standup document with commits and PRs",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "PR Review Queue Summary",
            "description": "Get a prioritized list of pull requests waiting for your review with AI-generated summaries of changes, risk assessment, and estimated review time.",
            "categories": ["Engineering"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Fetch Pending PR Reviews",
                    "github",
                    "Get all open PRs where you're requested as a reviewer",
                ),
                create_step(
                    2,
                    "Analyze PR Files",
                    "github",
                    "Review changed files in each PR to assess complexity",
                ),
                create_step(
                    3,
                    "Create Review Priority List",
                    "productivity",
                    "Generate prioritized review tasks based on PR size and age",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Bug Report to GitHub Issue",
            "description": "Convert bug reports from Slack or email into properly formatted GitHub issues with reproduction steps and appropriate labels.",
            "categories": ["Engineering", "featured"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Search Bug Reports",
                    "slack",
                    "Find recent bug reports in designated Slack channels",
                ),
                create_step(
                    2,
                    "Create GitHub Issue",
                    "github",
                    "Generate a structured GitHub issue with bug details",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Daily Engineering Digest",
            "description": "Morning briefing with all open issues, pending PRs, and Linear tickets. Skip checking multiple dashboards and get a single prioritized view.",
            "categories": ["Engineering"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 8 * * 1-5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Fetch Open Issues",
                    "github",
                    "Get all open issues assigned to you",
                ),
                create_step(
                    2,
                    "Get Linear Tickets",
                    "linear",
                    "Retrieve your assigned Linear tickets and their status",
                ),
                create_step(
                    3,
                    "Create Morning Brief",
                    "memory",
                    "Generate a prioritized engineering task list for the day",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Spec to Linear Tasks",
            "description": "Parse a requirements document and automatically create Linear tickets with acceptance criteria, story points, and proper categorization.",
            "categories": ["Engineering"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Fetch Spec Document",
                    "notion",
                    "Retrieve the requirements document from Notion",
                ),
                create_step(
                    2,
                    "Create Linear Issues",
                    "linear",
                    "Generate Linear tickets from extracted requirements",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Hourly Review Queue Alert",
            "description": "Check all open pull requests hourly, rank by importance and age, and send a prioritized list to Slack to prevent review bottlenecks.",
            "categories": ["Engineering"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 * * * 1-5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Check Open PRs",
                    "github",
                    "Get all open PRs sorted by age",
                ),
                create_step(
                    2,
                    "Post to Slack",
                    "slack",
                    "Send prioritized PR list to the engineering channel",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "PR Summary to Slack",
            "description": "When a new PR is opened, analyze the changes, summarize what was modified, and post to Slack so reviewers can quickly understand the context.",
            "categories": ["Engineering"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Get PR Details",
                    "github",
                    "Fetch the pull request details including description",
                ),
                create_step(
                    2,
                    "Analyze Changes",
                    "github",
                    "Review the files changed to identify scope",
                ),
                create_step(
                    3,
                    "Post Summary to Slack",
                    "slack",
                    "Send formatted PR summary to the team channel",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    return workflows


def get_founders_workflows() -> list[dict[str, Any]]:
    """Founder and executive workflows."""
    workflows = []

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Morning Priority Map",
            "description": "Start each day focused with an AI-generated priority list. Reviews your calendar, pending tasks, and deadlines to surface the top 3 things that matter most today.",
            "categories": ["Founders", "featured"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 6 * * 1-5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Review Today's Calendar",
                    "google_calendar",
                    "Fetch all meetings and events scheduled for today",
                ),
                create_step(
                    2,
                    "Check Pending Tasks",
                    "productivity",
                    "Get all todos with upcoming deadlines",
                ),
                create_step(
                    3,
                    "Generate Priority Map",
                    "memory",
                    "Create a focused daily priority document with top 3 objectives",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Weekly Team Sync Document",
            "description": "Automatically collect project updates from Slack, GitHub, and Linear to generate a comprehensive weekly team brief. Standardizes communication without manual effort.",
            "categories": ["Founders"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 9 * * 1",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Gather Slack Updates",
                    "slack",
                    "Search for project updates from the past week",
                ),
                create_step(
                    2,
                    "Fetch GitHub Activity",
                    "github",
                    "Get engineering progress from recent commits",
                ),
                create_step(
                    3,
                    "Create Team Brief",
                    "notion",
                    "Generate a formatted weekly team update document",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Founder Social Content Assistant",
            "description": "Weekly analysis of your social media performance plus AI-drafted LinkedIn content. Keeps founders active on social without the manual effort.",
            "categories": ["Founders"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 10 * * 1",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Research Industry Trends",
                    "search",
                    "Find trending topics and discussions in your industry",
                ),
                create_step(
                    2,
                    "Draft LinkedIn Post",
                    "memory",
                    "Generate thought leadership content drafts based on trends",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Applicant Pipeline Automation",
            "description": "When new applicants are identified, automatically add them to tracking, send evaluation tasks, and set up the hiring workflow.",
            "categories": ["Founders"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Add to Airtable",
                    "airtable",
                    "Create a new applicant record in the hiring pipeline",
                ),
                create_step(
                    2,
                    "Send Evaluation Email",
                    "gmail",
                    "Send the candidate an evaluation task email",
                ),
                create_step(
                    3,
                    "Create Interview Todo",
                    "productivity",
                    "Set up follow-up task to review candidate submission",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Investor CRM Update",
            "description": "Parse investor emails and automatically log communication details to Airtable. Replaces manual investor spreadsheet maintenance.",
            "categories": ["Founders"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Search Investor Emails",
                    "gmail",
                    "Find recent emails from investors",
                ),
                create_step(
                    2,
                    "Update Airtable CRM",
                    "airtable",
                    "Log investor communications and update relationship status",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Customer Voice Daily Summary",
            "description": "Scan customer feedback from email and social channels to compile a sentiment summary with emerging themes.",
            "categories": ["Founders", "featured"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 8 * * 1-5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Fetch Customer Emails",
                    "gmail",
                    "Search for customer feedback and support-related emails",
                ),
                create_step(
                    2,
                    "Search Social Mentions",
                    "search",
                    "Find social media mentions about your product",
                ),
                create_step(
                    3,
                    "Generate Sentiment Report",
                    "memory",
                    "Create a customer voice summary with sentiment analysis",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    return workflows


def get_marketing_workflows() -> list[dict[str, Any]]:
    """Marketing team workflows."""
    workflows = []

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Weekly SEO Content Ideas",
            "description": "Generate SEO-optimized content ideas based on trending topics and keyword research. Creates actionable content briefs with target keywords and outlines.",
            "categories": ["Marketing", "featured"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 9 * * 1",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Research Trending Topics",
                    "search",
                    "Find trending topics and high-volume keywords in your industry",
                ),
                create_step(
                    2,
                    "Create Content Tasks",
                    "productivity",
                    "Generate content brief tasks with keyword targets and outlines",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Content Calendar Builder",
            "description": "Review social analytics and upcoming events to generate a content schedule. Aligns content with company events and removes guesswork from planning.",
            "categories": ["Marketing"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 10 * * 1",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Check Upcoming Events",
                    "google_calendar",
                    "Review company events, launches, and marketing milestones",
                ),
                create_step(
                    2,
                    "Research Content Opportunities",
                    "search",
                    "Find upcoming industry events and trending topics",
                ),
                create_step(
                    3,
                    "Create Content Calendar",
                    "notion",
                    "Generate a monthly content calendar with topics and publish dates",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Weekly Campaign Performance Pack",
            "description": "Load marketing metrics from connected tools and generate a summary performance report. Replaces manual analytics compilation.",
            "categories": ["Marketing"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 9 * * 5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Fetch Campaign Data",
                    "airtable",
                    "Retrieve campaign metrics and performance data from tracking base",
                ),
                create_step(
                    2,
                    "Generate Performance Report",
                    "documents",
                    "Create a formatted weekly campaign report with KPIs and insights",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Competitor Brief Builder",
            "description": "Monitor competitor activity across social and web channels to produce a competitive intelligence brief. Skip manual scanning and get actionable insights.",
            "categories": ["Marketing"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Search Competitor Activity",
                    "search",
                    "Find recent competitor announcements, content, and social activity",
                ),
                create_step(
                    2,
                    "Create Competitor Brief",
                    "memory",
                    "Generate a competitive intelligence summary with key findings",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Social Mention Response Manager",
            "description": "Classify social comments and mentions, draft appropriate responses, and log interactions for tracking. Minimizes reaction time to social engagement.",
            "categories": ["Marketing"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Search Social Mentions",
                    "search",
                    "Find recent social media mentions and comments about your brand",
                ),
                create_step(
                    2,
                    "Log to Airtable",
                    "airtable",
                    "Record social mentions with sentiment and response status",
                ),
                create_step(
                    3,
                    "Create Response Tasks",
                    "productivity",
                    "Generate response tasks for mentions requiring engagement",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Influencer Discovery & Outreach",
            "description": "Scan for relevant influencers, update your outreach database, and draft personalized outreach emails. Trims hours of research time.",
            "categories": ["Marketing"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 10 * * 3",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Research Influencers",
                    "search",
                    "Find relevant influencers and content creators in your industry",
                ),
                create_step(
                    2,
                    "Update Outreach Database",
                    "airtable",
                    "Add discovered influencers to outreach tracking",
                ),
                create_step(
                    3,
                    "Draft Outreach Emails",
                    "gmail",
                    "Create personalized outreach email drafts",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    return workflows


def get_knowledge_worker_workflows() -> list[dict[str, Any]]:
    """Knowledge worker workflows for productivity and documentation."""
    workflows = []

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Weekly Work Report Generator",
            "description": "Compile completed tasks from your todo lists into a formatted weekly report. Eliminates the common chore of writing weekly updates manually.",
            "categories": ["Knowledge Workers", "featured"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 16 * * 5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Fetch Completed Tasks",
                    "productivity",
                    "Get all tasks completed this week across your todo lists",
                ),
                create_step(
                    2,
                    "Generate Weekly Report",
                    "memory",
                    "Create a formatted weekly accomplishment report with categorized achievements",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Research Link Summarizer",
            "description": "Provide links or topics and get organized summaries saved to Notion. Reduces time spent on initial research and note-taking.",
            "categories": ["Knowledge Workers"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Fetch Web Content",
                    "search",
                    "Retrieve and parse content from provided URLs or search results",
                ),
                create_step(
                    2,
                    "Save to Notion",
                    "notion",
                    "Create an organized Notion page with summarized research and key findings",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Daily Meeting Context Builder",
            "description": "Before your first meeting each day, gather relevant emails, documents, and notes for each calendar event. Stop scrambling for context before calls.",
            "categories": ["Knowledge Workers", "featured"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 7 * * 1-5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Get Today's Meetings",
                    "google_calendar",
                    "Fetch all meetings scheduled for today with attendee information",
                ),
                create_step(
                    2,
                    "Search Related Emails",
                    "gmail",
                    "Find recent emails from meeting attendees and about meeting topics",
                ),
                create_step(
                    3,
                    "Create Meeting Prep Notes",
                    "memory",
                    "Generate meeting context documents with relevant background and talking points",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Email Thread to Structured Tasks",
            "description": "When long emails arrive, automatically summarize them and extract action items into your todo list. Cuts time reading lengthy threads.",
            "categories": ["Knowledge Workers"],
            "trigger_config": {"type": "email", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Fetch Email Thread",
                    "gmail",
                    "Get the complete email thread for context",
                ),
                create_step(
                    2,
                    "Create Action Tasks",
                    "productivity",
                    "Extract and create todos for action items found in the email thread",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Idea to Notion Page",
            "description": "Transform rough ideas and notes into structured Notion pages with proper formatting, sections, and action items.",
            "categories": ["Knowledge Workers"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Create Structured Page",
                    "notion",
                    "Convert raw ideas into a well-organized Notion page with sections and formatting",
                ),
                create_step(
                    2,
                    "Create Follow-up Tasks",
                    "productivity",
                    "Generate action items based on the documented idea",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Document Outline Builder",
            "description": "Research a topic and produce a clean, structured outline ready for writing. Helps you start creating content instantly.",
            "categories": ["Knowledge Workers"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Research Topic",
                    "search",
                    "Gather comprehensive information about the document topic",
                ),
                create_step(
                    2,
                    "Generate Outline",
                    "documents",
                    "Create a detailed document outline with sections, key points, and structure",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    return workflows


def get_student_workflows() -> list[dict[str, Any]]:
    """Student productivity workflows."""
    workflows = []

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Daily Study Plan Generator",
            "description": "Check your classes, deadlines, and tasks to create a personalized study plan for the day. Stop wasting time figuring out what to study next.",
            "categories": ["Students", "featured"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 7 * * 1-5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Check Today's Classes",
                    "google_calendar",
                    "Get all classes and study sessions scheduled for today",
                ),
                create_step(
                    2,
                    "Review Pending Tasks",
                    "productivity",
                    "Fetch assignments and study tasks with upcoming deadlines",
                ),
                create_step(
                    3,
                    "Create Study Plan",
                    "memory",
                    "Generate a prioritized daily study plan with time allocations",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Lecture Notes Summarizer",
            "description": "Summarize lecture notes from Notion, extract key concepts and potential exam topics. Cuts revision time significantly.",
            "categories": ["Students"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Fetch Lecture Notes",
                    "notion",
                    "Retrieve lecture notes from your Notion study workspace",
                ),
                create_step(
                    2,
                    "Create Study Summary",
                    "memory",
                    "Generate a condensed summary with key concepts, definitions, and exam-relevant points",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Weekly Assignment Tracker",
            "description": "Review your calendar and build a comprehensive list of upcoming assignments and deadlines. Never be surprised by a due date again.",
            "categories": ["Students"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 18 * * 0",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Check Assignment Deadlines",
                    "google_calendar",
                    "Get all assignment deadlines for the next two weeks",
                ),
                create_step(
                    2,
                    "Create Assignment Tasks",
                    "productivity",
                    "Generate prioritized tasks for each assignment with milestone dates",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Academic Paper Summarizer",
            "description": "Summarize academic papers and research articles, then save organized notes to Notion for easy reference during writing.",
            "categories": ["Students"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Fetch Paper Content",
                    "search",
                    "Retrieve and parse the academic paper or research article",
                ),
                create_step(
                    2,
                    "Save Research Notes",
                    "notion",
                    "Create a structured research note with summary, key findings, and citations",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Professor Email Task Extractor",
            "description": "When emails from professors arrive, automatically extract deadlines, requirements, and create corresponding tasks.",
            "categories": ["Students"],
            "trigger_config": {"type": "email", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Process Professor Email",
                    "gmail",
                    "Retrieve the email content to extract requirements and deadlines",
                ),
                create_step(
                    2,
                    "Create Class Tasks",
                    "productivity",
                    "Generate tasks from extracted deadlines and requirements with due dates",
                ),
                create_step(
                    3,
                    "Add to Calendar",
                    "google_calendar",
                    "Schedule study blocks and deadline reminders",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Group Project Board Setup",
            "description": "Create a complete project management board with task structure for group assignments. Get organized from day one.",
            "categories": ["Students"],
            "trigger_config": {"type": "manual", "enabled": True},
            "steps": [
                create_step(
                    1,
                    "Create Trello Board",
                    "trello",
                    "Set up a new Trello board with standard project columns",
                ),
                create_step(
                    2,
                    "Add Project Tasks",
                    "trello",
                    "Create task cards for project milestones and deliverables",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    total, successful = generate_run_count()
    workflows.append(
        {
            "title": "Weekly Study Review & Practice",
            "description": "Compile all notes from the week into a revision pack with generated practice questions. Makes exam prep systematic and effective.",
            "categories": ["Students", "featured"],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 15 * * 5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Fetch Week's Notes",
                    "notion",
                    "Search for all lecture notes and study materials from this week",
                ),
                create_step(
                    2,
                    "Generate Revision Pack",
                    "documents",
                    "Create a comprehensive revision document with summaries and practice questions",
                ),
                create_step(
                    3,
                    "Schedule Review Session",
                    "google_calendar",
                    "Block time for reviewing the revision pack",
                ),
            ],
            "total_executions": total,
            "successful_executions": successful,
        }
    )

    return workflows


def get_all_workflows() -> list[dict[str, Any]]:
    """Combine all workflow categories."""
    all_workflows = []
    all_workflows.extend(get_productivity_workflows())
    all_workflows.extend(get_engineering_workflows())
    all_workflows.extend(get_founders_workflows())
    all_workflows.extend(get_marketing_workflows())
    all_workflows.extend(get_knowledge_worker_workflows())
    all_workflows.extend(get_student_workflows())
    return all_workflows


def create_workflow_document(config: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Create a workflow document ready for MongoDB insertion."""
    workflow_id = f"wf_{uuid.uuid4().hex[:12]}"

    trigger_type = TriggerType(config["trigger_config"]["type"])
    trigger_config = TriggerConfig(
        type=trigger_type,
        enabled=config["trigger_config"].get("enabled", True),
        cron_expression=config["trigger_config"].get("cron_expression"),
        timezone=config["trigger_config"].get("timezone", "UTC"),
    )

    if trigger_config.type == TriggerType.SCHEDULE and trigger_config.cron_expression:
        trigger_config.update_next_run()

    steps = []
    for step_config in config["steps"]:
        step = WorkflowStep(**step_config)
        steps.append(step.model_dump(mode="json"))

    now = datetime.now(timezone.utc)

    return {
        "_id": workflow_id,
        "id": workflow_id,
        "user_id": user_id,
        "title": config["title"],
        "description": config["description"],
        "steps": steps,
        "trigger_config": trigger_config.model_dump(mode="json"),
        "activated": True,
        "is_public": True,
        "is_explore": True,
        "use_case_categories": config.get("categories", ["featured"]),
        "created_by": user_id,
        "total_executions": config.get("total_executions", 0),
        "successful_executions": config.get("successful_executions", 0),
        "current_step_index": 0,
        "execution_logs": [],
        "created_at": now,
        "updated_at": now,
    }


async def create_backup() -> str:
    """Create a backup of existing explore workflows."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"explore_workflows_backup_{timestamp}.json"

    try:
        existing = []
        async for workflow in workflows_collection.find({"is_explore": True}):
            workflow["_id"] = str(workflow["_id"])
            existing.append(workflow)

        with open(backup_file, "w") as f:
            json.dump(existing, f, indent=2, default=str)

        print(f"✅ Backup created: {backup_file}")
        return backup_file
    except Exception as e:
        print(f"❌ Error creating backup: {e}")
        raise


async def seed_explore_workflows(
    dry_run: bool = False,
    force: bool = False,
    backup: bool = True,
    user_id: str = "system",
    clear_existing: bool = False,
) -> None:
    """Seed the workflows collection with explore workflows."""
    print("🚀 Starting explore workflows seeding...")

    workflow_configs = get_all_workflows()

    existing_explore = await workflows_collection.count_documents({"is_explore": True})
    existing_total = await workflows_collection.count_documents({})

    print("\n📊 Current State:")
    print(f"   📄 Total workflows: {existing_total}")
    print(f"   🔍 Explore workflows: {existing_explore}")
    print(f"   ➕ Workflows to seed: {len(workflow_configs)}")

    categories: dict[str, int] = {}
    for config in workflow_configs:
        for cat in config.get("categories", ["featured"]):
            categories[cat] = categories.get(cat, 0) + 1

    print("\n📁 By Category:")
    for cat, count in sorted(categories.items()):
        print(f"   • {cat}: {count}")

    print("\n📝 Workflows to Add:")
    for i, config in enumerate(workflow_configs, 1):
        trigger = config["trigger_config"]["type"]
        cats = ", ".join(config.get("categories", ["featured"]))
        print(f"   {i:2d}. [{trigger:8s}] {config['title']}")
        print(f"       Categories: {cats}")

    if dry_run:
        print("\n🔍 DRY RUN - No changes applied.")
        return

    if not force:
        response = input(
            f"\n❓ Seed {len(workflow_configs)} explore workflows? (y/N): "
        )
        if response.lower() != "y":
            print("❌ Cancelled.")
            return

    if backup:
        await create_backup()

    if clear_existing:
        result = await workflows_collection.delete_many({"is_explore": True})
        print(f"🗑️  Cleared {result.deleted_count} existing explore workflows")

    print("\n🔄 Seeding workflows...")

    to_insert = []
    skipped = 0

    for config in workflow_configs:
        existing = await workflows_collection.find_one(
            {
                "title": config["title"],
                "is_explore": True,
            }
        )

        if existing and not clear_existing:
            print(f"⚠️  Skipping '{config['title']}' - already exists")
            skipped += 1
            continue

        doc = create_workflow_document(config, user_id)
        to_insert.append(doc)
        print(f"✅ Prepared: {config['title']}")

    if to_insert:
        result = await workflows_collection.insert_many(to_insert)
        print(f"\n🎉 Successfully seeded {len(result.inserted_ids)} workflows!")
    else:
        print("\n⚠️  No new workflows to add")

    if skipped > 0:
        print(f"⏭️  Skipped {skipped} existing workflows")

    final_explore = await workflows_collection.count_documents({"is_explore": True})
    final_total = await workflows_collection.count_documents({})

    print("\n📊 Final State:")
    print(f"   📄 Total workflows: {final_total}")
    print(f"   🔍 Explore workflows: {final_explore}")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Seed explore/discover workflows for GAIA (FIXED VERSION with real tools)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show changes without applying them",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating backup",
    )
    parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="Clear existing explore workflows before seeding",
    )
    parser.add_argument(
        "--user-id",
        type=str,
        default="system",
        help="User ID for workflows (default: system)",
    )

    return parser.parse_args()


async def main():
    """Main function."""
    args = parse_arguments()

    try:
        await seed_explore_workflows(
            dry_run=args.dry_run,
            force=args.force,
            backup=not args.no_backup,
            user_id=args.user_id,
            clear_existing=args.clear_existing,
        )
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
