"""Voice agent CLI entrypoint."""

import sys


def main():
    """Main entrypoint for voice-agent CLI."""
    if len(sys.argv) < 2:
        print("Usage: python -m src <command>")
        print("Commands: start, download-files")
        sys.exit(1)

    command = sys.argv[1]

    try:
        if command == "download-files":
            from src.worker import download_files

            download_files()
        elif command == "start":
            from src.worker import start_worker

            start_worker()
        else:
            print(f"Unknown command: {command}")
            sys.exit(1)

    except Exception as e:
        print(f"Error executing command '{command}': {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
