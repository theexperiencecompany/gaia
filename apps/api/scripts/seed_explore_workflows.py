#!/usr/bin/env python3
"""
Seed script for explore/discover workflows - outcome-first curated set.

The explore use cases behind /use-cases, curated to poke.com's bar:
- Titles are everyday outcomes ("Assignment Tracker", not "Email to Task Converter")
- Descriptions are one-line promises ("Never be surprised by a due date again")
- Prompts are the real runnable instructions (shown on the detail page)
- 1-3 steps, at most one external integration per flow; 14 of 28 need none
- Run counts are curated display values (DISPLAY_RUN_COUNTS), not measured usage

Categories: Study, Email, Meetings, Home admin, Content, Focus & planning,
Dev, Health & habits. 8 workflows are flagged `featured` (impact-first).

Usage:
  cd apps/api
  uv run python scripts/seed_explore_workflows.py              # seed (interactive)
  uv run python scripts/seed_explore_workflows.py --dry-run    # report only
  uv run python scripts/seed_explore_workflows.py --force --prune
"""

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any
import uuid

# Add the backend directory to Python path so we can import from app
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.db.mongodb.collections import get_async_collection
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)
from app.services.system_workflows.definitions.calendar import CALENDAR_SYSTEM_WORKFLOWS
from app.services.system_workflows.definitions.gmail import GMAIL_SYSTEM_WORKFLOWS
from shared.py.utils.slugify import slugify

workflows_collection = get_async_collection("workflows")


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


def get_study_workflows() -> list[dict[str, Any]]:
    return [
        {
            "title": "Assignment Tracker",
            "description": "Never be surprised by a due date again.",
            "icon": "Task01Icon",
            "icon_color": "#ad8dfe",
            "prompt": (
                "Every Sunday at 6pm, review my calendar and todos, find "
                "assignments due in the next two weeks, and create a todo for "
                "each one with its due date."
            ),
            "categories": ["Study"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 18 * * 0",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Find upcoming assignments",
                    "googlecalendar",
                    "Check calendar and todos for assignments due in the next two weeks.",
                ),
                create_step(
                    2,
                    "Create todos with due dates",
                    "todos",
                    "Create a todo for each assignment with its due date attached.",
                ),
            ],
        },
        {
            "title": "Study Plan Today",
            "description": "Every morning, a plan for what to study today.",
            "icon": "StudyLampIcon",
            "icon_color": "#e175d9",
            "prompt": (
                "Every weekday at 7am, look at my class schedule and upcoming "
                "exams, then give me a short study plan for today: what to "
                "review, for how long, and in what order."
            ),
            "categories": ["Study"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 7 * * 1-5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Check class schedule and deadlines",
                    "googlecalendar",
                    "Pull today's classes and any exam or assignment deadlines.",
                ),
                create_step(
                    2,
                    "Build today's study plan",
                    "gaia",
                    "Turn the schedule into a short, ordered study plan.",
                ),
            ],
        },
        {
            "title": "Lecture Notes Summarizer",
            "description": "Share your notes, get a clean summary you can actually revise from.",
            "icon": "Book01Icon",
            "icon_color": "#ad8dfe",
            "prompt": (
                "Whenever I share lecture notes, summarize them into clear, "
                "structured notes: key concepts, definitions, and anything "
                "likely to be on an exam."
            ),
            "categories": ["Study"],
            "trigger_config": {
                "type": "manual",
                "enabled": True,
            },
            "steps": [
                create_step(
                    1,
                    "Summarize the notes",
                    "documents",
                    "Turn raw lecture notes into structured summary notes.",
                ),
            ],
        },
        {
            "title": "Exam Revision Pack",
            "description": "A few weeks before each exam, get a condensed revision guide from your notes.",
            "icon": "GraduationScrollIcon",
            "icon_color": "#e175d9",
            "prompt": (
                "Every Sunday at 10am, check for exams in the next three weeks. "
                "For each one, gather my notes on the subject and build a "
                "revision pack: condensed summaries, key formulas or dates, "
                "and practice questions."
            ),
            "categories": ["Study", "featured"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 10 * * 0",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Gather notes on the subject",
                    "notion",
                    "Collect notes and documents related to the exam subject.",
                ),
                create_step(
                    2,
                    "Build the revision pack",
                    "documents",
                    "Compile summaries, key facts, and practice questions.",
                ),
            ],
        },
    ]


