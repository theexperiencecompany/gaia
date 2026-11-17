"""Run the post-deploy step (scripts/post_deploy.py) once per worker start, beside the worker.

It runs as its own process from the api directory, so app code never imports the
one-off migrations and a slow step never holds the worker's boot. A step that fails
leaves its exit code and output in a failed post_deploy event; its markers let the
next worker start retry exactly what is still pending.
"""

import asyncio
from pathlib import Path
import sys

from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log, log_context

#: apps/api: where `python -m scripts.post_deploy` resolves, in a checkout and in the image.
_API_ROOT = Path(__file__).resolve().parents[3]
#: The tail of the step's output kept on its event when it fails.
_FAILURE_OUTPUT_CHARS = 4000


async def _run_post_deploy() -> None:
    async with log_context("post_deploy", component="arq_lifecycle"):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "scripts.post_deploy",
            "--apply",
            cwd=_API_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        log.set_ns("post_deploy", exit_code=process.returncode)
        if process.returncode != 0:
            log.error(
                "post_deploy.failed",
                exit_code=process.returncode,
                output=output.decode(errors="replace")[-_FAILURE_OUTPUT_CHARS:],
            )


def start_post_deploy() -> None:
    """Start the post-deploy step in the background of this worker."""
    spawn_background_task(_run_post_deploy(), name="post_deploy")
