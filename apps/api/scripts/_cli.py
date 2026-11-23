"""The command line every dry-run-unless---apply data script takes."""

import argparse


def apply_requested(description: str | None) -> bool:
    """Parse the command line for --apply; an unknown argument exits with a usage error."""
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    return bool(parser.parse_args().apply)