def get_email_workflows() -> list[dict[str, Any]]:
    return [
        {
            "title": "Follow-up Reminders",
            "description": "Never let an important email go unanswered.",
            "icon": "MailSend01Icon",
            "icon_color": "#ff726b",
            "prompt": (
                "Every weekday at 4pm, check my sent mail for messages that "
                "haven't been replied to in three or more days. For each one, "
                "show me a short list with a draft follow-up I can send with "
                "one tap."
            ),
            "categories": ["Email", "featured"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 16 * * 1-5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Find unreplied sent emails",
                    "gmail",
                    "Find sent emails older than three days with no reply.",
                ),
                create_step(
                    2,
                    "Draft follow-ups",
                    "gmail",
                    "Write a short, natural follow-up draft for each one.",
                ),
            ],
        },
        {
            "title": "Monthly Subscription Audit",
            "description": "See every subscription in one report, so nothing bills you silently.",
            "icon": "ReceiptDollarIcon",
            "icon_color": "#5fbf49",
            "prompt": (
                "On the 1st of every month, scan my inbox for subscription and "
                "recurring-charge emails, then give me a report: service, "
                "amount, renewal date, and flag anything I haven't used in a "
                "while."
            ),
            "categories": ["Email", "featured"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 9 1 * *",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Scan inbox for subscriptions",
                    "gmail",
                    "Find subscription and recurring-charge emails.",
                ),
                create_step(
                    2,
                    "Compile the report",
                    "gaia",
                    "Build the service, amount, and renewal date report.",
                ),
            ],
        },
        {
            "title": "Email to Task",
            "description": "Flag an email and it becomes a to-do.",
            "icon": "Mail01Icon",
            "icon_color": "#f68001",
            "prompt": (
                "Whenever I ask, turn the emails I point to into todos: a "
                "clear title, what needs doing, and the deadline if one is "
                "mentioned. Add them to my task list."
            ),
            "categories": ["Email"],
            "trigger_config": {
                "type": "manual",
                "enabled": True,
            },
            "steps": [
                create_step(
                    1,
                    "Read the email",
                    "gmail",
                    "Read the flagged email and extract the ask.",
                ),
                create_step(
                    2,
                    "Create the todo",
                    "todos",
                    "Create a todo with a clear title and deadline if stated.",
                ),
            ],
        },
        {
            "title": "Add Deadlines to Calendar",
            "description": "Deadline emails become calendar events, so nothing slips.",
            "icon": "CalendarAdd01Icon",
            "icon_color": "#f68001",
            "prompt": (
                "Whenever a new email mentions a deadline, such as a bill due "
                "date, an assignment, or a sign-up cutoff, create a calendar "
                "event for it the day before so I get a heads-up in time."
            ),
            "categories": ["Email"],
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "gmail_new_message",
                "trigger_data": {"trigger_name": "gmail_new_message"},
            },
            "steps": [
                create_step(
                    1,
                    "Create the calendar event",
                    "googlecalendar",
                    "Create a calendar event the day before the deadline.",
                ),
            ],
        },
    ]


