#!/usr/bin/env python3
"""
Enhanced seed script to manage workflows collection with public use cases.

This script handles:
- Adding sample workflows with realistic use cases
- Creating public workflows for community use
- Setting up workflows with proper categorization
- Maintaining data integrity and providing detailed logging

IMPORTANT: Run this script from the correct directory!

1. If running locally:
   cd /path/to/your/gaia/backend
   python scripts/seed_workflows.py

2. If running inside Docker container:
   cd /app
   python scripts/seed_workflows.py

3. Alternative Docker approach (set PYTHONPATH):
   PYTHONPATH=/app python scripts/seed_workflows.py

4. Run as module (from app directory):
   python -m scripts.seed_workflows

Usage flags:
--dry-run: Show what changes would be made without applying them
--force: Skip confirmation prompts
--backup: Create a backup before making changes
--user-id: Specify user ID for workflows (default: system)
"""

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import (
    TriggerConfig,
    WorkflowStep,
    Workflow,
)


def get_public_workflows_configuration(user_id: str = "system") -> List[Dict[str, Any]]:
    """
    Define public use case workflows that should be available in the community marketplace.
    These are realistic, practical workflows that users can benefit from.
    """
    return [
        # Email Management Workflows
        {
            "title": "Daily Email Digest",
            "description": "Get a summary of important emails from the last 24 hours and organize your inbox",
            "user_id": user_id,
            "is_public": True,
            "steps": [
                {
                    "id": "step_1",
                    "title": "Fetch Recent Important Emails",
                    "tool_name": "search_gmail_messages",
                    "tool_category": "mail",
                    "description": "Search for unread emails from the last 24 hours with high importance",
                    "tool_inputs": {
                        "query": "is:unread newer_than:1d",
                        "max_results": 20,
                    },
                    "order": 0,
                },
                {
                    "id": "step_2",
                    "title": "Create Daily Task List",
                    "tool_name": "create_todo",
                    "tool_category": "todos",
                    "description": "Create todos for emails that require action",
                    "tool_inputs": {"title": "Process important emails from digest"},
                    "order": 1,
                },
            ],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 8 * * 1-5",  # 8 AM on weekdays
                "timezone": "UTC",
            },
            "total_executions": 45,
            "successful_executions": 42,
        },
        # Productivity Workflows
        {
            "title": "Weekly Planning Assistant",
            "description": "Review your calendar, create weekly goals, and set up priority tasks for the upcoming week",
            "user_id": user_id,
            "is_public": True,
            "steps": [
                {
                    "id": "step_1",
                    "title": "Review Upcoming Calendar Events",
                    "tool_name": "list_calendar_events",
                    "tool_category": "calendar",
                    "description": "Get all calendar events for the upcoming week",
                    "tool_inputs": {"days_ahead": 7},
                    "order": 0,
                },
                {
                    "id": "step_2",
                    "title": "Create Weekly Goal",
                    "tool_name": "create_goal",
                    "tool_category": "goals",
                    "description": "Set up main objectives for the week",
                    "tool_inputs": {"title": "Weekly Focus Goals"},
                    "order": 1,
                },
                {
                    "id": "step_3",
                    "title": "Schedule Planning Time",
                    "tool_name": "create_calendar_event",
                    "tool_category": "calendar",
                    "description": "Block time for weekly planning and review",
                    "tool_inputs": {"title": "Weekly Planning Session", "duration": 60},
                    "order": 2,
                },
            ],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 18 * * 5",  # 6 PM on Fridays
                "timezone": "UTC",
            },
            "total_executions": 67,
            "successful_executions": 61,
        },
        # Research Workflows
        {
            "title": "Topic Research & Documentation",
            "description": "Research a topic comprehensively and create organized documentation with key findings",
            "user_id": user_id,
            "is_public": True,
            "steps": [
                {
                    "id": "step_1",
                    "title": "Web Search for Topic",
                    "tool_name": "web_search_tool",
                    "tool_category": "search",
                    "description": "Search for comprehensive information on the specified topic",
                    "tool_inputs": {"query": "research topic", "num_results": 10},
                    "order": 0,
                },
                {
                    "id": "step_2",
                    "title": "Deep Research Analysis",
                    "tool_name": "deep_research_tool",
                    "tool_category": "research",
                    "description": "Conduct deep analysis and gather detailed information",
                    "tool_inputs": {
                        "topic": "research subject",
                        "depth": "comprehensive",
                    },
                    "order": 1,
                },
                {
                    "id": "step_3",
                    "title": "Create Research Notes",
                    "tool_name": "create_note",
                    "tool_category": "notes",
                    "description": "Organize findings into structured notes",
                    "tool_inputs": {
                        "title": "Research Findings",
                        "content": "Organized research results",
                    },
                    "order": 2,
                },
            ],
            "trigger_config": {"type": "manual", "enabled": True},
            "total_executions": 89,
            "successful_executions": 84,
        },
        # Meeting Management
        {
            "title": "Pre-Meeting Preparation",
            "description": "Automatically prepare for upcoming meetings by gathering context and creating action items",
            "user_id": user_id,
            "is_public": True,
            "steps": [
                {
                    "id": "step_1",
                    "title": "Get Today's Meetings",
                    "tool_name": "list_calendar_events",
                    "tool_category": "calendar",
                    "description": "Fetch all meetings scheduled for today",
                    "tool_inputs": {"days_ahead": 1},
                    "order": 0,
                },
                {
                    "id": "step_2",
                    "title": "Search Related Emails",
                    "tool_name": "search_gmail_messages",
                    "tool_category": "mail",
                    "description": "Find emails related to meeting participants and topics",
                    "tool_inputs": {"query": "meeting agenda", "max_results": 5},
                    "order": 1,
                },
                {
                    "id": "step_3",
                    "title": "Create Meeting Notes",
                    "tool_name": "create_note",
                    "tool_category": "notes",
                    "description": "Set up structured notes template for the meeting",
                    "tool_inputs": {"title": "Meeting Notes Template"},
                    "order": 2,
                },
            ],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 7 * * 1-5",  # 7 AM on weekdays
                "timezone": "UTC",
            },
            "total_executions": 63,
            "successful_executions": 60,
        },
        # Content Creation
        {
            "title": "Social Media Content Planning",
            "description": "Research trending topics and plan content for social media platforms",
            "user_id": user_id,
            "is_public": True,
            "steps": [
                {
                    "id": "step_1",
                    "title": "Research Trending Topics",
                    "tool_name": "web_search_tool",
                    "tool_category": "search",
                    "description": "Find current trending topics in your industry",
                    "tool_inputs": {
                        "query": "trending topics industry news",
                        "num_results": 15,
                    },
                    "order": 0,
                },
                {
                    "id": "step_2",
                    "title": "Create Content Ideas",
                    "tool_name": "create_note",
                    "tool_category": "notes",
                    "description": "Document content ideas based on trending topics",
                    "tool_inputs": {"title": "Social Media Content Ideas"},
                    "order": 1,
                },
                {
                    "id": "step_3",
                    "title": "Schedule Content Creation",
                    "tool_name": "create_todo",
                    "tool_category": "todos",
                    "description": "Create tasks for content creation and publishing",
                    "tool_inputs": {"title": "Create social media content"},
                    "order": 2,
                },
            ],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 9 * * 1",  # 9 AM on Mondays
                "timezone": "UTC",
            },
            "total_executions": 72,
            "successful_executions": 69,
        },
        # Email Management
        {
            "title": "Project Status Update",
            "description": "Gather project updates, create status reports, and plan next steps",
            "user_id": user_id,
            "is_public": True,
            "steps": [
                {
                    "id": "step_1",
                    "title": "Review Project Tasks",
                    "tool_name": "list_todos",
                    "tool_category": "todos",
                    "description": "Get overview of current project tasks and their status",
                    "tool_inputs": {"filter": "project"},
                    "order": 0,
                },
                {
                    "id": "step_2",
                    "title": "Create Status Report",
                    "tool_name": "create_note",
                    "tool_category": "notes",
                    "description": "Document project progress and current status",
                    "tool_inputs": {"title": "Weekly Project Status Report"},
                    "order": 1,
                },
                {
                    "id": "step_3",
                    "title": "Schedule Team Check-in",
                    "tool_name": "create_calendar_event",
                    "tool_category": "calendar",
                    "description": "Set up team meeting to discuss project progress",
                    "tool_inputs": {"title": "Project Team Check-in", "duration": 30},
                    "order": 2,
                },
            ],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 16 * * 3",  # 4 PM on Wednesdays
                "timezone": "UTC",
            },
            "total_executions": 94,
            "successful_executions": 89,
        },
        # Learning & Development
        {
            "title": "Daily Learning Routine",
            "description": "Research new topics in your field and create learning materials",
            "user_id": user_id,
            "is_public": True,
            "steps": [
                {
                    "id": "step_1",
                    "title": "Research Industry Updates",
                    "tool_name": "web_search_tool",
                    "tool_category": "search",
                    "description": "Find latest news and updates in your professional field",
                    "tool_inputs": {
                        "query": "industry updates technology news",
                        "num_results": 8,
                    },
                    "order": 0,
                },
                {
                    "id": "step_2",
                    "title": "Create Learning Notes",
                    "tool_name": "create_note",
                    "tool_category": "notes",
                    "description": "Document key learnings and insights",
                    "tool_inputs": {"title": "Daily Learning Notes"},
                    "order": 1,
                },
                {
                    "id": "step_3",
                    "title": "Set Learning Goal",
                    "tool_name": "create_goal",
                    "tool_category": "goals",
                    "description": "Create specific learning objective based on findings",
                    "tool_inputs": {"title": "Today's Learning Objective"},
                    "order": 2,
                },
            ],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 10 * * 1-5",  # 10 AM on weekdays
                "timezone": "UTC",
            },
            "total_executions": 134,
            "successful_executions": 127,
        },
        # Health & Wellness
        {
            "title": "Weekly Wellness Check",
            "description": "Plan wellness activities and track health goals for the week",
            "user_id": user_id,
            "is_public": True,
            "steps": [
                {
                    "id": "step_1",
                    "title": "Schedule Exercise Time",
                    "tool_name": "create_calendar_event",
                    "tool_category": "calendar",
                    "description": "Block time for physical exercise activities",
                    "tool_inputs": {"title": "Exercise Session", "duration": 60},
                    "order": 0,
                },
                {
                    "id": "step_2",
                    "title": "Create Wellness Goals",
                    "tool_name": "create_goal",
                    "tool_category": "goals",
                    "description": "Set health and wellness objectives for the week",
                    "tool_inputs": {"title": "Weekly Wellness Goals"},
                    "order": 1,
                },
                {
                    "id": "step_3",
                    "title": "Plan Meal Prep",
                    "tool_name": "create_todo",
                    "tool_category": "todos",
                    "description": "Create task for healthy meal planning and preparation",
                    "tool_inputs": {"title": "Plan and prep healthy meals"},
                    "order": 2,
                },
            ],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 19 * * 0",  # 7 PM on Sundays
                "timezone": "UTC",
            },
            "total_executions": 38,
            "successful_executions": 35,
        },
        # Financial Management
        {
            "title": "Monthly Budget Review",
            "description": "Review expenses, analyze spending patterns, and plan budget for next month",
            "user_id": user_id,
            "is_public": True,
            "steps": [
                {
                    "id": "step_1",
                    "title": "Research Financial Tips",
                    "tool_name": "web_search_tool",
                    "tool_category": "search",
                    "description": "Find current financial advice and budgeting tips",
                    "tool_inputs": {
                        "query": "budgeting tips financial planning",
                        "num_results": 6,
                    },
                    "order": 0,
                },
                {
                    "id": "step_2",
                    "title": "Create Budget Plan",
                    "tool_name": "create_note",
                    "tool_category": "notes",
                    "description": "Document budget plan and financial goals",
                    "tool_inputs": {"title": "Monthly Budget Plan"},
                    "order": 1,
                },
                {
                    "id": "step_3",
                    "title": "Set Financial Goals",
                    "tool_name": "create_goal",
                    "tool_category": "goals",
                    "description": "Create specific financial objectives for the month",
                    "tool_inputs": {"title": "Monthly Financial Goals"},
                    "order": 2,
                },
            ],
            "trigger_config": {
                "type": "schedule",
                "enabled": True,
                "cron_expression": "0 20 28-31 * *",  # 8 PM on last days of month
                "timezone": "UTC",
            },
            "total_executions": 29,
            "successful_executions": 27,
        },
        # Travel Planning
        {
            "title": "Trip Planning Assistant",
            "description": "Research destination, create itinerary, and organize travel documents",
            "user_id": user_id,
            "is_public": True,
            "steps": [
                {
                    "id": "step_1",
                    "title": "Research Destination",
                    "tool_name": "web_search_tool",
                    "tool_category": "search",
                    "description": "Find information about travel destination, attractions, and tips",
                    "tool_inputs": {
                        "query": "travel destination guide attractions",
                        "num_results": 12,
                    },
                    "order": 0,
                },
                {
                    "id": "step_2",
                    "title": "Create Travel Itinerary",
                    "tool_name": "create_note",
                    "tool_category": "notes",
                    "description": "Organize travel plans and itinerary details",
                    "tool_inputs": {"title": "Travel Itinerary"},
                    "order": 1,
                },
                {
                    "id": "step_3",
                    "title": "Travel Preparation Checklist",
                    "tool_name": "create_todo",
                    "tool_category": "todos",
                    "description": "Create checklist for travel preparation tasks",
                    "tool_inputs": {"title": "Complete travel preparations"},
                    "order": 2,
                },
            ],
            "trigger_config": {"type": "manual", "enabled": True},
            "total_executions": 28,
            "successful_executions": 26,
        },
    ]


