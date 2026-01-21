#!/usr/bin/env python3
"""
Enhanced seed/sync script to manage AI models collection with full CRUD operations.

This script handles:
- Adding new models that don't exist in the database
- Updating existing models with new configurations
- Removing models from database that are no longer in the configuration
- Maintaining data integrity and providing detailed logging

IMPORTANT: Run this script from the correct directory!

1. If running locally:
   cd /path/to/your/gaia/backend
   python scripts/seed_models.py

2. If running inside Docker container:
   cd /app
   python scripts/seed_models.py

3. Alternative Docker approach (set PYTHONPATH):
   PYTHONPATH=/app python scripts/seed_models.py

4. Run as module (from app directory):
   python -m scripts.seed_models

Usage flags:
--dry-run: Show what changes would be made without applying them
--force: Skip confirmation prompts
--backup: Create a backup before making changes
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Add the backend directory to Python path so we can import from app
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Import app modules after path setup  # noqa: E402
from app.db.mongodb.collections import ai_models_collection, users_collection  # noqa: E402
from app.db.redis import delete_cache_by_pattern  # noqa: E402
from app.models.models_models import ModelProvider, PlanType  # noqa: E402

# Redis cache key patterns for chat models (from model_service.py)
CHAT_MODELS_CACHE_PATTERNS = [
    "chat_models:available_models:*",
    "chat_models:model_by_id:*",
    "chat_models:selected_model:*",
    "chat_models:default_model",
]


def get_models_configuration() -> List[Dict[str, Any]]:
    """
    Define the desired models configuration.
    This is the single source of truth for what models should exist.
    """
    return [
        # Google Gemini 3 Models (preview - latest generation)
        {
            "model_id": "gemini-3-flash",
            "name": "Gemini 3 Flash",
            "model_provider": ModelProvider.GEMINI.value,
            "inference_provider": ModelProvider.GEMINI.value,
            "provider_model_name": "gemini-3-flash-preview",
            "description": "Google's most balanced model built for speed, scale, and frontier intelligence with 1M context",
            "logo_url": "/images/icons/gemini.webp",
            "max_tokens": 1_000_000,
            "supports_streaming": True,
            "supports_function_calling": True,
            "available_in_plans": [PlanType.FREE.value, PlanType.PRO.value],
            "lowest_tier": PlanType.FREE.value,
            "is_active": True,
            "is_default": False,
            "pricing_per_1k_input_tokens": 0.0005,
            "pricing_per_1k_output_tokens": 0.003,
        },
        {
            "model_id": "gemini-3-pro",
            "name": "Gemini 3 Pro",
            "model_provider": ModelProvider.GEMINI.value,
            "inference_provider": ModelProvider.GEMINI.value,
            "provider_model_name": "gemini-3-pro-preview",
            "description": "Google's most intelligent model with state-of-the-art reasoning for complex multimodal tasks",
            "logo_url": "/images/icons/gemini.webp",
            "max_tokens": 1_000_000,
            "supports_streaming": True,
            "supports_function_calling": True,
            "available_in_plans": [PlanType.PRO.value],
            "lowest_tier": PlanType.PRO.value,
            "is_active": True,
            "is_default": False,
            "pricing_per_1k_input_tokens": 0.002,
            "pricing_per_1k_output_tokens": 0.012,
        },
        # Grok Models (via OpenRouter)
        {
            "model_id": "x-ai/grok-4.1-fast",
            "name": "Grok 4.1 Fast",
            "model_provider": ModelProvider.GROK.value,
            "inference_provider": ModelProvider.OPENROUTER.value,
            "provider_model_name": "x-ai/grok-4.1-fast",
            "description": "xAI's fast Grok model with strong reasoning capabilities",
            "logo_url": "/images/icons/grok.webp",
            "max_tokens": 128_000,
            "supports_streaming": True,
            "supports_function_calling": True,
            "available_in_plans": [PlanType.FREE.value, PlanType.PRO.value],
            "lowest_tier": PlanType.FREE.value,
            "is_active": True,
            "is_default": True,
            "pricing_per_1k_input_tokens": 0.0004,
            "pricing_per_1k_output_tokens": 0.001,
        },
    ]


async def create_backup() -> str:
    """Create a backup of the current models collection."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"models_backup_{timestamp}.json"

    try:
        existing_models = []
        async for model in ai_models_collection.find({}):
            # Convert ObjectId to string for JSON serialization
            model["_id"] = str(model["_id"])
            existing_models.append(model)

        with open(backup_file, "w") as f:
            json.dump(existing_models, f, indent=2, default=str)

        print(f"✅ Backup created: {backup_file}")
        return backup_file
    except Exception as e:
        print(f"❌ Error creating backup: {e}")
        raise