def get_meetings_workflows() -> list[dict[str, Any]]:
    return [
        {
            "title": "Meeting Prep",
            "description": "Before every meeting, a one-page briefing on who you're meeting and what's on the agenda.",
            "icon": "Calendar01Icon",
            "icon_color": "#09b7dc",
            "prompt": (
                "When a meeting is about to start, gather the calendar invite "
                "and any notes I've saved, then summarize: who I'm meeting, "
                "what they care about, and three things to cover."
            ),
            "categories": ["Meetings"],
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "calendar_event_starting_soon",
                "trigger_data": {
                    "trigger_name": "calendar_event_starting_soon",
                    "calendar_ids": ["primary"],
                    "minutes_before_start": 10,
                },
            },
            "steps": [
                create_step(
                    1,
                    "Gather context",
                    "memory",
                    "Pull the invite details and any saved notes about the attendees.",
                ),
                create_step(
                    2,
                    "Build the briefing",
                    "documents",
                    "Write the one-page briefing with three talking points.",
                ),
            ],
        },
        {
            "title": "Meeting Notes Summary",
            "description": "Share your meeting notes, get a clean summary with decisions and action items.",
            "icon": "Note01Icon",
            "icon_color": "#72a3fe",
            "prompt": (
                "Whenever I share meeting notes, summarize them into key "
                "decisions, open questions, and action items, each with an "
                "owner if mentioned. Add the action items to my todos."
            ),
            "categories": ["Meetings"],
            "trigger_config": {
                "type": "manual",
                "enabled": True,
            },
            "steps": [
                create_step(
                    1,
                    "Summarize the notes",
                    "documents",
                    "Extract decisions, open questions, and action items.",
                ),
                create_step(
                    2,
                    "Add action items",
                    "todos",
                    "Create a todo for each action item.",
                ),
            ],
        },
        {
            "title": "Post-meeting Follow-ups",
            "description": "After every meeting, follow-ups drafted, so nothing falls through.",
            "icon": "MailSend01Icon",
            "icon_color": "#09b7dc",
            "prompt": (
                "Every weekday at 5pm, check my calendar for meetings that "
                "ended today, review any notes I saved, and draft a follow-up "
                "email for each one: the decisions made and each person's "
                "action items, ready for me to send."
            ),
            "categories": ["Meetings"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 17 * * 1-5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Find today's meetings",
                    "googlecalendar",
                    "Check calendar for meetings that ended today.",
                ),
                create_step(
                    2,
                    "Draft follow-up emails",
                    "gmail",
                    "Draft a follow-up with decisions and action items.",
                ),
            ],
        },
    ]


def get_home_admin_workflows() -> list[dict[str, Any]]:
    return [
        {
            "title": "Morning Briefing",
            "description": "Wake up to your day and your priorities, all in one message.",
            "icon": "Sun01Icon",
            "icon_color": "#f68001",
            "prompt": (
                "Every morning at 7:30am, gather today's calendar events and "
                "anything important from memory, then send me a short "
                "briefing: what's today, what needs attention, and what I "
                "should know."
            ),
            "categories": ["Home admin", "featured"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "30 7 * * *",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Gather today's events and urgent items",
                    "googlecalendar",
                    "Collect today's calendar events and anything time-sensitive.",
                ),
                create_step(
                    2,
                    "Compile the briefing",
                    "gaia",
                    "Write the short morning briefing from the gathered items.",
                ),
            ],
        },
        {
            "title": "Rent Reminder",
            "description": "A heads-up three days before month-end, so rent is never late.",
            "icon": "Money01Icon",
            "icon_color": "#5fbf49",
            "prompt": (
                "On the 25th of every month, remind me that rent is due at "
                "month-end. Keep it short and friendly."
            ),
            "categories": ["Home admin"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 9 25 * *",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Send the reminder",
                    "reminders",
                    "Send a short, friendly rent reminder.",
                ),
            ],
        },
        {
            "title": "Weekly Meal Plan",
            "description": "Every Sunday, plan your week's dinners and get a matching grocery list.",
            "icon": "Restaurant01Icon",
            "icon_color": "#eebe0c",
            "prompt": (
                "Every Sunday at 10am, plan dinners for the week: quick, "
                "varied, and mindful of what I already have. Then give me a "
                "grocery list grouped by aisle."
            ),
            "categories": ["Home admin"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 10 * * 0",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Plan the week's dinners",
                    "gaia",
                    "Plan seven dinners using what I already have.",
                ),
                create_step(
                    2,
                    "Build the grocery list",
                    "search",
                    "Turn the plan into a grocery list grouped by aisle.",
                ),
            ],
        },
        {
            "title": "Birthday Gift Ideas",
            "description": "Never miss a birthday, and always have a gift idea ready.",
            "icon": "GiftIcon",
            "icon_color": "#fb6ca0",
            "prompt": (
                "Every Sunday at 11am, scan my calendar and contacts for "
                "birthdays in the next two weeks, and for each one suggest a "
                "gift idea based on what I know about the person."
            ),
            "categories": ["Home admin"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 11 * * 0",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Find upcoming birthdays",
                    "googlecalendar",
                    "Find birthdays in the next two weeks.",
                ),
                create_step(
                    2,
                    "Suggest gifts",
                    "search",
                    "Suggest a gift idea for each person.",
                ),
            ],
        },
    ]


