"""Entry point of the browser stack's API and worker processes.

Run as ``python -m tests.integration.real.browser._stack.serve api <port>`` or
``... serve worker`` from apps/api, with the stack's environment. Every setting
comes from that environment at import, as in production; the worker serves only
the browser queue, since the main worker's other tasks are not on a browser
task's path.
"""

from __future__ import annotations

import asyncio
import importlib
import sys


def main() -> None:
    """Apply the third-party patches before anything imports what they patch, as main.py and worker.py do, then serve."""
    importlib.import_module("app.patches")
    boot = importlib.import_module("tests.integration.real.browser._stack.boot")
    role = sys.argv[1]
    if role == "api":
        boot.serve_api(int(sys.argv[2]))
    elif role == "worker":
        asyncio.run(boot.serve_browser_queue())
    else:
        raise SystemExit(f"unknown stack process {role!r}: expected api or worker")


if __name__ == "__main__":
    main()
