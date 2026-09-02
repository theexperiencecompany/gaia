"""run_code — code mode: a sandbox script that calls GAIA tools via execute.

The script runs in the user's E2B sandbox; its only door back into GAIA is the
/sandbox/execute route, reached with a short-lived HMAC token minted here AFTER
the whole-script approval gate clears (run_code is registry-stamped
always_gate). Credentials never enter the sandbox.
"""

import json
from typing import Annotated
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.coding._context import get_session_id, get_user_id, safe_emit
from app.config.settings import settings
from app.constants.execute import (
    RUN_CODE_OUTPUT_MAX_CHARS,
    RUN_CODE_TIMEOUT_SECONDS,
    RUN_CODE_TOKEN_TTL_SECONDS,
)
from app.constants.log_tags import LogTag
from app.models.agent_models import agent_configurable
from app.services.sandbox import acquire_sandbox
from app.services.sandbox.execute_token import mint_execute_token
from app.utils.output_limiter import truncate_head_tail
from shared.py.wide_events import log

# Stdlib-only client written into the script's workdir. Kept as source (not a
# packaged dep) so it needs no template rebuild and no network install.
GAIA_SANDBOX_CLIENT_SOURCE = '''\
"""GAIA sandbox tool client. Usage: from gaia import execute"""
import json
import os
import urllib.request


class GaiaToolError(RuntimeError):
    """A tool call the host refused or failed to validate; str() carries the detail."""


def execute(tool_name: str, data: dict | None = None):
    """Run a GAIA tool. Returns the parsed JSON result or raises GaiaToolError."""
    request = urllib.request.Request(
        os.environ["GAIA_EXECUTE_URL"],
        data=json.dumps({"tool_name": tool_name, "data": data or {}}).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + os.environ["GAIA_EXECUTE_TOKEN"],
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode())
    if not body.get("ok"):
        raise GaiaToolError(json.dumps(body.get("error"), indent=2))
    return body["output"]
'''


@tool
async def run_code(
    config: RunnableConfig,
    script: Annotated[
        str,
        "A complete Python 3.11 script. It may call GAIA integration tools via "
        "`from gaia import execute`; execute(tool_name, data) returns the tool's "
        "parsed JSON output or raises GaiaToolError with the validation detail. "
        "print() what you need to see; stdout/stderr come back to you.",
    ],
) -> str:
    """Run a Python script in your sandbox that can call GAIA integration tools.

    Use for multi-step integration work: fetch once, filter/compute in Python,
    act, and print a concise summary. Avoid printing large raw payloads. Each
    run is a fresh process (no state carries over). The user approves the whole
    script before it runs; a declined run means rethink, not resubmit.
    """
    if not settings.SANDBOX_EXECUTE_TOKEN_SECRET or not settings.SANDBOX_EXECUTE_CALLBACK_URL:
        return (
            "run_code is not available: code mode is not configured on this "
            "deployment (SANDBOX_EXECUTE_TOKEN_SECRET / SANDBOX_EXECUTE_CALLBACK_URL). "
            "Complete the task with execute() calls instead."
        )
    user_id = get_user_id(config)
    session_id = get_session_id(config)
    stream_id = agent_configurable(config).get("stream_id")
    run_id = str(uuid4())
    token = mint_execute_token(
        user_id,
        run_id,
        stream_id=stream_id,
        ttl_seconds=RUN_CODE_TOKEN_TTL_SECONDS,
    )
    workdir = f"/tmp/gaia-run-{run_id}"
    log.set_ns("run_code", run_id=run_id, script_chars=len(script))

    def _stream(kind: str) -> object:
        def _on_chunk(chunk: str) -> None:
            safe_emit(
                {"bash_data": {"id": run_id, "status": "running", "stream": kind, "chunk": chunk}},
                session_id=session_id,
            )

        return _on_chunk

    async with acquire_sandbox(user_id) as sbx:
        await sbx.files.write(f"{workdir}/gaia.py", GAIA_SANDBOX_CLIENT_SOURCE)
        await sbx.files.write(f"{workdir}/script.py", script)
        result = await sbx.commands.run(
            "python3 script.py",
            cwd=workdir,
            envs={
                "GAIA_EXECUTE_URL": settings.SANDBOX_EXECUTE_CALLBACK_URL,
                "GAIA_EXECUTE_TOKEN": token,
            },
            on_stdout=_stream("stdout"),
            on_stderr=_stream("stderr"),
            timeout=RUN_CODE_TIMEOUT_SECONDS,
        )

    exit_code = getattr(result, "exit_code", None)
    half_cap = RUN_CODE_OUTPUT_MAX_CHARS // 2
    stdout = truncate_head_tail(getattr(result, "stdout", "") or "", half_cap, half_cap)
    stderr = truncate_head_tail(getattr(result, "stderr", "") or "", half_cap, half_cap)
    log.info(f"{LogTag.TOOL} run_code finished", run_id=run_id, exit_code=exit_code)
    return json.dumps({"exit_code": exit_code, "stdout": stdout, "stderr": stderr})