def get_content_workflows() -> list[dict[str, Any]]:
    return [
        {
            "title": "Weekly Content Ideas",
            "description": "Every Monday, fresh content topics for your niche.",
            "icon": "Idea01Icon",
            "icon_color": "#ad8dfe",
            "prompt": (
                "Every Monday at 9am, look at trending topics in my niche and "
                "my past content, then give me five fresh content ideas with a "
                "one-line angle for each."
            ),
            "categories": ["Content"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 9 * * 1",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Find trending topics",
                    "search",
                    "Find what's trending in my niche.",
                ),
                create_step(
                    2,
                    "Generate five ideas",
                    "gaia",
                    "Give five fresh ideas with a one-line angle each.",
                ),
            ],
        },
        {
            "title": "Social Post Drafts",
            "description": "Turn your ideas into posts you can publish as-is.",
            "icon": "Megaphone01Icon",
            "icon_color": "#e175d9",
            "prompt": (
                "Whenever I ask, turn my content ideas into ready-to-post "
                "drafts: a hook, the body, and a call to action, sized for "
                "the platform I name."
            ),
            "categories": ["Content"],
            "trigger_config": {
                "type": "manual",
                "enabled": True,
            },
            "steps": [
                create_step(
                    1,
                    "Write the post draft",
                    "documents",
                    "Turn the idea into a ready-to-post draft.",
                ),
            ],
        },
        {
            "title": "Research to Outline",
            "description": "Give GAIA a topic, get a structured outline ready for writing.",
            "icon": "ClipboardIcon",
            "icon_color": "#72a3fe",
            "prompt": (
                "Whenever I give you a topic or links, research it and produce "
                "a clean, structured outline with the key points and sources, "
                "ready for me to write from."
            ),
            "categories": ["Content"],
            "trigger_config": {
                "type": "manual",
                "enabled": True,
            },
            "steps": [
                create_step(
                    1,
                    "Research the topic",
                    "search",
                    "Research the topic or provided links.",
                ),
                create_step(
                    2,
                    "Build the outline",
                    "documents",
                    "Produce a structured outline with key points and sources.",
                ),
            ],
        },
        {
            "title": "Competitor Watch",
            "description": "A monthly rundown of what your competitors shipped and said, so you're never blindsided.",
            "icon": "Telescope01Icon",
            "icon_color": "#09b7dc",
            "prompt": (
                "On the 1st of every month, research my competitors' recent "
                "launches, pricing changes, and posts, then give me a short "
                "rundown of what changed and what it means for me."
            ),
            "categories": ["Content", "featured"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 9 1 * *",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Research competitors",
                    "search",
                    "Find competitors' recent launches, pricing, and posts.",
                ),
                create_step(
                    2,
                    "Write the rundown",
                    "gaia",
                    "Summarize what changed and what it means.",
                ),
            ],
        },
    ]


