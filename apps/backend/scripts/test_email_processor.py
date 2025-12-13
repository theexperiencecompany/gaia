#!/usr/bin/env python3
"""
Test script for Gmail email memory processing.

This script allows testing the email processor with a specific user ID.

IMPORTANT: Run this script from the correct directory!

1. If running locally:
   cd /path/to/your/gaia/backend
   python scripts/test_email_processor.py --user-id <user_id>

2. If running inside Docker container:
   cd /app
   python scripts/test_email_processor.py --user-id <user_id>

3. Alternative Docker approach (set PYTHONPATH):
   PYTHONPATH=/app python scripts/test_email_processor.py --user-id <user_id>

4. Run as module (from app directory):
   python -m scripts.test_email_processor --user-id <user_id>

Usage examples:
python scripts/test_email_processor.py --user-id 507f1f77bcf86cd799439011
python scripts/test_email_processor.py --user-id 507f1f77bcf86cd799439011 --verbose
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Dict

# Add the backend directory to Python path so we can import from app
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Import app modules after path setup  # noqa: E402
from app.agents.memory.email_processor import process_gmail_to_memory  # noqa: E402


async def initialize_providers():
    """Initialize required providers for standalone script execution."""
    try:
        # Import necessary modules
        from app.core.lazy_loader import providers  # noqa: E402
        from app.services.composio.composio_service import (
            init_composio_service,
            get_composio_service,
        )  # noqa: E402
        from app.config.settings import get_settings  # noqa: E402

        # Initialize settings first
        get_settings()
        print("✅ Settings initialized")

        # Register the composio service provider
        init_composio_service()
        print("✅ Composio service provider registered")

        # Force initialization of the provider through the lazy loading system
        composio_service = providers.get("composio_service")
        if composio_service is None:
            raise RuntimeError(
                "Failed to initialize composio service through lazy loader"
            )

        print("✅ Composio service provider initialized")

        # Test that we can actually get the service
        get_composio_service()
        print("✅ Composio service retrieval test successful")

    except Exception as e:
        print(f"⚠️  Warning: Failed to initialize providers: {e}")
        print("   This might cause issues with email processing")
        raise


def validate_user_id(user_id: str) -> bool:
    """Validate that the user ID is a valid MongoDB ObjectId format."""
    if len(user_id) != 24:
        return False
    try:
        int(user_id, 16)
        return True
    except ValueError:
        return False


async def test_email_processor(user_id: str, verbose: bool = False) -> Dict:
    """
    Test the email processor for a specific user.

    Args:
        user_id: MongoDB ObjectId string for the user
        verbose: Enable verbose logging

    Returns:
        Dict with processing results
    """

    await initialize_providers()

    if not validate_user_id(user_id):
        raise ValueError(
            f"Invalid user ID format: {user_id}. Must be a 24-character hex string."
        )

    if verbose:
        print("ℹ️  Verbose mode enabled - detailed logs will be shown")

    print(f"🚀 Starting Gmail email processing test for user: {user_id}")
    print("=" * 60)

    try:
        result = await process_gmail_to_memory(user_id)

        print("\n📊 Processing Results:")
        print("=" * 60)

        if result.get("already_processed", False):
            print("ℹ️  User emails were already processed")
        else:
            print(f"📥 Total emails found: {result.get('total', 0)}")
            print(f"✅ Successfully processed: {result.get('successful', 0)}")
            print(f"❌ Failed to process: {result.get('failed', 0)}")

            processing_complete = result.get("processing_complete", False)
            if processing_complete:
                print("✅ Processing marked as complete")
            else:
                print("⚠️  Processing NOT marked as complete (too many failures)")

            if result.get("total", 0) > 0:
                success_rate = (
                    result.get("successful", 0) / result.get("total", 1)
                ) * 100
                print(f"📈 Success rate: {success_rate:.1f}%")

        print("\n🎉 Test completed successfully!")
        return result

    except Exception as e:
        print(f"\n❌ Error during processing: {e}")
        raise


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Test Gmail email memory processing for a specific user",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/test_email_processor.py --user-id 507f1f77bcf86cd799439011
  python scripts/test_email_processor.py --user-id 507f1f77bcf86cd799439011 --verbose
        """,
    )

    parser.add_argument(
        "--user-id",
        required=True,
        help="MongoDB ObjectId of the user to test (24-character hex string)",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging output",
    )

    return parser.parse_args()


async def main():
    """Main function to run the test script."""
    args = parse_arguments()

    try:
        await test_email_processor(args.user_id, args.verbose)
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
