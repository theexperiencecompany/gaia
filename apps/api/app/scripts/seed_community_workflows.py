"""
Seed high-quality community workflows for specified users.
Run with: cd apps/api && uv run python -m app.scripts.seed_community_workflows

Options:
    --force     Overwrite existing workflows with matching titles
    --dry-run   Print what would be seeded without writing to DB
"""

import argparse
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from shared.py.wide_events import log
from app.db.mongodb.collections import users_collection, workflows_collection
from shared.py.utils.slugify import slugify

# Emails of users who will own the seeded workflows
SEED_USER_EMAILS = [
    "aryanranderiya1478@gmail.com",
    "dhruvmaradiya0@gmail.com",
    "s.aryan.randeriya@gmail.com",
    "45vinitthakkar@gmail.com",
]

# ---------------------------------------------------------------------------
# Workflow definitions
# ---------------------------------------------------------------------------

COMMUNITY_WORKFLOWS: list[dict[str, Any]] = [
    {
        "title": "Daily Morning Brief",
        "description": (
            "Aggregates your emails, calendar events, and todos each morning into "
            "a concise digest so you start the day fully informed."
        ),
        "prompt": (
            "Fetch the user's unread emails from the last 12 hours and summarise the "
            "top 5 by urgency. Then pull today's calendar events and list them in "
            "chronological order. Finally, retrieve all incomplete high-priority todos "
            "and surface any that are overdue. Combine everything into a clean morning "
            "brief with three clearly labelled sections: Emails, Calendar, and Tasks. "
            "If any section is empty, say so. Do not include full email bodies — "
            "subject and sender only. Send the brief as a chat message."
        ),
        "trigger_config": {
            "type": "schedule",
            "enabled": True,
            "cron_expression": "0 8 * * 1-5",
            "timezone": "UTC",
        },
        "steps": [
            {
                "title": "Fetch unread emails",
                "category": "gmail",
                "description": "Retrieve unread emails from the last 12 hours and rank by urgency.",
            },
            {
                "title": "Pull today's calendar events",
                "category": "googlecalendar",
                "description": "List all calendar events scheduled for today in chronological order.",
            },
            {
                "title": "Retrieve high-priority todos",
                "category": "todos",
                "description": "Get all incomplete high-priority todos, flagging any overdue items.",
            },
            {
                "title": "Compose and send morning brief",
                "category": "general",
                "description": "Combine emails, events, and tasks into a clean three-section digest.",
            },
        ],
        "use_case_categories": ["featured", "productivity", "email"],
    },
    {
        "title": "Smart Meeting Prep",
        "description": (
            "Thirty minutes before each calendar meeting, researches attendees and "
            "summarises the agenda so you walk in prepared."
        ),
        "prompt": (
            "Thirty minutes before the next calendar event that has external attendees, "
            "look up each attendee's name and organisation using web search. Retrieve "
            "the meeting agenda from the event description. Summarise the key discussion "
            "points and any open action items from the previous meeting with the same "
            "attendees if one exists. Present a concise prep note: who will be there, "
            "what the meeting is about, and any background context worth knowing."
        ),
        "trigger_config": {
            "type": "integration",
            "enabled": True,
            "trigger_name": "GOOGLECALENDAR_EVENT_START",
        },
        "steps": [
            {
                "title": "Detect upcoming meeting",
                "category": "googlecalendar",
                "description": "Identify the next calendar event with external attendees within 30 minutes.",
            },
            {
                "title": "Research attendees",
                "category": "search",
                "description": "Look up each attendee's name, role, and organisation via web search.",
            },
            {
                "title": "Extract agenda from event",
                "category": "googlecalendar",
                "description": "Parse the event description for discussion points and goals.",
            },
            {
                "title": "Send prep summary",
                "category": "general",
                "description": "Deliver a concise meeting prep note with attendee context and agenda.",
            },
        ],
        "use_case_categories": ["featured", "productivity", "calendar"],
    },
    {
        "title": "Invoice and Receipt Tracker",
        "description": (
            "Monitors Gmail for invoices and receipts, then logs key details "
            "to a Google Sheet for effortless expense tracking."
        ),
        "prompt": (
            "Scan the Gmail inbox for any new emails containing invoices or receipts "
            "received in the last 24 hours. For each one, extract the vendor name, "
            "date, amount, and currency. Log each extracted record as a new row in the "
            "designated Google Sheet (column order: Date, Vendor, Amount, Currency, "
            "Email Subject). If the sheet does not exist, create it with those headers. "
            "After logging, reply with a summary of how many records were added today."
        ),
        "trigger_config": {
            "type": "schedule",
            "enabled": True,
            "cron_expression": "0 20 * * *",
            "timezone": "UTC",
        },
        "steps": [
            {
                "title": "Scan Gmail for invoices",
                "category": "gmail",
                "description": "Search for emails with invoice or receipt content in the last 24 hours.",
            },
            {
                "title": "Extract invoice details",
                "category": "general",
                "description": "Parse vendor, date, amount, and currency from each matching email.",
            },
            {
                "title": "Log to Google Sheets",
                "category": "googlesheets",
                "description": "Append one row per invoice to the expense-tracking spreadsheet.",
            },
            {
                "title": "Report results",
                "category": "general",
                "description": "Summarise how many invoices were logged in this run.",
            },
        ],
        "use_case_categories": ["featured", "finance", "email"],
    },
    {
        "title": "Competitive Intelligence Weekly",
        "description": (
            "Searches the web for competitor news every week and delivers a "
            "structured digest straight to your inbox."
        ),
        "prompt": (
            "Search the web for recent news and announcements about the user's key "
            "competitors from the past seven days. Group findings by competitor. For "
            "each item include the headline, source, date, and a one-sentence summary. "
            "Highlight anything that signals a product launch, pricing change, "
            "partnership, or funding event. Format the output as a competitive "
            "intelligence digest and send it as a chat message. If no notable news is "
            "found for a competitor, skip that section."
        ),
        "trigger_config": {
            "type": "schedule",
            "enabled": True,
            "cron_expression": "0 9 * * 1",
            "timezone": "UTC",
        },
        "steps": [
            {
                "title": "Search for competitor news",
                "category": "search",
                "description": "Run web searches for each competitor, scoped to the past 7 days.",
            },
            {
                "title": "Filter and rank results",
                "category": "general",
                "description": "Keep product launches, pricing changes, partnerships, and funding news.",
            },
            {
                "title": "Compose digest",
                "category": "general",
                "description": "Group findings by competitor and write a one-sentence summary per item.",
            },
            {
                "title": "Deliver weekly report",
                "category": "general",
                "description": "Send the competitive intelligence digest as a chat message.",
            },
        ],
        "use_case_categories": ["featured", "research", "productivity"],
    },
    {
        "title": "GitHub PR Review Assistant",
        "description": (
            "Checks your open GitHub pull requests daily and surfaces a clear "
            "review-status summary so nothing falls through the cracks."
        ),
        "prompt": (
            "Retrieve all open pull requests across the user's GitHub repositories. "
            "For each PR, record the title, repository, author, number of review "
            "comments, approval status (approved / changes requested / pending), and "
            "time open. Group PRs into three buckets: Waiting for your review, "
            "Waiting for others to review, and Blocked (changes requested). Present "
            "the summary with actionable next steps for each bucket. If there are no "
            "open PRs, say so and stop."
        ),
        "trigger_config": {
            "type": "schedule",
            "enabled": True,
            "cron_expression": "0 9 * * 1-5",
            "timezone": "UTC",
        },
        "steps": [
            {
                "title": "Fetch open pull requests",
                "category": "github",
                "description": "List all open PRs across all accessible repositories.",
            },
            {
                "title": "Collect review status",
                "category": "github",
                "description": "For each PR, get approval status, comments, and time since opening.",
            },
            {
                "title": "Bucket PRs by action needed",
                "category": "general",
                "description": "Group into: needs your review, waiting on others, and blocked.",
            },
            {
                "title": "Send review summary",
                "category": "general",
                "description": "Present the bucketed list with actionable next steps per group.",
            },
        ],
        "use_case_categories": ["featured", "developer", "productivity"],
    },
    {
        "title": "Travel Expense Logger",
        "description": (
            "Extracts travel receipts from email automatically and categorises "
            "them into your expense spreadsheet for easy reimbursement."
        ),
        "prompt": (
            "Search Gmail for any emails containing flight, hotel, rental car, or "
            "transport receipts received in the last 48 hours. For each receipt, "
            "extract: vendor, travel date, expense category (Flight / Hotel / "
            "Ground Transport / Meals / Other), amount, and currency. Append each "
            "record as a new row to the travel-expenses Google Sheet. If the sheet "
            "does not exist, create it with headers: Date, Vendor, Category, Amount, "
            "Currency. Send a confirmation message listing what was logged."
        ),
        "trigger_config": {
            "type": "schedule",
            "enabled": True,
            "cron_expression": "0 22 * * *",
            "timezone": "UTC",
        },
        "steps": [
            {
                "title": "Scan Gmail for travel receipts",
                "category": "gmail",
                "description": "Find emails with flight, hotel, rental car, or transport receipts.",
            },
            {
                "title": "Extract expense details",
                "category": "general",
                "description": "Parse vendor, date, category, amount, and currency from each email.",
            },
            {
                "title": "Append to expense sheet",
                "category": "googlesheets",
                "description": "Log each expense as a new row in the travel-expenses spreadsheet.",
            },
            {
                "title": "Confirm logged expenses",
                "category": "general",
                "description": "Send a message listing all records added in this run.",
            },
        ],
        "use_case_categories": ["featured", "finance", "travel"],
    },
    {
        "title": "Content Calendar Planner",
        "description": (
            "Suggests a week of content ideas every Monday based on trending topics "
            "in your niche so you never face a blank content calendar."
        ),
        "prompt": (
            "Search the web for trending topics and discussions in the user's niche "
            "from the past week. Generate seven content ideas — one per day — that "
            "are timely, specific, and actionable. For each idea include a suggested "
            "post format (short-form video, article, thread, carousel, etc.), a "
            "working title, and a two-sentence description of what to cover. Present "
            "the calendar in a table: Day, Format, Title, Description. Bias toward "
            "ideas with high engagement potential based on what is currently trending."
        ),
        "trigger_config": {
            "type": "schedule",
            "enabled": True,
            "cron_expression": "0 7 * * 1",
            "timezone": "UTC",
        },
        "steps": [
            {
                "title": "Research trending topics",
                "category": "search",
                "description": "Search for viral content and discussions in the user's niche this week.",
            },
            {
                "title": "Generate content ideas",
                "category": "general",
                "description": "Create seven distinct, timely content ideas with formats and titles.",
            },
            {
                "title": "Deliver content calendar",
                "category": "general",
                "description": "Present a seven-day table with day, format, title, and description.",
            },
        ],
        "use_case_categories": ["featured", "marketing", "creativity"],
    },
    {
        "title": "Customer Feedback Aggregator",
        "description": (
            "Collects feedback from emails and mentions weekly, then delivers a "
            "structured summary highlighting themes and urgent issues."
        ),
        "prompt": (
            "Search Gmail for emails containing customer feedback, complaints, or "
            "feature requests received in the last seven days. Also search the web "
            "for any public mentions, reviews, or social posts about the user's "
            "product or brand from the same period. Cluster all feedback into "
            "themes (e.g. Performance, UX, Missing Feature, Billing, Support). "
            "Count occurrences per theme. Flag any feedback that signals urgency "
            "or churn risk. Output a weekly feedback digest with: theme breakdown, "
            "top quotes per theme, and a list of urgent items to address."
        ),
        "trigger_config": {
            "type": "schedule",
            "enabled": True,
            "cron_expression": "0 8 * * 5",
            "timezone": "UTC",
        },
        "steps": [
            {
                "title": "Collect email feedback",
                "category": "gmail",
                "description": "Retrieve customer emails with feedback, complaints, or requests from the past week.",
            },
            {
                "title": "Search public mentions",
                "category": "search",
                "description": "Find public reviews and social mentions of the product from the past week.",
            },
            {
                "title": "Cluster into themes",
                "category": "general",
                "description": "Group all feedback into named themes and count occurrences.",
            },
            {
                "title": "Deliver feedback digest",
                "category": "general",
                "description": "Send a weekly summary with theme breakdown, top quotes, and urgent items.",
            },
        ],
        "use_case_categories": ["featured", "productivity", "research"],
    },
    {
        "title": "Unsubscribe From Marketing Emails",
        "description": (
            "Scans your inbox for marketing and promotional emails and helps you "
            "unsubscribe from lists that clutter your inbox."
        ),
        "prompt": (
            "Scan the Gmail inbox and identify emails that appear to be marketing "
            "or promotional in nature — look for unsubscribe links, bulk-sender "
            "headers, and promotional language. Group them by sender domain. For "
            "each sender, report: how many emails have been received in the last "
            "30 days, the most recent subject line, and whether an unsubscribe link "
            "was found. Present the grouped list ordered by email volume descending. "
            "Ask the user which senders to unsubscribe from, then follow the "
            "unsubscribe link for each confirmed sender."
        ),
        "trigger_config": {
            "type": "manual",
            "enabled": True,
        },
        "steps": [
            {
                "title": "Identify marketing emails",
                "category": "gmail",
                "description": "Scan inbox for bulk senders, promotional headers, and unsubscribe links.",
            },
            {
                "title": "Group by sender domain",
                "category": "general",
                "description": "Cluster emails by sender and count volume over the last 30 days.",
            },
            {
                "title": "Present unsubscribe list",
                "category": "general",
                "description": "Show senders ranked by email volume with unsubscribe link availability.",
            },
            {
                "title": "Execute unsubscribes",
                "category": "gmail",
                "description": "Follow unsubscribe links for senders confirmed by the user.",
            },
        ],
        "use_case_categories": ["featured", "email", "productivity"],
    },
    {
        "title": "Task Overdue Alert",
        "description": (
            "Checks your todos every morning and sends a focused reminder of "
            "everything overdue so urgent tasks never slip past you."
        ),
        "prompt": (
            "Retrieve all incomplete todos that have a due date earlier than today. "
            "Sort them by how many days overdue they are (most overdue first). For "
            "each overdue task include: title, original due date, days overdue, and "
            "priority level. Group into three urgency buckets: Critical (7+ days "
            "overdue or high priority), Overdue (1-6 days), and Due Today. Send the "
            "alert as a chat message with the count per bucket in the heading. If "
            "nothing is overdue, send a brief positive confirmation instead."
        ),
        "trigger_config": {
            "type": "schedule",
            "enabled": True,
            "cron_expression": "0 8 * * *",
            "timezone": "UTC",
        },
        "steps": [
            {
                "title": "Fetch overdue todos",
                "category": "todos",
                "description": "Retrieve all incomplete todos with due dates before today.",
            },
            {
                "title": "Sort and bucket by urgency",
                "category": "general",
                "description": "Group into Critical, Overdue, and Due Today by days past due and priority.",
            },
            {
                "title": "Send overdue alert",
                "category": "general",
                "description": "Deliver the bucketed overdue task list or a positive confirmation if clear.",
            },
        ],
        "use_case_categories": ["featured", "productivity", "todos"],
    },
]