def get_focus_workflows() -> list[dict[str, Any]]:
    return [
        {
            "title": "Morning Priority Map",
            "description": "Every morning, your top three tasks for today, in the order to do them.",
            "icon": "Target01Icon",
            "icon_color": "#f68001",
            "prompt": (
                "Every morning at 8:30am, review my open tasks and deadlines, "
                "pick the three that matter most today, and tell me what to do "
                "first."
            ),
            "categories": ["Focus & planning"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "30 8 * * *",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Review open tasks",
                    "todos",
                    "Pull open tasks and deadlines.",
                ),
                create_step(
                    2,
                    "Pick the top three",
                    "gaia",
                    "Pick the three that matter most and order them.",
                ),
            ],
        },
        {
            "title": "Focus Time",
            "description": "Every morning, block out uninterrupted time for your most important work.",
            "icon": "Timer01Icon",
            "icon_color": "#72a3fe",
            "prompt": (
                "Every weekday at 9am, look at my calendar and open tasks, "
                "then block 90 minutes of focus time today for the most "
                "important thing I need to do."
            ),
            "categories": ["Focus & planning"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 9 * * 1-5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Find the most important task",
                    "todos",
                    "Pick the highest-priority task for today.",
                ),
                create_step(
                    2,
                    "Block focus time",
                    "googlecalendar",
                    "Create a 90-minute calendar block for it.",
                ),
            ],
        },
        {
            "title": "Nightly Review",
            "description": "Every evening, review what got done and set up tomorrow's list.",
            "icon": "Moon01Icon",
            "icon_color": "#ad8dfe",
            "prompt": (
                "Every evening at 9pm, review what I completed today, note "
                "anything left undone, and prepare tomorrow's task list."
            ),
            "categories": ["Focus & planning"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 21 * * *",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Review today",
                    "todos",
                    "Check what was completed and what remains.",
                ),
                create_step(
                    2,
                    "Prepare tomorrow",
                    "todos",
                    "Set up tomorrow's task list.",
                ),
            ],
        },
    ]


def get_dev_workflows() -> list[dict[str, Any]]:
    return [
        {
            "title": "Weekly Work Summary",
            "description": "Every Friday, a summary of what you shipped this week, ready to paste into your team chat.",
            "icon": "GitCommitIcon",
            "icon_color": "#72a3fe",
            "prompt": (
                "Every Friday at 4pm, review my commits, merged pull requests, "
                "and completed tasks this week, and write a short summary I "
                "can paste into my team chat."
            ),
            "categories": ["Dev", "featured"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 16 * * 5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Gather this week's work",
                    "github",
                    "Collect commits and merged pull requests.",
                ),
                create_step(
                    2,
                    "Check completed tasks",
                    "todos",
                    "Collect tasks completed this week.",
                ),
                create_step(
                    3,
                    "Write the summary",
                    "documents",
                    "Write a short summary ready to paste into team chat.",
                ),
            ],
        },
        {
            "title": "Code Review Reminders",
            "description": "When a teammate asks you to review code, GAIA keeps reminding you until it's done.",
            "icon": "GitBranchIcon",
            "icon_color": "#ad8dfe",
            "prompt": (
                "Whenever I'm assigned a pull request, add it to my reminders "
                "and keep surfacing it until I've reviewed it."
            ),
            "categories": ["Dev"],
            "trigger_config": {
                "type": "integration",
                "enabled": True,
                "trigger_name": "github_pr_event",
                "trigger_data": {"trigger_name": "github_pr_event", "repos": []},
            },
            "steps": [
                create_step(
                    1,
                    "Track assigned PRs",
                    "github",
                    "Track pull requests assigned to me.",
                ),
                create_step(
                    2,
                    "Keep surfacing the reminder",
                    "reminders",
                    "Add it to reminders and keep resurfacing until reviewed.",
                ),
            ],
        },
        {
            "title": "Save the Bug",
            "description": "Describe a bug once; GAIA files it as a tracked issue, so nothing gets lost.",
            "icon": "Bug01Icon",
            "icon_color": "#ff726b",
            "prompt": (
                "Whenever I describe a bug, file it as a GitHub issue with a "
                "clear title, repro steps, and any error text I gave you."
            ),
            "categories": ["Dev"],
            "trigger_config": {
                "type": "manual",
                "enabled": True,
            },
            "steps": [
                create_step(
                    1,
                    "File the issue",
                    "github",
                    "Create a GitHub issue with title and repro steps.",
                ),
            ],
        },
    ]


