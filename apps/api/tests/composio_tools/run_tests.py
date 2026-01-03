#!/usr/bin/env python
"""
CLI runner for Composio tool integration tests.

Run tests by integration name instead of pytest directly.

Usage:
    python -m tests.composio_tools.run_tests gmail
    python -m tests.composio_tools.run_tests all --skip-destructive
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from tests.composio_tools.config_utils import (
    ALL_INTEGRATIONS,
    INTEGRATION_MAP,
    get_test_file,
    get_user_id,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("run_tests")

# Base directory for test files
TEST_DIR = Path(__file__).parent


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run Composio tool integration tests by name",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "integrations",
        nargs="+",
        help="Integration names to test (e.g., gmail, notion, calendar, all)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--skip-destructive",
        action="store_true",
        help="Skip destructive tests (creates, deletes, etc.)",
    )
    parser.add_argument(
        "--user-id",
        help="Override user ID from config/env",
    )
    parser.add_argument(
        "-s",
        action="store_true",
        help="Allow stdout to be shown (interactive mode)",
    )
    parser.add_argument(
        "-k",
        help="Run only tests matching expression (passed to pytest)",
    )
    parser.add_argument(
        "--confirm-action",
        "--confirm",
        action="store_true",
        help="Confirm destructive actions before execution (passes --yes to pytest)",
    )
    return parser.parse_args()


def resolve_integrations(names: list[str]) -> list[str]:
    """
    Resolve integration names, expanding 'all' to all integrations.

    Returns list of test file names (without .py).
    """
    test_files = []

    for name in names:
        name_lower = name.lower()

        if name_lower == "all":
            # Add all integrations
            for integration in ALL_INTEGRATIONS:
                test_file = get_test_file(integration)
                if test_file and test_file not in test_files:
                    test_files.append(test_file)
        else:
            test_file = get_test_file(name_lower)
            if test_file:
                if test_file not in test_files:
                    test_files.append(test_file)
            else:
                logger.warning(f"Warning: Unknown integration '{name}'. Skipping.")
                logger.info(f"Available: {', '.join(sorted(INTEGRATION_MAP.keys()))}")

    return test_files


def run_tests(test_files: list[str], args) -> int:
    """
    Run pytest for the specified test files.

    Returns exit code (0 for success).
    """
    if not test_files:
        logger.error("No test files to run.")
        return 1

    # Get user ID
    user_id = args.user_id or get_user_id()
    if not user_id:
        logger.error("Error: No user ID provided.")
        logger.info("Set EVAL_USER_ID env var or use --user-id flag.")
        return 1

    # Build pytest command
    cmd = [
        sys.executable,
        "-m",
        "pytest",
    ]

    # Add test files
    for test_file in test_files:
        test_path = TEST_DIR / f"{test_file}.py"
        if test_path.exists():
            cmd.append(str(test_path))
        else:
            logger.warning(f"Warning: Test file not found: {test_path}")

    # Add user ID
    cmd.extend(["--user-id", user_id])

    # Add optional flags
    if args.verbose:
        cmd.append("-v")

    if args.skip_destructive:
        cmd.extend(["--skip-destructive"])

    if args.k:
        cmd.extend(["-k", args.k])

    if args.s:
        cmd.append("-s")

    if args.confirm_action:
        cmd.append("--yes")

    # Log execution details
    logger.info(f"\n🧪 Running tests for: {', '.join(test_files)}")

    uid_display = f"{user_id[:8]}..." if len(user_id) > 8 else user_id
    logger.info(f"   User ID: {uid_display}")
    logger.debug(f"   Command: {' '.join(cmd)}\n")

    # Run pytest
    result = subprocess.run(cmd)
    return result.returncode


def main():
    """Main entry point."""
    args = parse_args()

    # Set log level based on verbose flag
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Resolve integration names to test files
    test_files = resolve_integrations(args.integrations)

    if not test_files:
        logger.error("No valid integrations specified.")
        logger.info("\nAvailable integrations:")
        for name in sorted(set(INTEGRATION_MAP.values())):
            aliases = [k for k, v in INTEGRATION_MAP.items() if v == name]
            logger.info(f"  {aliases[0]}: {', '.join(aliases)}")
        return 1

    # Run the tests
    return run_tests(test_files, args)


if __name__ == "__main__":
    sys.exit(main())
