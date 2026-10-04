"""Private agent-lab orchestration: seed a per-run sandbox workdir, relay messages, stop runs.

Thin relay only — the model drives the CLIs itself via bash per the drive
skills; these tools seed the workdir, persist the run id plus the CLI-native
session id on the tracked todo's references, and record activity. One run's
entries are the bare ``run_id`` (receiver shape) plus
``lab:<run_id>:<cli_session_id>`` (routing shape for message/stop).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from e2b import AsyncSandbox, CommandExitException
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.coding._context import get_user_id, sh_quote
from app.constants.log_tags import LogTag
from app.constants.todos import TodoActivityEvent
from app.db.repositories.todos import todo_repository
from app.models.agent_models import agent_configurable
from app.models.todo_models import TodoDocument
from app.services.agent_lab.sandbox_setup import (
    build_seed_command,
    lab_events_url,
    mint_lab_hooks_token,
)
from app.services.feature_flags import is_agent_lab_enabled
from app.services.sandbox import SandboxAcquisitionError, acquire_sandbox
from app.services.todo_activity import record_activity
from shared.py.wide_events import log

#: Every tool in this module, for the registry category and the retrieval gate.
LAB_TOOL_NAMES: tuple[str, str, str] = ("lab_start", "lab_message", "lab_stop")

#: Routing entry in a todo's references: ``lab:<run_id>:<cli_session_id>``.
LAB_REF_PREFIX: str = "lab:"

#: Parent dir for per-run workdirs; one run owns exactly one subdir.
LAB_RUN_DIR_PREFIX: str = "/workspace/.gaia/lab"

#: Seed runs CLI installs, so allow time for a cold download.
LAB_SEED_TIMEOUT_SECONDS: int = 300

#: Probe budget for `opencode session list` - a local index read, never agent work.
LAB_SESSION_PROBE_TIMEOUT_SECONDS: int = 30

#: Bound for the resume turn so a wedged CLI cannot hang the relay forever.
LAB_RESUME_TIMEOUT_SECONDS: int = 600

#: Bound for the stop signal so a wedged sandbox cannot hang the tool.
LAB_STOP_TIMEOUT_SECONDS: int = 15

#: Stderr tail kept in user-facing errors; the full stream stays in the sandbox.
LAB_STDERR_TAIL_CHARS: int = 2000
LAB_SHORT_STDERR_TAIL_CHARS: int = 1000

#: Text kept in a todo's activity entry; the full reply lives in the inbox file.
LAB_ACTIVITY_TEXT_CHARS: int = 200

LAB_DISABLED_MESSAGE: str = (
    "Agent lab is not enabled for this user. Tell the user agent lab is off "
    "and stop - do not retry, do not work around it."
)


@dataclass(frozen=True)
class _LabRun:
    todo_id: str
    todo_title: str
    run_id: str
    cli_session_id: str
    run_dir: str


def _run_dir(run_id: str) -> str:
    return f"{LAB_RUN_DIR_PREFIX}/{run_id}"


def _routing_ref(run_id: str, cli_session_id: str) -> str:
    return f"{LAB_REF_PREFIX}{run_id}:{cli_session_id}"


def parse_lab_routing_ref(entry: str) -> tuple[str, str] | None:
    """Split a ``lab:<run_id>:<cli_session_id>`` entry; None for anything else."""
    if not entry.startswith(LAB_REF_PREFIX):
        return None
    _, _, rest = entry.partition(":")
    run_id, sep, cli_session_id = rest.partition(":")
    if not sep or not run_id or not cli_session_id:
        return None
    return run_id, cli_session_id


def _latest_routing_ref(references: list[str]) -> tuple[str, str] | None:
    """The run's routing entry: the last ``lab:`` entry wins, earlier runs are history."""
    for entry in reversed(references):
        parsed = parse_lab_routing_ref(entry)
        if parsed is not None:
            return parsed
    return None


async def _resolve_run(config: RunnableConfig, user_id: str, todo_id: str | None) -> _LabRun | str:
    """Load the todo and its latest lab run; error string when there is nothing to route to."""
    resolved_todo_id = todo_id or agent_configurable(config).get("active_todo_id")
    if not resolved_todo_id:
        return (
            "No tracked todo is bound to this run. Ask the user which todo this "
            "lab work belongs to then call again with its todo id."
        )
    todo: TodoDocument | None = await todo_repository.get(resolved_todo_id, user_id=user_id)
    if todo is None:
        return (
            "That todo does not exist or belongs to someone else. Ask the user "
            "which of their tracked todos to use."
        )
    routed = _latest_routing_ref(todo.references)
    if routed is None:
        return f'The todo "{todo.title}" has no lab run yet. Start one with lab_start first.'
    run_id, cli_session_id = routed
    return _LabRun(
        todo_id=todo.id,
        todo_title=todo.title,
        run_id=run_id,
        cli_session_id=cli_session_id,
        run_dir=_run_dir(run_id),
    )