def get_health_workflows() -> list[dict[str, Any]]:
    return [
        {
            "title": "Drink Water Reminder",
            "description": "Gentle hydration nudges all day, no apps needed.",
            "icon": "RainIcon",
            "icon_color": "#09b7dc",
            "prompt": (
                "Every two hours between 8am and 10pm, send me a friendly "
                "reminder to drink water. Keep it short and vary the wording "
                "so it doesn't get annoying."
            ),
            "categories": ["Health & habits"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 8-22/2 * * *",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Send the reminder",
                    "reminders",
                    "Send a short, friendly hydration nudge.",
                ),
            ],
        },
        {
            "title": "Weekly Productivity Check-in",
            "description": "Review your wins every Friday, so the week doesn't blur past.",
            "icon": "ChampionIcon",
            "icon_color": "#eebe0c",
            "prompt": (
                "Every Friday at 5pm, review what I completed this week, "
                "celebrate the wins, and ask me one question: what's the one "
                "thing I want to carry into next week?"
            ),
            "categories": ["Health & habits"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "0 17 * * 5",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Review the week",
                    "todos",
                    "Collect what was completed this week.",
                ),
                create_step(
                    2,
                    "Write the check-in",
                    "gaia",
                    "Summarize the wins and ask the carry-over question.",
                ),
            ],
        },
        {
            "title": "Nightly Gratitude",
            "description": "A 9pm moment to note what went well today.",
            "icon": "SmileIcon",
            "icon_color": "#fb6ca0",
            "prompt": (
                "Every evening at 9:30pm, ask me what went well today and save "
                "it to memory, so I can look back on the good days."
            ),
            "categories": ["Health & habits"],
            "trigger_config": {
                "type": "schedule",
                "cron_expression": "30 21 * * *",
                "timezone": "UTC",
            },
            "steps": [
                create_step(
                    1,
                    "Save the note",
                    "memory",
                    "Ask what went well and save it to memory.",
                ),
            ],
        },
    ]


# Presentation for the built-in cards. Everything else about them — title,
# description, prompt, steps, trigger — is read from the system-workflow
# definitions so the explore card can never drift from what gets provisioned.
SYSTEM_WORKFLOW_PRESENTATION: dict[str, dict[str, Any]] = {
    "gmail:email_intelligence": {
        "icon": "InboxIcon",
        "icon_color": "#ff726b",
        "categories": ["Email", "featured"],
    },
    "gmail:smart_reply_drafts": {
        "icon": "MailSend01Icon",
        "icon_color": "#f68001",
        "categories": ["Email"],
    },
    "calendar:meeting_prep": {
        "icon": "UserGroupIcon",
        "icon_color": "#09b7dc",
        "categories": ["Meetings", "featured"],
    },
    "calendar:meeting_reminder": {
        "icon": "AlarmClockIcon",
        "icon_color": "#72a3fe",
        "categories": ["Meetings"],
    },
}


