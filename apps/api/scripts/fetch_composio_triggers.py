#!/usr/bin/env python3
"""
Fetch Available Composio Triggers Script

Independent script to fetch all available Composio triggers for GAIA's integrations.
Outputs trigger information including slug, name, description, and config schema.

Usage:
    cd apps/api
    python scripts/fetch_composio_triggers.py

Requirements:
    - COMPOSIO_API_KEY environment variable must be set
    - Or run with: ENV=development python scripts/fetch_composio_triggers.py
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

# Add the app directory to the path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set environment for local development
if not os.getenv("ENV"):
    os.environ["ENV"] = "development"


def load_integrations() -> list[dict[str, Any]]:
    """Load integrations from oauth_config.py"""
    from app.config.oauth_config import OAUTH_INTEGRATIONS

    integrations = []
    for integration in OAUTH_INTEGRATIONS:
        if integration.composio_config:
            integrations.append(
                {
                    "id": integration.id,
                    "name": integration.name,
                    "toolkit": integration.composio_config.toolkit,
                    "existing_triggers": [
                        t.slug for t in integration.associated_triggers
                    ],
                }
            )
    return integrations


def fetch_triggers_for_app(composio: Any, app_name: str) -> list[dict[str, Any]]:
    """Fetch available triggers for a specific app/toolkit."""
    try:
        # Use triggers.list() with toolkit_slugs parameter (correct method)
        response = composio.triggers.list(toolkit_slugs=[app_name], limit=100)

        # The response might be a paginated object with .items attribute
        triggers = response.items if hasattr(response, "items") else response

        # For each trigger, try to get the detailed info with config schema
        detailed_triggers = []
        for trigger in triggers:
            trigger_slug = getattr(trigger, "slug", getattr(trigger, "name", None))
            if trigger_slug:
                try:
                    detailed = composio.triggers.get_type(slug=trigger_slug)
                    detailed_triggers.append(detailed)
                except Exception:
                    # Fall back to basic trigger info
                    detailed_triggers.append(trigger)

        return detailed_triggers
    except Exception as e:
        print(f"  Error fetching triggers for {app_name}: {e}")
        return []


def extract_trigger_info(trigger: Any) -> dict[str, Any]:
    """Extract relevant information from a trigger object."""
    info = {
        "slug": getattr(trigger, "slug", getattr(trigger, "name", "unknown")),
        "name": getattr(trigger, "display_name", getattr(trigger, "name", "unknown")),
        "description": getattr(trigger, "description", "No description"),
    }

    # Try to get config schema
    if hasattr(trigger, "config"):
        info["config_schema"] = trigger.config
    elif hasattr(trigger, "config_schema"):
        info["config_schema"] = trigger.config_schema
    elif hasattr(trigger, "properties"):
        info["config_schema"] = trigger.properties

    # Try to get payload schema
    if hasattr(trigger, "payload"):
        info["payload_schema"] = trigger.payload
    elif hasattr(trigger, "payload_schema"):
        info["payload_schema"] = trigger.payload_schema

    return info


def format_config_schema(config: Any) -> str:
    """Format config schema for display."""
    if not config:
        return "  (No configuration required)"

    if isinstance(config, dict):
        lines = []
        properties = config.get("properties", config)
        required = config.get("required", [])

        for key, value in properties.items():
            if isinstance(value, dict):
                field_type = value.get("type", "unknown")
                description = value.get("description", "")
                default = value.get("default", "")
                is_required = key in required

                line = f"    - {key}: {field_type}"
                if default:
                    line += f" (default: {default})"
                if is_required:
                    line += " [REQUIRED]"
                if description:
                    line += f" - {description}"
                lines.append(line)
            else:
                lines.append(f"    - {key}: {value}")

        return "\n".join(lines) if lines else "  (No configuration required)"

    return f"  {config}"


def main():
    """Main function to fetch and display triggers."""
    print("=" * 80)
    print("COMPOSIO TRIGGERS FETCH SCRIPT")
    print("=" * 80)
    print()

    # Initialize Composio
    try:
        from app.config.settings import settings

        if not settings.COMPOSIO_KEY:
            print(
                "ERROR: COMPOSIO_API_KEY not set. Please set the environment variable."
            )
            sys.exit(1)

        from composio import Composio

        composio = Composio(api_key=settings.COMPOSIO_KEY)
        print("✓ Composio client initialized")
    except Exception as e:
        print(f"ERROR: Failed to initialize Composio client: {e}")
        sys.exit(1)

    # Load integrations
    try:
        integrations = load_integrations()
        print(f"✓ Loaded {len(integrations)} integrations from oauth_config.py")
    except Exception as e:
        print(f"ERROR: Failed to load integrations: {e}")
        sys.exit(1)

    print()
    print("-" * 80)
    print()

    # Store all triggers for JSON output
    all_triggers: dict[str, Any] = {}

    # Fetch triggers for each integration
    for integration in integrations:
        toolkit = integration["toolkit"]
        print(f"📦 {integration['name']} ({toolkit})")
        print(f"   Existing triggers: {integration['existing_triggers'] or 'None'}")
        print()

        triggers = fetch_triggers_for_app(composio, toolkit)

        if not triggers:
            print("   No triggers found for this integration")
            print()
            continue

        all_triggers[toolkit] = []

        for trigger in triggers:
            try:
                info = extract_trigger_info(trigger)
                all_triggers[toolkit].append(info)

                # Check if this trigger is already configured
                is_existing = info["slug"] in integration["existing_triggers"]
                status = "✅ CONFIGURED" if is_existing else "⚪ AVAILABLE"

                print(f"   {status} {info['slug']}")
                print(f"      Name: {info['name']}")
                print(f"      Description: {info['description']}")

                if "config_schema" in info:
                    print("      Config:")
                    print(format_config_schema(info["config_schema"]))

                print()

            except Exception as e:
                print(f"   Error processing trigger: {e}")

        print("-" * 80)
        print()

    # Save to JSON file
    output_file = Path(__file__).parent / "composio_triggers_output.json"
    with open(output_file, "w") as f:
        json.dump(all_triggers, f, indent=2, default=str)

    print(f"✓ Full output saved to: {output_file}")
    print()

    # Summary
    total_available = sum(len(triggers) for triggers in all_triggers.values())
    total_configured = sum(
        len(integration["existing_triggers"]) for integration in integrations
    )

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"  Total integrations scanned: {len(integrations)}")
    print(f"  Total triggers available: {total_available}")
    print(f"  Total triggers already configured: {total_configured}")
    print("=" * 80)


if __name__ == "__main__":
    main()