def normalize_model_for_comparison(model: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a model dictionary for comparison by removing
    timestamps and MongoDB-specific fields.
    """
    comparison_model = model.copy()

    # Remove fields that shouldn't be compared
    fields_to_exclude = {"_id", "created_at", "updated_at"}
    for field in fields_to_exclude:
        comparison_model.pop(field, None)

    return comparison_model


def models_are_different(existing: Dict[str, Any], new: Dict[str, Any]) -> bool:
    """
    Compare two models to see if they're different (excluding timestamps).
    """
    existing_normalized = normalize_model_for_comparison(existing)
    new_normalized = normalize_model_for_comparison(new)

    return existing_normalized != new_normalized


def get_changed_fields(existing: Dict[str, Any], new: Dict[str, Any]) -> List[str]:
    """
    Get a list of fields that have changed between two models.
    """
    existing_normalized = normalize_model_for_comparison(existing)
    new_normalized = normalize_model_for_comparison(new)

    changed_fields = []
    for key, new_value in new_normalized.items():
        if key not in existing_normalized or existing_normalized[key] != new_value:
            changed_fields.append(key)

    # Check for removed fields
    for key in existing_normalized:
        if key not in new_normalized:
            changed_fields.append(f"{key} (removed)")

    return changed_fields


async def sync_models(
    dry_run: bool = False, force: bool = False, backup: bool = False
) -> None:
    """
    Synchronize the models collection with the configuration.

    Args:
        dry_run: If True, only show what changes would be made
        force: If True, skip confirmation prompts
        backup: If True, create backup before making changes
    """

    print("🔄 Starting AI models synchronization...")

    # Get desired configuration
    desired_models = get_models_configuration()
    desired_model_ids = {model["model_id"] for model in desired_models}

    # Get existing models from database
    existing_models = {}
    async for model in ai_models_collection.find({}):
        existing_models[model["model_id"]] = model

    existing_model_ids = set(existing_models.keys())

    # Calculate changes needed
    models_to_add = desired_model_ids - existing_model_ids
    models_to_remove = existing_model_ids - desired_model_ids
    models_to_potentially_update = desired_model_ids & existing_model_ids

    # Check which models actually need updates
    models_to_update = []
    for model_id in models_to_potentially_update:
        existing_model = existing_models[model_id]
        new_model = next(m for m in desired_models if m["model_id"] == model_id)

        if models_are_different(existing_model, new_model):
            changed_fields = get_changed_fields(existing_model, new_model)
            models_to_update.append(
                {
                    "model_id": model_id,
                    "changed_fields": changed_fields,
                    "new_data": new_model,
                }
            )

    # Display summary
    print("\n📊 Synchronization Summary:")
    print(f"   📥 Models to add: {len(models_to_add)}")
    print(f"   🔄 Models to update: {len(models_to_update)}")
    print(f"   📤 Models to remove: {len(models_to_remove)}")
    print(
        f"   ✅ Models unchanged: {len(models_to_potentially_update) - len(models_to_update)}"
    )

    # Show detailed changes
    if models_to_add:
        print("\n➕ Models to ADD:")
        for model_id in models_to_add:
            model = next(m for m in desired_models if m["model_id"] == model_id)
            print(f"   - {model['name']} ({model_id})")

    if models_to_update:
        print("\n🔄 Models to UPDATE:")
        for update_info in models_to_update:
            model_id = update_info["model_id"]
            changed_fields = update_info["changed_fields"]
            print(f"   - {model_id}:")
            for field in changed_fields[:5]:  # Show first 5 changed fields
                print(f"     • {field}")
            if len(changed_fields) > 5:
                print(f"     • ... and {len(changed_fields) - 5} more fields")

    if models_to_remove:
        print("\n❌ Models to REMOVE:")
        for model_id in models_to_remove:
            model_name = existing_models[model_id].get("name", "Unknown")
            print(f"   - {model_name} ({model_id})")

    # If no changes needed
    if not models_to_add and not models_to_update and not models_to_remove:
        print("\n✅ No changes needed. All models are up to date!")
        return

    # Dry run - just show what would happen
    if dry_run:
        print("\n🔍 DRY RUN - No changes will be applied.")
        print("   Run without --dry-run to apply these changes.")
        return

    # Confirmation prompt
    if not force:
        total_changes = (
            len(models_to_add) + len(models_to_update) + len(models_to_remove)
        )
        response = input(f"\n❓ Apply {total_changes} changes? (y/N): ")
        if response.lower() != "y":
            print("❌ Operation cancelled.")
            return

    # Create backup if requested
    if backup and (models_to_update or models_to_remove):
        await create_backup()

    # Apply changes
    print("\n🚀 Applying changes...")

    try:
        # Add new models
        if models_to_add:
            new_models = []
            for model_id in models_to_add:
                model = next(m for m in desired_models if m["model_id"] == model_id)
                model["created_at"] = datetime.now(timezone.utc)
                model["updated_at"] = datetime.now(timezone.utc)
                new_models.append(model)

            result = await ai_models_collection.insert_many(new_models)
            print(f"✅ Added {len(result.inserted_ids)} new models")

        # Update existing models
        for update_info in models_to_update:
            model_id = update_info["model_id"]
            new_data = update_info["new_data"].copy()
            new_data["updated_at"] = datetime.now(timezone.utc)

            # Preserve created_at from existing model
            new_data["created_at"] = existing_models[model_id]["created_at"]

            await ai_models_collection.replace_one({"model_id": model_id}, new_data)
            print(f"✅ Updated model: {model_id}")

        # Remove obsolete models
        if models_to_remove:
            # First, reset users who have selected a model being removed
            default_model = next(
                (m["model_id"] for m in desired_models if m.get("is_default")),
                desired_models[0]["model_id"] if desired_models else None,
            )
            if default_model:
                reset_result = await users_collection.update_many(
                    {"selected_model": {"$in": list(models_to_remove)}},
                    {"$set": {"selected_model": default_model}},
                )
                if reset_result.modified_count > 0:
                    print(
                        f"✅ Reset {reset_result.modified_count} users' selected model to {default_model}"
                    )

            result = await ai_models_collection.delete_many(
                {"model_id": {"$in": list(models_to_remove)}}
            )
            print(f"✅ Removed {result.deleted_count} obsolete models")

        print("\n🎉 Synchronization completed successfully!")

        # Clear Redis cache for chat models
        print("\n🧹 Clearing Redis cache for chat models...")
        for pattern in CHAT_MODELS_CACHE_PATTERNS:
            await delete_cache_by_pattern(pattern)
        print("✅ Redis cache cleared")

        # Final summary
        final_count = await ai_models_collection.count_documents({})
        print(f"📊 Total models in database: {final_count}")

    except Exception as e:
        print(f"❌ Error during synchronization: {e}")
        raise


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Synchronize AI models collection with configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/seed_models.py                    # Normal sync with prompts
  python scripts/seed_models.py --dry-run          # Show changes without applying
  python scripts/seed_models.py --force            # Skip confirmation prompts
  python scripts/seed_models.py --no-backup        # Skip creating backup
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

    return parser.parse_args()


async def main():
    """Main function to run the sync script."""
    args = parse_arguments()

    try:
        await sync_models(
            dry_run=args.dry_run, force=args.force, backup=not args.no_backup
        )
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