def get_system_workflows() -> list[dict[str, Any]]:
    """The auto-provisioned workflows, as explore cards.

    Same definitions the provisioner uses, so the card shows exactly what a user
    gets when they connect the integration. The ``system_workflow_key`` rides
    along to the client, which is what stops "add this" from creating a second
    copy of one the user already has.
    """
    configs: list[dict[str, Any]] = []
    for key, factory in [*GMAIL_SYSTEM_WORKFLOWS, *CALENDAR_SYSTEM_WORKFLOWS]:
        request = factory()
        presentation = SYSTEM_WORKFLOW_PRESENTATION[key]
        configs.append(
            {
                "title": request.title,
                "description": request.description,
                "prompt": request.prompt,
                "trigger_config": request.trigger_config.model_dump(mode="json"),
                "steps": [
                    {
                        "id": step.id,
                        "title": step.title,
                        "category": step.category,
                        "description": step.description,
                    }
                    for step in (request.steps or [])
                ],
                "is_system_workflow": True,
                "source_integration": request.source_integration,
                "system_workflow_key": key,
                **presentation,
            }
        )
    return configs


# Display run counts for the seeded library. Deterministic so re-seeding is
# stable, and scaled by how broadly each flow applies rather than uniformly.
DISPLAY_RUN_COUNTS: dict[str, int] = {
    # Built-ins — provisioned for everyone who connects the integration.
    "Inbox Triage": 8420,
    "Auto-Draft Replies": 6180,
    "Meeting Briefing": 5740,
    "Meeting Reminder": 7310,
    # Broad daily habits.
    "Morning Briefing": 7860,
    "Morning Priority Map": 5230,
    "Nightly Review": 4180,
    "Focus Time": 3940,
    "Drink Water Reminder": 6420,
    "Nightly Gratitude": 2780,
    "Weekly Productivity Check-in": 3120,
    # Email.
    "Follow-up Reminders": 5610,
    "Monthly Subscription Audit": 4470,
    "Add Deadlines to Calendar": 3860,
    "Email to Task": 3290,
    # Meetings.
    "Post-meeting Follow-ups": 3410,
    "Meeting Notes Summary": 2960,
    "Meeting Prep": 2540,
    # Home admin.
    "Rent Reminder": 4020,
    "Weekly Meal Plan": 2870,
    "Birthday Gift Ideas": 2210,
    # Content.
    "Weekly Content Ideas": 2640,
    "Social Post Drafts": 2380,
    "Research to Outline": 3070,
    "Competitor Watch": 1980,
    # Dev.
    "Weekly Work Summary": 2450,
    "Code Review Reminders": 2130,
    "Save the Bug": 1740,
    # Study.
    "Assignment Tracker": 3580,
    "Study Plan Today": 2690,
    "Lecture Notes Summarizer": 2340,
    "Exam Revision Pack": 1860,
}


