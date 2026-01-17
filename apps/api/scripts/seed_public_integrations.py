#!/usr/bin/env python3
"""
Seed script to populate the integrations collection with public community integrations.

This script adds sample public MCP integrations to demonstrate the marketplace.
All integrations are marked as published and publicly visible.

Usage:
    cd apps/api
    uv run python scripts/seed_public_integrations.py

Flags:
    --dry-run: Show what would be inserted without making changes
    --force: Skip confirmation prompts
    --clear: Clear existing public integrations before seeding
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import random

# Add the backend directory to Python path so we can import from app
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.db.mongodb.collections import integrations_collection  # noqa: E402


def get_public_integrations() -> List[Dict[str, Any]]:
    """
    Define public community integrations to seed.
    These are real MCP servers from the community.
    """
    now = datetime.now(timezone.utc)

    return [
        # Research & Knowledge
        {
            "integration_id": "custom_semantic_scholar",
            "name": "Semantic Scholar",
            "description": "Search and retrieve academic papers, citations, and research data from Semantic Scholar's database of over 200 million papers.",
            "category": "research",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "created_by": "system_seed",
            "published_at": now,
            "clone_count": random.randint(50, 200),
            "slug": "semantic-scholar",
            "og_title": "Semantic Scholar MCP Integration",
            "og_description": "Access academic papers and research data through AI",
            "creator_name": "Hamid Vakilzadeh",
            "creator_picture": None,
            "mcp_config": {
                "server_url": "https://server.smithery.ai/@hamid-vakilzadeh/mcpsemanticscholar",
                "requires_auth": False,
                "auth_type": "none",
            },
            "tools": [
                {
                    "name": "search_papers",
                    "description": "Search for academic papers by keywords",
                },
                {
                    "name": "get_paper_details",
                    "description": "Get detailed information about a specific paper",
                },
                {
                    "name": "get_citations",
                    "description": "Retrieve citations for a paper",
                },
                {
                    "name": "get_references",
                    "description": "Get papers referenced by a given paper",
                },
                {
                    "name": "get_author",
                    "description": "Get information about an author",
                },
            ],
            "icon_url": "https://www.semanticscholar.org/favicon.ico",
            "display_priority": 10,
            "is_featured": True,
            "created_at": now,
        },
        # Web & Browser
        {
            "integration_id": "custom_browserbase",
            "name": "Browserbase",
            "description": "Control headless browsers for web scraping, automation, and testing. Navigate pages, extract content, and interact with web elements.",
            "category": "developer",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "created_by": "system_seed",
            "published_at": now,
            "clone_count": random.randint(100, 400),
            "slug": "browserbase",
            "og_title": "Browserbase MCP Integration",
            "og_description": "AI-powered browser automation and web scraping",
            "creator_name": "Browserbase Team",
            "creator_picture": None,
            "mcp_config": {
                "server_url": "https://server.smithery.ai/@anthropics/mcp-server-browserbase",
                "requires_auth": False,
                "auth_type": "none",
            },
            "tools": [
                {"name": "navigate", "description": "Navigate to a URL"},
                {"name": "screenshot", "description": "Take a screenshot of the page"},
                {"name": "click", "description": "Click on an element"},
                {"name": "type", "description": "Type text into an input"},
                {"name": "get_content", "description": "Extract page content"},
            ],
            "icon_url": "https://www.browserbase.com/favicon.ico",
            "display_priority": 9,
            "is_featured": True,
            "created_at": now,
        },
        # Database & Storage
        {
            "integration_id": "custom_supabase",
            "name": "Supabase",
            "description": "Interact with Supabase databases - query tables, insert data, manage authentication, and work with real-time subscriptions.",
            "category": "developer",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "created_by": "system_seed",
            "published_at": now,
            "clone_count": random.randint(150, 500),
            "slug": "supabase",
            "og_title": "Supabase MCP Integration",
            "og_description": "Connect AI to your Supabase database",
            "creator_name": "Alexander Zuev",
            "creator_picture": None,
            "mcp_config": {
                "server_url": "https://server.smithery.ai/@alexander-zuev/supabase-mcp-server",
                "requires_auth": False,
                "auth_type": "none",
            },
            "tools": [
                {
                    "name": "query",
                    "description": "Execute SQL queries on your database",
                },
                {"name": "insert", "description": "Insert data into tables"},
                {"name": "update", "description": "Update existing records"},
                {"name": "delete", "description": "Delete records from tables"},
                {
                    "name": "list_tables",
                    "description": "List all tables in the database",
                },
            ],
            "icon_url": "https://supabase.com/favicon.ico",
            "display_priority": 8,
            "is_featured": True,
            "created_at": now,
        },
        # File & Document
        {
            "integration_id": "custom_gdrive",
            "name": "Google Drive MCP",
            "description": "Search, read, and manage files in Google Drive. Access documents, spreadsheets, and collaborate on shared files.",
            "category": "productivity",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "created_by": "system_seed",
            "published_at": now,
            "clone_count": random.randint(200, 600),
            "slug": "google-drive-mcp",
            "og_title": "Google Drive MCP Integration",
            "og_description": "AI access to your Google Drive files",
            "creator_name": "Anthropic",
            "creator_picture": None,
            "mcp_config": {
                "server_url": "https://server.smithery.ai/@anthropics/mcp-server-gdrive",
                "requires_auth": True,
                "auth_type": "oauth",
            },
            "tools": [
                {
                    "name": "search_files",
                    "description": "Search for files by name or content",
                },
                {"name": "read_file", "description": "Read the contents of a file"},
                {"name": "list_folder", "description": "List files in a folder"},
                {"name": "create_file", "description": "Create a new file"},
                {"name": "share_file", "description": "Share a file with others"},
            ],
            "icon_url": "https://ssl.gstatic.com/images/branding/product/1x/drive_2020q4_48dp.png",
            "display_priority": 7,
            "is_featured": False,
            "created_at": now,
        },
        # Communication
        {
            "integration_id": "custom_slack_mcp",
            "name": "Slack MCP",
            "description": "Send messages, search conversations, and manage Slack workspaces. Interact with channels, users, and threads programmatically.",
            "category": "communication",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "created_by": "system_seed",
            "published_at": now,
            "clone_count": random.randint(100, 350),
            "slug": "slack-mcp",
            "og_title": "Slack MCP Integration",
            "og_description": "AI-powered Slack messaging and search",
            "creator_name": "Anthropic",
            "creator_picture": None,
            "mcp_config": {
                "server_url": "https://server.smithery.ai/@anthropics/mcp-server-slack",
                "requires_auth": True,
                "auth_type": "oauth",
            },
            "tools": [
                {
                    "name": "send_message",
                    "description": "Send a message to a channel or user",
                },
                {"name": "search_messages", "description": "Search for messages"},
                {"name": "list_channels", "description": "List available channels"},
                {"name": "get_thread", "description": "Get messages in a thread"},
                {"name": "add_reaction", "description": "Add a reaction to a message"},
            ],
            "icon_url": "https://a.slack-edge.com/80588/marketing/img/meta/favicon-32.png",
            "display_priority": 6,
            "is_featured": False,
            "created_at": now,
        },
        # Code & Development
        {
            "integration_id": "custom_github_mcp",
            "name": "GitHub MCP",
            "description": "Interact with GitHub repositories - search code, manage issues and pull requests, view commits, and automate workflows.",
            "category": "developer",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "created_by": "system_seed",
            "published_at": now,
            "clone_count": random.randint(300, 800),
            "slug": "github-mcp",
            "og_title": "GitHub MCP Integration",
            "og_description": "Connect AI to your GitHub repositories",
            "creator_name": "Anthropic",
            "creator_picture": None,
            "mcp_config": {
                "server_url": "https://server.smithery.ai/@anthropics/mcp-server-github",
                "requires_auth": True,
                "auth_type": "oauth",
            },
            "tools": [
                {
                    "name": "search_code",
                    "description": "Search for code across repositories",
                },
                {"name": "get_file", "description": "Get the contents of a file"},
                {"name": "list_issues", "description": "List issues in a repository"},
                {"name": "create_issue", "description": "Create a new issue"},
                {"name": "get_pull_request", "description": "Get pull request details"},
            ],
            "icon_url": "https://github.githubassets.com/favicons/favicon.svg",
            "display_priority": 10,
            "is_featured": True,
            "created_at": now,
        },
        # Data & APIs
        {
            "integration_id": "custom_weather",
            "name": "Weather API",
            "description": "Get current weather conditions, forecasts, and historical weather data for any location worldwide.",
            "category": "data",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "created_by": "system_seed",
            "published_at": now,
            "clone_count": random.randint(50, 150),
            "slug": "weather-api",
            "og_title": "Weather API MCP Integration",
            "og_description": "Real-time weather data for AI applications",
            "creator_name": "MCP Community",
            "creator_picture": None,
            "mcp_config": {
                "server_url": "https://server.smithery.ai/@anthropics/mcp-server-fetch",
                "requires_auth": False,
                "auth_type": "none",
            },
            "tools": [
                {
                    "name": "get_current_weather",
                    "description": "Get current weather for a location",
                },
                {"name": "get_forecast", "description": "Get weather forecast"},
                {
                    "name": "get_historical",
                    "description": "Get historical weather data",
                },
            ],
            "icon_url": None,
            "display_priority": 3,
            "is_featured": False,
            "created_at": now,
        },
        # E-commerce
        {
            "integration_id": "custom_stripe",
            "name": "Stripe",
            "description": "Manage Stripe payments - view transactions, customers, subscriptions, and generate reports on your payment data.",
            "category": "finance",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "created_by": "system_seed",
            "published_at": now,
            "clone_count": random.randint(80, 250),
            "slug": "stripe",
            "og_title": "Stripe MCP Integration",
            "og_description": "AI-powered Stripe payment management",
            "creator_name": "MCP Community",
            "creator_picture": None,
            "mcp_config": {
                "server_url": "https://server.smithery.ai/@anthropics/mcp-server-stripe",
                "requires_auth": True,
                "auth_type": "bearer",
            },
            "tools": [
                {"name": "list_payments", "description": "List recent payments"},
                {"name": "get_customer", "description": "Get customer details"},
                {
                    "name": "list_subscriptions",
                    "description": "List active subscriptions",
                },
                {"name": "create_invoice", "description": "Create an invoice"},
                {"name": "get_balance", "description": "Get account balance"},
            ],
            "icon_url": "https://stripe.com/favicon.ico",
            "display_priority": 5,
            "is_featured": False,
            "created_at": now,
        },
        # News & Content
        {
            "integration_id": "custom_hackernews",
            "name": "Hacker News",
            "description": "Search and browse Hacker News - get top stories, comments, and discussions from the tech community.",
            "category": "news",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "created_by": "system_seed",
            "published_at": now,
            "clone_count": random.randint(60, 180),
            "slug": "hacker-news",
            "og_title": "Hacker News MCP Integration",
            "og_description": "AI access to Hacker News content",
            "creator_name": "MCP Community",
            "creator_picture": None,
            "mcp_config": {
                "server_url": "https://server.smithery.ai/@anthropics/mcp-server-fetch",
                "requires_auth": False,
                "auth_type": "none",
            },
            "tools": [
                {
                    "name": "get_top_stories",
                    "description": "Get top stories from Hacker News",
                },
                {
                    "name": "get_story",
                    "description": "Get a specific story with comments",
                },
                {
                    "name": "search_stories",
                    "description": "Search for stories by keywords",
                },
            ],
            "icon_url": "https://news.ycombinator.com/favicon.ico",
            "display_priority": 4,
            "is_featured": False,
            "created_at": now,
        },
        # Memory & Context
        {
            "integration_id": "custom_memory",
            "name": "Memory Server",
            "description": "Persistent memory storage for AI conversations - remember user preferences, past interactions, and important context.",
            "category": "ai",
            "managed_by": "mcp",
            "source": "custom",
            "is_public": True,
            "created_by": "system_seed",
            "published_at": now,
            "clone_count": random.randint(40, 120),
            "slug": "memory-server",
            "og_title": "Memory Server MCP Integration",
            "og_description": "Persistent memory for AI applications",
            "creator_name": "Anthropic",
            "creator_picture": None,
            "mcp_config": {
                "server_url": "https://server.smithery.ai/@anthropics/mcp-server-memory",
                "requires_auth": False,
                "auth_type": "none",
            },
            "tools": [
                {"name": "store_memory", "description": "Store a piece of information"},
                {"name": "retrieve_memory", "description": "Retrieve stored memories"},
                {
                    "name": "search_memories",
                    "description": "Search through stored memories",
                },
                {"name": "delete_memory", "description": "Delete a stored memory"},
            ],
            "icon_url": None,
            "display_priority": 2,
            "is_featured": False,
            "created_at": now,
        },
    ]


async def seed_integrations(
    dry_run: bool = False,
    force: bool = False,
    clear: bool = False,
) -> None:
    """Seed public integrations into the database."""

    integrations = get_public_integrations()

    print("\n🌱 Public Integrations Seeder")
    print("=" * 50)
    print(f"📦 Integrations to seed: {len(integrations)}")

    if dry_run:
        print("\n🔍 DRY RUN MODE - No changes will be made\n")
        for integration in integrations:
            print(f"  • {integration['name']} ({integration['integration_id']})")
            print(f"    Category: {integration['category']}")
            print(f"    Server: {integration['mcp_config']['server_url']}")
            print(f"    Featured: {integration['is_featured']}")
            print()
        return

    if not force:
        confirm = input(
            "\n⚠️  This will insert integrations into the database. Continue? (y/N): "
        )
        if confirm.lower() != "y":
            print("❌ Aborted.")
            return

    # Clear existing public integrations if requested
    if clear:
        result = await integrations_collection.delete_many(
            {
                "source": "custom",
                "is_public": True,
                "created_by": "system_seed",
            }
        )
        print(f"🗑️  Cleared {result.deleted_count} existing seeded integrations")

    # Insert integrations
    inserted = 0
    updated = 0
    skipped = 0

    for integration in integrations:
        # Check if integration already exists
        existing = await integrations_collection.find_one(
            {"integration_id": integration["integration_id"]}
        )

        if existing:
            if force:
                # Update existing
                await integrations_collection.update_one(
                    {"integration_id": integration["integration_id"]},
                    {"$set": integration},
                )
                updated += 1
                print(f"  ♻️  Updated: {integration['name']}")
            else:
                skipped += 1
                print(f"  ⏭️  Skipped (exists): {integration['name']}")
        else:
            # Insert new
            await integrations_collection.insert_one(integration)
            inserted += 1
            print(f"  ✅ Inserted: {integration['name']}")

    print("\n" + "=" * 50)
    print(f"📊 Summary:")
    print(f"   Inserted: {inserted}")
    print(f"   Updated:  {updated}")
    print(f"   Skipped:  {skipped}")
    print("✨ Done!\n")


def main():
    parser = argparse.ArgumentParser(
        description="Seed public integrations into the database"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation and update existing integrations",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing seeded integrations before inserting",
    )

    args = parser.parse_args()

    asyncio.run(
        seed_integrations(
            dry_run=args.dry_run,
            force=args.force,
            clear=args.clear,
        )
    )


if __name__ == "__main__":
    main()