def create_workflow_from_config(config: Dict[str, Any]) -> Workflow:
    """Create a Workflow object from configuration dictionary."""
    # Create workflow steps
    steps = []
    for step_config in config["steps"]:
        step = WorkflowStep(**step_config)
        steps.append(step)

    # Create trigger config
    trigger_config = TriggerConfig(**config["trigger_config"])

    # Calculate next run time if it's a scheduled workflow
    if trigger_config.type == "schedule" and trigger_config.cron_expression:
        trigger_config.update_next_run()

    # Create workflow
    workflow = Workflow(
        id=config.get("id", f"wf_{uuid.uuid4().hex[:12]}"),
        user_id=config["user_id"],
        title=config["title"],
        description=config["description"],
        steps=steps,
        trigger_config=trigger_config,
        activated=config.get("activated", True),
        is_public=config.get("is_public", False),
        created_by=config.get("created_by", config["user_id"]),
        total_executions=config.get("total_executions", 0),
        successful_executions=config.get("successful_executions", 0),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    return workflow


async def create_backup() -> str:
    """Create a backup of the current workflows collection."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"workflows_backup_{timestamp}.json"

    try:
        existing_workflows = []
        async for workflow in workflows_collection.find({}):
            # Convert ObjectId to string for JSON serialization
            workflow["_id"] = str(workflow["_id"])
            existing_workflows.append(workflow)

        with open(backup_file, "w") as f:
            json.dump(existing_workflows, f, indent=2, default=str)

        print(f"✅ Backup created: {backup_file}")
        return backup_file
    except Exception as e:
        print(f"❌ Error creating backup: {e}")
        raise


async def seed_workflows(
    dry_run: bool = False,
    force: bool = False,
    backup: bool = False,
    user_id: str = "system",
) -> None:
    """
    Seed the workflows collection with public use case workflows.

    Args:
        dry_run: If True, only show what changes would be made
        force: If True, skip confirmation prompts
        backup: If True, create backup before making changes
        user_id: User ID to assign to the workflows
    """

    print("🔄 Starting workflows seeding...")

    # Get workflow configurations
    workflow_configs = get_public_workflows_configuration(user_id)

    # Check existing workflows
    existing_count = await workflows_collection.count_documents({})
    public_count = await workflows_collection.count_documents({"is_public": True})

    print("\n📊 Current State:")
    print(f"   📄 Existing workflows: {existing_count}")
    print(f"   🌐 Public workflows: {public_count}")
    print(f"   ➕ Workflows to add: {len(workflow_configs)}")

    # Display workflows to be added
    print("\n📝 Public Workflows to Add:")
    for i, config in enumerate(workflow_configs, 1):
        trigger_type = config["trigger_config"]["type"]
        if trigger_type == "schedule":
            cron = config["trigger_config"].get("cron_expression", "N/A")
            trigger_desc = f"Scheduled ({cron})"
        else:
            trigger_desc = trigger_type.title()

        print(f"   {i:2d}. {config['title']}")
        print(
            f"       📝 {config['description'][:80]}{'...' if len(config['description']) > 80 else ''}"
        )
        print(f"       ⚡ {trigger_desc}")
        print(f"       🔧 {len(config['steps'])} steps")

    if dry_run:
        print("\n🔍 DRY RUN - No changes will be applied.")
        print("   Run without --dry-run to add these workflows.")
        return

    # Confirmation prompt
    if not force:
        response = input(f"\n❓ Add {len(workflow_configs)} public workflows? (y/N): ")
        if response.lower() != "y":
            print("❌ Operation cancelled.")
            return

    # Create backup if requested
    if backup:
        await create_backup()

    # Add workflows
    print("\n🚀 Adding workflows...")

    try:
        workflows_to_insert = []

        for config in workflow_configs:
            # Check if workflow with same title already exists
            existing = await workflows_collection.find_one(
                {"title": config["title"], "user_id": user_id}
            )

            if existing:
                print(f"⚠️  Skipping '{config['title']}' - already exists")
                continue

            # Create workflow object
            workflow = create_workflow_from_config(config)

            # Convert to dict for MongoDB insertion
            workflow_dict = workflow.model_dump(mode="json")
            workflow_dict["_id"] = workflow_dict["id"]

            workflows_to_insert.append(workflow_dict)
            print(f"✅ Prepared: {workflow.title}")

        # Insert all workflows
        if workflows_to_insert:
            result = await workflows_collection.insert_many(workflows_to_insert)
            print(f"\n🎉 Successfully added {len(result.inserted_ids)} workflows!")
        else:
            print("\n⚠️  No new workflows to add (all already exist)")

        # Final summary
        final_count = await workflows_collection.count_documents({})
        final_public_count = await workflows_collection.count_documents(
            {"is_public": True}
        )

        print("\n📊 Final State:")
        print(f"   📄 Total workflows: {final_count}")
        print(f"   🌐 Public workflows: {final_public_count}")

        # Display workflow statistics
        categories: dict[str, int] = {}
        async for workflow in workflows_collection.find({"is_public": True}):
            # Count by trigger type
            trigger_type = workflow.get("trigger_config", {}).get("type", "unknown")
            categories[trigger_type] = categories.get(trigger_type, 0) + 1

        print("\n📈 Public Workflow Breakdown:")
        for trigger_type, count in sorted(categories.items()):
            print(f"   📌 {trigger_type.title()}: {count}")

    except Exception as e:
        print(f"❌ Error during seeding: {e}")
        raise


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Seed workflows collection with public use cases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/seed_workflows.py                          # Normal seed with prompts
  python scripts/seed_workflows.py --dry-run                # Show changes without applying
  python scripts/seed_workflows.py --force                  # Skip confirmation prompts
  python scripts/seed_workflows.py --user-id "admin123"     # Use specific user ID
  python scripts/seed_workflows.py --no-backup              # Skip creating backup
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what changes would be made without applying them",
    )

    parser.add_argument(
        "--force", action="store_true", help="Skip confirmation prompts"
    )

    parser.add_argument(
        "--no-backup", action="store_true", help="Skip creating backup before changes"
    )

    parser.add_argument(
        "--user-id",
        type=str,
        default="system",
        help="User ID to assign to the workflows (default: system)",
    )

    return parser.parse_args()


async def main():
    """Main function to run the seed script."""
    args = parse_arguments()

    try:
        await seed_workflows(
            dry_run=args.dry_run,
            force=args.force,
            backup=not args.no_backup,
            user_id=args.user_id,
        )
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