def apply_display_run_counts(configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stamp each config with its display run count (successes at ~96%)."""
    for config in configs:
        total = DISPLAY_RUN_COUNTS.get(config["title"], 0)
        config["total_executions"] = total
        config["successful_executions"] = round(total * 0.96)
    return configs


def get_all_workflows() -> list[dict[str, Any]]:
    """Combine all workflow categories."""
    all_workflows = []
    all_workflows.extend(get_system_workflows())
    all_workflows.extend(get_study_workflows())
    all_workflows.extend(get_email_workflows())
    all_workflows.extend(get_meetings_workflows())
    all_workflows.extend(get_home_admin_workflows())
    all_workflows.extend(get_content_workflows())
    all_workflows.extend(get_focus_workflows())
    all_workflows.extend(get_dev_workflows())
    all_workflows.extend(get_health_workflows())
    return apply_display_run_counts(all_workflows)


def create_workflow_document(config: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Create a workflow document ready for MongoDB insertion."""
    workflow_id = f"wf_{uuid.uuid4().hex[:12]}"

    trigger_type = TriggerType(config["trigger_config"]["type"])
    trigger_config = TriggerConfig(
        type=trigger_type,
        enabled=config["trigger_config"].get("enabled", True),
        cron_expression=config["trigger_config"].get("cron_expression"),
        timezone=config["trigger_config"].get("timezone", "UTC"),
        trigger_name=config["trigger_config"].get("trigger_name"),
        trigger_data=config["trigger_config"].get("trigger_data"),
    )

    if trigger_config.type == TriggerType.SCHEDULE and trigger_config.cron_expression:
        trigger_config.update_next_run()

    steps = []
    for step_config in config["steps"]:
        step = WorkflowStep(**step_config)
        steps.append(step.model_dump(mode="json"))

    now = datetime.now(UTC)

    return {
        "_id": workflow_id,
        "id": workflow_id,
        "user_id": user_id,
        "title": config["title"],
        "description": config["description"],
        "icon": config["icon"],
        "icon_color": config["icon_color"],
        # Set only on the built-in cards (see get_system_workflows). Carrying the
        # key through the explore payload is what lets "add this" resolve to the
        # workflow the user was already provisioned instead of duplicating it.
        "is_system_workflow": config.get("is_system_workflow", False),
        "source_integration": config.get("source_integration"),
        "system_workflow_key": config.get("system_workflow_key"),
        "prompt": config.get("prompt", ""),
        "slug": slugify(config["title"]),
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
    except Exception:
        print("⚠️  Could not read existing explore workflows, skipping backup")
        return ""

    if not existing:
        print("ℹ️  No existing explore workflows to back up")
        return ""

    await asyncio.to_thread(_write_backup_file, backup_file, existing)
    print(f"💾 Backup created: {backup_file}")
    return backup_file


def _write_backup_file(backup_file: str, existing: list[dict[str, Any]]) -> None:
    """Write the backup JSON synchronously (called from async context)."""
    with open(backup_file, "w") as f:
        json.dump(existing, f, indent=2, default=str)


async def seed_explore_workflows(
    dry_run: bool = False,
    force: bool = False,
    backup: bool = True,
    user_id: str = "system",
    prune: bool = False,
) -> None:
    """Seed the workflows collection with explore workflows."""
    print("🚀 Starting explore workflows seeding...")

    workflow_configs = get_all_workflows()
    curated_slugs = {slugify(config["title"]) for config in workflow_configs}

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

    if prune:
        old_docs = await workflows_collection.find(
            {"is_explore": True, "slug": {"$nin": list(curated_slugs)}}
        ).to_list(length=None)
        print(f"\n🗑️  Prune would remove {len(old_docs)} explore workflows not in the curated set:")
        for doc in old_docs:
            print(f"   • {doc.get('slug', '?')}")

    if dry_run:
        print("\n🔍 DRY RUN - No changes applied.")
        return

    if not force:
        response = await asyncio.to_thread(
            input, f"\n❓ Seed {len(workflow_configs)} explore workflows? (y/N): "
        )
        if response.lower() != "y":
            print("❌ Cancelled.")
            return

    if backup:
        await create_backup()

    print("\n🔄 Upserting workflows (delete + insert by slug)...")

    for config in workflow_configs:
        slug = slugify(config["title"])
        await workflows_collection.delete_many({"slug": slug, "is_explore": True})

    docs = [create_workflow_document(config, user_id) for config in workflow_configs]
    if docs:
        result = await workflows_collection.insert_many(docs)
        print(f"🎉 Seeded {len(result.inserted_ids)} workflows")

    if prune:
        deleted = await workflows_collection.delete_many(
            {"is_explore": True, "slug": {"$nin": list(curated_slugs)}}
        )
        print(f"🗑️  Pruned {deleted.deleted_count} non-curated explore workflows")

    final_explore = await workflows_collection.count_documents({"is_explore": True})
    final_total = await workflows_collection.count_documents({})

    print("\n📊 Final State:")
    print(f"   📄 Total workflows: {final_total}")
    print(f"   🔍 Explore workflows: {final_explore}")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Seed explore/discover workflows for GAIA (outcome-first curated set)",
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
        "--prune",
        action="store_true",
        help="Delete explore workflows not in the curated set",
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
            prune=args.prune,
        )
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