async def _seed_run_workdir(user_id: str, run_id: str, run_dir: str) -> str | None:
    """Seed hooks + plugin + env into the run workdir; error string on failure."""
    try:
        token = mint_lab_hooks_token(user_id, run_id)
        seed = build_seed_command(lab_events_url(), token, run_id, run_dir)
    except Exception as e:
        log.error(f"{LogTag.TOOL} lab_start seed build failed", error_type=type(e).__name__)
        return f"Error: could not prepare the lab run ({e})."
    try:
        async with acquire_sandbox(user_id) as sbx:
            try:
                await sbx.commands.run(seed, timeout=LAB_SEED_TIMEOUT_SECONDS)
            except CommandExitException as e:
                log.error(f"{LogTag.TOOL} lab_start seed failed", error_type=type(e).__name__)
                return (
                    "Error: seeding the lab workdir failed in the sandbox "
                    f"(exit {e.exit_code}): {(e.stderr or '').strip()[-LAB_STDERR_TAIL_CHARS:]}"
                )
    except SandboxAcquisitionError as e:
        return f"Error: sandbox unavailable ({e})"
    except Exception as e:
        log.error(f"{LogTag.TOOL} lab_start failed", error_type=type(e).__name__)
        return f"Error: could not start the lab run ({e})."
    return None


@tool
async def lab_start(
    config: RunnableConfig,
    task: Annotated[str, "What the sandbox CLI should do, in one or two sentences."],
    active_todo_id: Annotated[
        str | None,
        "REQUIRED: the tracked todo this run belongs to. Never start a lab run without one.",
    ] = None,
) -> str:
    """Start a Claude/OpenCode run in the user's sandbox, linked to a tracked todo."""
    log.set(tool={"name": "lab_start", "action": "start"})
    try:
        user_id = get_user_id(config)
    except ValueError as e:
        return f"Error: {e}"
    if not await is_agent_lab_enabled(user_id):
        return LAB_DISABLED_MESSAGE
    if not task or not task.strip():
        return "Error: task cannot be empty. Say what the sandbox CLI should do."
    resolved_todo_id = active_todo_id or agent_configurable(config).get("active_todo_id")
    if not resolved_todo_id:
        return (
            "Refusing to start: lab runs must link to a tracked todo and none was "
            "given. Ask the user which todo this work belongs to (or create one), "
            "then call lab_start again with its id."
        )
    todo: TodoDocument | None = await todo_repository.get(resolved_todo_id, user_id=user_id)
    if todo is None:
        return (
            "That todo does not exist or belongs to someone else. Ask the user "
            "which of their tracked todos to use."
        )

    run_id = uuid4().hex
    cli_session_id = uuid4().hex
    run_dir = _run_dir(run_id)
    seed_error = await _seed_run_workdir(user_id, run_id, run_dir)
    if seed_error is not None:
        return seed_error

    await todo_repository.add_references(
        todo.id, user_id=user_id, references=[run_id, _routing_ref(run_id, cli_session_id)]
    )
    await record_activity(
        todo.id,
        user_id,
        TodoActivityEvent.RUN_STARTED,
        f"lab run started: {task.strip()[:LAB_ACTIVITY_TEXT_CHARS]}",
    )
    log.set_ns("lab", todo_id=todo.id)
    return (
        f'Lab run seeded for todo "{todo.title}" in {run_dir}. '
        f"CLI session id (use verbatim, never invent another): {cli_session_id}. "
        "Launch ONE cli with the bash tool now, from that workdir, per its drive skill "
        '(lab-claude-drive: `claude -p "<prompt>" --output-format stream-json '
        f"--session-id {cli_session_id}`; lab-opencode-drive: `opencode run --format json "
        f'-s {cli_session_id} "<message>"`). If the CLI shows a login code or key, relay '
        "it to the user ad hoc and continue after they paste it back. "
        f'Tell the user: a coding agent is now working on "{todo.title}" - no ids, '
        "no paths, no session tokens in that message."
    )


def _lab_resume_command(cli: str, cli_session_id: str, text: str, run_dir: str) -> str:
    """CLI-native resume from the run workdir; verbatim shapes from the drive skills."""
    quoted = sh_quote(text.strip())
    if cli == "opencode":
        resume = f"opencode run -s {sh_quote(cli_session_id)} {quoted}"
    else:
        resume = f"claude --resume {sh_quote(cli_session_id)} {quoted}"
    return f"cd {sh_quote(run_dir)} && {resume}"