# ---------------------------------------------------------------------------
# Slug generation (lightweight, no service dependency)
# ---------------------------------------------------------------------------


async def _generate_unique_slug(title: str) -> str:
    """Generate a unique slug for a public workflow, appending suffix if needed."""
    base = slugify(title)
    candidate = base
    suffix = 1
    while True:
        existing = await workflows_collection.find_one(
            {"slug": candidate, "is_public": True}
        )
        if not existing:
            return candidate
        candidate = f"{base}-{suffix}"
        suffix += 1


# ---------------------------------------------------------------------------
# Core seeding logic
# ---------------------------------------------------------------------------


async def _lookup_user_ids(emails: list[str]) -> dict[str, str]:
    """Return a mapping of email -> user _id (as str) for found users."""
    mapping: dict[str, str] = {}
    for email in emails:
        user = await users_collection.find_one({"email": email}, {"_id": 1})
        if user:
            mapping[email] = str(user["_id"])
        else:
            log.warning(f"[seed_workflows] User not found for email: {email}")
    return mapping


async def _seed_workflow_for_user(
    workflow_def: dict[str, Any],
    user_id: str,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> bool:
    """
    Seed a single workflow for a single user.

    Returns True if a new document was inserted, False if skipped or dry-run.
    """
    title = workflow_def["title"]

    # Idempotency check: skip if a matching workflow already exists for this user
    existing = await workflows_collection.find_one(
        {"title": title, "user_id": user_id, "is_public": True}
    )
    if existing and not force:
        log.info(f"[seed_workflows] Already exists, skipping: '{title}' for {user_id}")
        return False

    if dry_run:
        log.info(f"[seed_workflows] [DRY RUN] Would seed: '{title}' for {user_id}")
        return False

    now = datetime.now(timezone.utc)
    workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
    slug = await _generate_unique_slug(title)

    trigger_raw = workflow_def["trigger_config"]
    trigger_config: dict[str, Any] = {
        "type": trigger_raw["type"],
        "enabled": trigger_raw.get("enabled", True),
        "trigger_name": trigger_raw.get("trigger_name"),
        "cron_expression": trigger_raw.get("cron_expression"),
        "timezone": trigger_raw.get("timezone", "UTC"),
        "next_run": None,
        "composio_trigger_ids": None,
        "trigger_data": None,
    }

    steps_raw = workflow_def.get("steps", [])
    steps: list[dict[str, Any]] = [
        {
            "id": f"step_{uuid.uuid4().hex[:8]}",
            "title": s["title"],
            "category": s["category"],
            "description": s["description"],
        }
        for s in steps_raw
    ]

    doc: dict[str, Any] = {
        "_id": workflow_id,
        "id": workflow_id,
        "user_id": user_id,
        "title": title,
        "description": workflow_def["description"],
        "prompt": workflow_def["prompt"],
        "steps": steps,
        "trigger_config": trigger_config,
        "activated": True,
        "is_public": True,
        "is_explore": True,
        "slug": slug,
        "created_by": user_id,
        "status": "scheduled",
        "occurrence_count": 0,
        "total_executions": 0,
        "successful_executions": 0,
        "is_todo_workflow": False,
        "is_system_workflow": False,
        "current_step_index": 0,
        "execution_logs": [],
        "error_message": None,
        "last_executed_at": None,
        "source_todo_id": None,
        "source_integration": None,
        "system_workflow_key": None,
        "scheduled_at": now.isoformat(),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "use_case_categories": workflow_def.get("use_case_categories", ["featured"]),
    }

    if existing and force:
        await workflows_collection.delete_one({"_id": existing["_id"]})
        log.info(f"[seed_workflows] Deleted existing: '{title}' for {user_id} (force)")

    result = await workflows_collection.insert_one(doc)
    if result.inserted_id:
        log.info(f"[seed_workflows] Seeded: '{title}' (id={workflow_id}) for {user_id}")
        return True

    log.warning(f"[seed_workflows] Insert returned no ID for '{title}' / {user_id}")
    return False


async def seed_community_workflows(
    force: bool = False,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Seed all community workflows for all target users.

    Returns:
        (seeded_count, skipped_count)
    """
    log.info("[seed_workflows] Starting community workflow seeding")

    user_map = await _lookup_user_ids(SEED_USER_EMAILS)
    if not user_map:
        log.warning("[seed_workflows] No target users found — aborting")
        return 0, 0

    log.info(f"[seed_workflows] Found {len(user_map)} target user(s)")

    seeded = 0
    skipped = 0

    for workflow_def in COMMUNITY_WORKFLOWS:
        for email, user_id in user_map.items():
            inserted = await _seed_workflow_for_user(
                workflow_def, user_id, force=force, dry_run=dry_run
            )
            if inserted:
                seeded += 1
            else:
                skipped += 1

    action = "Would seed" if dry_run else "Seeded"
    log.info(f"[seed_workflows] {action} {seeded} workflow(s), skipped {skipped}")
    return seeded, skipped


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed high-quality community workflows for target users"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete and re-insert existing workflows with matching titles",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be seeded without writing to the database",
    )
    args = parser.parse_args()

    seeded, skipped = await seed_community_workflows(
        force=args.force,
        dry_run=args.dry_run,
    )

    mode_label = "[DRY RUN] " if args.dry_run else ""
    print(f"{mode_label}Seeded {seeded} workflow(s), skipped {skipped}.")
    if args.dry_run:
        print("Re-run without --dry-run to write to the database.")


if __name__ == "__main__":
    asyncio.run(main())
