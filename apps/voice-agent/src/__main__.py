"""Voice agent CLI entrypoint."""

import sys


def main() -> None:
    """Dispatch the voice-agent CLI commands.

    Imports are deferred per command (the sanctioned inline-import exception for
    this CLI dispatcher) so ``download-files`` does not require Infisical secrets.
    Errors are left to propagate so failures surface with a full traceback.
    """
    if len(sys.argv) < 2:
        print("Usage: python -m src <command>")
        print("Commands: start, download-files")
        sys.exit(1)

    command = sys.argv[1]

    if command == "start":
        from src.worker import start_worker

        start_worker()
    elif command == "download-files":
        from src.worker import download_files

        download_files()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