async def _relay_via_resume(
    sbx: AsyncSandbox, run: _LabRun, text: str, user_id: str
) -> tuple[bool, str]:
    """Probe the owning CLI and resume its session; (False, error) when the run never saw the reply."""
    # No record names the CLI (one cli_session_id covers either), so probe
    # opencode's session index: a hit names opencode, a miss means claude
    # (foreground -p sessions have no listable index). A wrong default fails
    # loudly at resume, never misdelivers.
    try:
        session_list = await sbx.commands.run(
            "opencode session list", timeout=LAB_SESSION_PROBE_TIMEOUT_SECONDS
        )
    except CommandExitException as e:
        log.warning(f"{LogTag.TOOL} lab_message CLI probe failed", error_type=type(e).__name__)
        return False, (
            "Error: reply filed to the run inbox but the CLI could not be "
            "determined (`opencode session list` failed: "
            f"{(e.stderr or '').strip()[-LAB_SHORT_STDERR_TAIL_CHARS:]}). The run has NOT seen "
            f"the reply - resume session {run.cli_session_id} by hand "
            f"from {run.run_dir}."
        )
    cli = "opencode" if run.cli_session_id in (session_list.stdout or "") else "claude"
    try:
        await sbx.commands.run(
            _lab_resume_command(cli, run.cli_session_id, text, run.run_dir),
            timeout=LAB_RESUME_TIMEOUT_SECONDS,
        )
    except CommandExitException as e:
        detail = (e.stderr or "").strip()[-LAB_STDERR_TAIL_CHARS:]
        log.warning(f"{LogTag.TOOL} lab_message resume failed", error_type=type(e).__name__)
        await record_activity(
            run.todo_id,
            user_id,
            TodoActivityEvent.LAB_MESSAGE_RELAYED,
            f"reply filed to inbox but {cli} resume failed: {detail[:LAB_ACTIVITY_TEXT_CHARS]}",
        )
        return False, (
            f"Error: reply filed to the run inbox but {cli} resume failed "
            f"(exit {e.exit_code}): {detail}. The run has NOT seen the "
            f"reply - resume session {run.cli_session_id} by hand from "
            f"{run.run_dir}."
        )
    return True, cli


@tool
async def lab_message(
    config: RunnableConfig,
    text: Annotated[str, "The reply to deliver to the sandbox run."],
) -> str:
    """Relay a user reply to the todo's latest lab run."""
    log.set(tool={"name": "lab_message", "action": "message"})
    try:
        user_id = get_user_id(config)
    except ValueError as e:
        return f"Error: {e}"
    if not await is_agent_lab_enabled(user_id):
        return LAB_DISABLED_MESSAGE
    if not text or not text.strip():
        return "Error: text cannot be empty."
    run = await _resolve_run(config, user_id, None)
    if isinstance(run, str):
        return run

    stamp = datetime.now(UTC).isoformat()
    inbox_path = f"{run.run_dir}/.gaia/inbox/{stamp}-{uuid4().hex[:8]}.md"
    try:
        async with acquire_sandbox(user_id) as sbx:
            try:
                await sbx.files.make_dir(f"{run.run_dir}/.gaia/inbox")
                await sbx.files.write(inbox_path, text.strip() + "\n")
            except CommandExitException as e:
                return f"Error: could not write the reply into the sandbox ({e})."
            delivered, result = await _relay_via_resume(sbx, run, text, user_id)
            if not delivered:
                return result
            cli = result
    except SandboxAcquisitionError as e:
        return f"Error: sandbox unavailable ({e})"
    except Exception as e:
        log.error(f"{LogTag.TOOL} lab_message failed", error_type=type(e).__name__)
        return f"Error: could not relay the reply ({e})."

    await record_activity(
        run.todo_id,
        user_id,
        TodoActivityEvent.LAB_MESSAGE_RELAYED,
        text.strip()[:LAB_ACTIVITY_TEXT_CHARS],
    )
    return (
        f'Reply delivered to the run on "{run.todo_title}" via {cli} resume '
        f"(session {run.cli_session_id}). Tell the user only that their reply was passed on."
    )


@tool
async def lab_stop(config: RunnableConfig) -> str:
    """Stop the todo's latest lab run."""
    log.set(tool={"name": "lab_stop", "action": "stop"})
    try:
        user_id = get_user_id(config)
    except ValueError as e:
        return f"Error: {e}"
    if not await is_agent_lab_enabled(user_id):
        return LAB_DISABLED_MESSAGE
    run = await _resolve_run(config, user_id, None)
    if isinstance(run, str):
        return run

    try:
        async with acquire_sandbox(user_id) as sbx:
            try:
                await sbx.commands.run(
                    f"pkill -f {sh_quote(run.cli_session_id)}", timeout=LAB_STOP_TIMEOUT_SECONDS
                )
                stopped = True
            except CommandExitException as e:
                if (e.exit_code or 0) not in (0, 1):
                    return f"Error: could not stop the run ({(e.stderr or '').strip()[-1000:]})"
                stopped = False
    except SandboxAcquisitionError as e:
        return f"Error: sandbox unavailable ({e})"
    except Exception as e:
        log.error(f"{LogTag.TOOL} lab_stop failed", error_type=type(e).__name__)
        return f"Error: could not stop the lab run ({e})."

    await record_activity(
        run.todo_id,
        user_id,
        TodoActivityEvent.RUN_FINISHED,
        "lab run stopped by user" if stopped else "lab stop: no live run process found",
    )
    detail = "stopped" if stopped else "no live process was left running"
    return (
        f'The run on "{run.todo_title}" is {detail}. '
        "Tell the user only that work on their todo has stopped."
    )


tools = [lab_start, lab_message, lab_stop]
