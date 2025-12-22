"""Voice agent CLI entrypoint."""

import sys


def main():
    """
    Entry point for the voice-agent command-line interface.
    
    Parses the first positional argument as a subcommand and dispatches:
    - "download-files": import and run src.worker.download_files()
    - "start": import and run src.worker.start_worker()
    
    If no subcommand is provided, prints usage and exits with status 1. If the subcommand is unrecognized, prints an error and exits with status 1.
    """
    if len(sys.argv) < 2:
        print("Usage: python -m src <command>")
        print("Commands: start, download-files")
        sys.exit(1)

    command = sys.argv[1]

    if command == "download-files":
        from src.worker import download_files

        download_files()
    elif command == "start":
        from src.worker import start_worker

        start_worker()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()