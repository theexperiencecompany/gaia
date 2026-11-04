"""Playbook tools: read the run record, then write, read, decline, or disable a workflow's playbook.

A workflow keeps at most one playbook. There is no edit path and no version
history, because the agent revises by writing the whole document again, so a
write always replaces what was there and a rejected write leaves the previous
playbook untouched. A write picks its steps from the run record by call id, so
every step is a call this run really made, as it made it.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from typing import Annotated, Any

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import BeforeValidator, ValidationError
from pydantic.v1 import ValidationError as LegacyValidationError

from app.agents.tools.execute.unwrap import unwrap_execute_call
from app.agents.tools.run_record import read_run_record as read_recorded_calls
from app.agents.tools.todo_tools import TODO_TOOL_NAMES
from app.constants.agents import PLAYBOOK_TOOL_NAMES, PLAYBOOK_UNPICKABLE_TOOLS
from app.constants.execute import ACTIVATE_INTEGRATION_TOOL_NAME
from app.constants.log_tags import LogTag
from app.db.repositories.playbooks import playbook_repository
from app.db.repositories.workflows import workflow_repository
from app.models.agent_models import get_user_id
from app.models.playbook_models import (
    BLOCKED_DECLINE_KINDS,
    INTEGRATION_DECLINE_KINDS,
    DeclineKind,
    PlaybookDocument,
    PlaybookRunStatus,
    is_work_call,
)
from app.models.workflow_models import WorkflowDocument, WorkflowUpdate
from app.services.workflow.playbook.lifecycle import HEAL_STATUSES
from app.services.workflow.playbook.parser import (
    PlaybookIssue,
    dump_playbook,
    validate_playbook,
)
from app.services.workflow.playbook.record import (
    PlaybookPick,
    RecordEntry,
    build_playbook,
    record_entries,
    render_record,
)
from app.services.workflow.playbook.workflow_hash import workflow_hash
from app.utils.json_args import decode_json_container
from app.utils.workflow_utils import (
    WorkflowConfigError,
    error_response,
    get_stream_id,
    get_workflow_id,
    success_response,
)
from shared.py.wide_events import log


def _render_location(location: tuple[int | str, ...]) -> str:
    """One pydantic error location as the author wrote it: ``steps[0].call``."""
    rendered = ""
    for part in location:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += f".{part}" if rendered else str(part)
    return rendered or "arguments"


def _explain_validation_error(error: ValidationError | LegacyValidationError) -> str:
    """Hand a rejected call back as an answer the author can act on.

    Without this, arguments that miss the schema come back as a framework-level
    error the model cannot read, and it retries the same shape. Reported as the
    tool's own ``error_response`` so a bad shape and a bad playbook read
    identically: what was wrong, and that nothing was written.

    Both pydantic generations are accepted because that is the signature
    langchain's hook declares; either one reports ``loc``/``msg`` the same way.
    """
    problems = "; ".join(
        f"{_render_location(item['loc'])}: {item['msg']}" for item in error.errors()
    )
    return json.dumps(
        error_response(
            "invalid_playbook",
            "The playbook was not written. Fix these and call write_playbook again: " + problems,
        )
    )


def _activated_integrations(state: Mapping[str, Any] | None) -> list[str]:
    """The integrations this run activated, in order, each once.

    A blocked-run claim is held to this: activation is how a run reaches an
    integration, and where an unconnected one shows its connect card, so a run
    that never activated Slack cannot have been blocked on Slack.
    """
    if state is None:
        return []
    messages = state.get("messages")
    if not isinstance(messages, list):
        return []
    targets = [
        (call.get("args") or {}).get("integration_id")
        for message in messages
        for call in getattr(message, "tool_calls", None) or []
        if call.get("name") == ACTIVATE_INTEGRATION_TOOL_NAME
    ]
    return [str(target) for target in dict.fromkeys(targets) if target]


def _invoked_call_names(state: Mapping[str, Any] | None) -> list[str]:
    """Every tool the run has called so far, answered or still in flight, seen through execute.

    The quiet-day check reads this rather than the run record: a model can
    issue ``create_todo`` and the decline in one parallel batch, and the create
    has not finished (so is not recorded) when the decline is judged.
    """
    if state is None:
        return []
    messages = state.get("messages")
    if not isinstance(messages, list):
        return []
    return [
        unwrap_execute_call(str(call["name"]), dict(call.get("args") or {}))[0]
        for message in messages
        for call in getattr(message, "tool_calls", None) or []
        if call.get("name")
    ]


async def _pickable_record(config: RunnableConfig) -> list[RecordEntry]:
    """Return this run's calls a playbook may replay, each with its id.

    A heal run's record opens with the stopped replay's calls (the worker seeds
    them), so a rewrite can keep a step the replay already ran.
    """
    return record_entries(await read_recorded_calls(get_stream_id(config)), _UNPICKABLE_TOOLS)


def _refused(issues: list[PlaybookIssue], workflow_id: str) -> dict[str, Any]:
    """Return the refusal for a write, every issue with where it is."""
    problems = "; ".join(f"{issue.where}: {issue.problem}" for issue in issues)
    log.warning(
        f"{LogTag.TOOL} write_playbook: rejected — "
        + "; ".join(f"{issue.where}: {issue.problem}" for issue in issues[:5]),
        issues=len(issues),
        workflow_id=workflow_id,
    )
    return error_response(
        "invalid_playbook",
        "The playbook was not written. Fix these and call write_playbook again: " + problems,
    )


@tool
async def read_run_record(config: RunnableConfig) -> dict[str, Any]:
    """
    List the tool calls this run has made, each with its id, to pick a playbook's steps from.

    Each call shows its id (its tool and which of that tool's calls it is, e.g.
    GMAIL_FETCH_EMAILS#1), the args it was sent and the shape of what it
    returned: the keys a $steps reference can read. Call this right before
    write_playbook; a playbook's steps are these ids, copied exactly.
    """
    try:
        workflow_id = get_workflow_id(config)
    except WorkflowConfigError as e:
        return error_response("not_in_workflow_run", str(e))
    log.set(tool={"name": "read_run_record", "action": "read"}, workflow_id=workflow_id)
    record = await _pickable_record(config)
    log.set_ns("playbook", record_calls=len(record))
    if not record:
        return success_response(
            {"calls": []},
            "This run has made no call a playbook can replay, so there is nothing to freeze.",
        )
    return success_response({"calls": render_record(record)})


@tool
async def write_playbook(
    config: RunnableConfig,
    description: Annotated[str, "What this playbook does, in one or two lines."],
    # Models often JSON-encode this list (prod: 7 refused writes); the schema stays an array.
    steps: Annotated[
        list[PlaybookPick],
        BeforeValidator(decode_json_container),
        "The calls from read_run_record that did the work, by their id: never "
        "discovery, dead ends or retries. Each step replays its call exactly as "
        "recorded, except the values you mark in vary.",
    ],
    result_brief: Annotated[
        str,
        "How to write the run's result for the user from the steps' results. "
        "Classification, judgement and summarising go here.",
    ],
) -> dict[str, Any]:
    """
    Freeze calls this workflow run made as its playbook, so later runs replay
    them instead of reasoning the work out again. Pick the calls by their id in
    read_run_record, copied exactly, and mark the values that change per run; the tool and every
    other argument come from the record. The playbook attaches
    to the workflow this run is executing; there is no id to supply.

    Nothing is written if a pick is wrong (an id that is not in the record, a
    path the call does not have, a $steps reference to a field its call did not
    return) or if it drops an action the previous playbook took for the user; the
    problems come back so you can fix them and call this again. A successful
    write replaces the workflow's previous playbook entirely.

    Only write a playbook when the same calls would do the work tomorrow with
    only the marked values changed. A run whose calls depend on what it finds is
    not a playbook.
    """
    try:
        workflow_id = get_workflow_id(config)
    except WorkflowConfigError as e:
        return error_response("not_in_workflow_run", str(e))
    log.set(tool={"name": "write_playbook", "action": "write"}, workflow_id=workflow_id)
    try:
        user_id = get_user_id(config)
        workflow = await workflow_repository.get_for_user(workflow_id, user_id)
        if workflow is None:
            return error_response("workflow_not_found", f"No workflow {workflow_id} for this user.")

        record = await _pickable_record(config)
        stored = await playbook_repository.get_for_workflow(workflow_id, user_id)
        built = build_playbook(
            description,
            steps,
            result_brief,
            record,
            replaces=stored.steps if stored is not None else (),
        )
        log.set_ns("playbook", record_calls=len(record), picks=len(steps))
        if built.body is None:
            return _refused(built.issues, workflow_id)
        validation = await validate_playbook(built.body, built.sources)
        if not validation.valid:
            return _refused(validation.issues, workflow_id)
        body = built.body

        now = datetime.now(UTC)
        stored = await playbook_repository.upsert_for_workflow(
            PlaybookDocument(
                workflow_id=workflow_id,
                user_id=user_id,
                workflow_hash=workflow_hash(workflow.prompt, workflow.steps),
                authored_run=get_stream_id(config),
                created_at=now,
                updated_at=now,
                description=body.description,
                steps=body.steps,
                result_brief=body.result_brief,
            )
        )
        # A written playbook supersedes the discard that recorded why the last one
        # was thrown away.
        await workflow_repository.update_for_user(
            workflow_id, user_id, WorkflowUpdate(last_playbook_discard=None)
        )
        log.set_ns("playbook", id=stored.playbook_id, steps=len(stored.steps))
        return success_response(
            {"playbook_id": stored.playbook_id, "steps": len(stored.steps)},
            "Playbook written. Later runs of this workflow replay it.",
        )
    except Exception as e:
        log.error(
            f"{LogTag.TOOL} write_playbook: exception", error_type=type(e).__name__, exc_info=True
        )
        return error_response("write_failed", str(e))


#: Arguments that miss the schema never reach the body above — langchain raises
#: before the coroutine runs — so the explanation is attached to the tool rather
#: than written as a try/except inside it.
write_playbook.handle_validation_error = _explain_validation_error


@tool
async def read_playbook(
    config: RunnableConfig,
) -> dict[str, Any]:
    """
    Read back this workflow's playbook: the YAML as written, when it was written,
    and whether the most recent run replayed it or fell back to reasoning.

    Read before revising, so you edit the document that exists rather than
    guessing at it.
    """
    try:
        workflow_id = get_workflow_id(config)
    except WorkflowConfigError as e:
        return error_response("not_in_workflow_run", str(e))
    log.set(tool={"name": "read_playbook", "action": "read"}, workflow_id=workflow_id)
    try:
        user_id = get_user_id(config)
        playbook = await playbook_repository.get_for_workflow(workflow_id, user_id)
        if playbook is None:
            return success_response(
                {"exists": False},
                f"Workflow {workflow_id} has no playbook yet.",
            )
        return success_response(
            {
                "exists": True,
                "yaml": dump_playbook(playbook),
                "written_at": playbook.updated_at.isoformat(),
                "last_run_used_it": playbook.last_run_status is not PlaybookRunStatus.NOT_RUN,
                "last_run_status": playbook.last_run_status.value,
            }
        )
    except Exception as e:
        log.error(
            f"{LogTag.TOOL} read_playbook: exception", error_type=type(e).__name__, exc_info=True
        )
        return error_response("read_failed", str(e))


async def _record_blocked_run(
    workflow_id: str,
    user_id: str,
    kind: DeclineKind,
    integrations: list[str],
    *,
    used_by_run: list[str],
) -> dict[str, Any]:
    """Settle a run that never reached the work.

    The stored playbook is deliberately left alone even mid-heal: a heal run that
    could not run at all has learned nothing about whether the frozen sequence
    still holds, and deleting it would throw away a working shortcut over a
    disconnected account.
    """
    # Deferred: integration_pause reaches WorkflowService, which pulls the
    # generation service and the whole LLM client stack behind it. A tools module
    # imported by the registry must not carry that at import time.
    from app.services.workflow.integration_pause import (  # noqa: PLC0415 -- deferred
        pause_workflow_for_missing_integrations,
    )

    log.set_ns("playbook", blocked=True, blocked_integrations=integrations)
    if kind not in INTEGRATION_DECLINE_KINDS:
        return success_response(
            {"declined": True, "blocked": True},
            "Noted — this run never reached the work. It will be asked again on a run that "
            "gets further.",
        )

    outcome = await pause_workflow_for_missing_integrations(
        workflow_id, user_id, integrations, used_by_run=used_by_run
    )
    if outcome.unrelated:
        # The run's own record says otherwise: neither the workflow's steps nor
        # this run's activations involve what it named. Refused, not recorded, so
        # the model re-decides with the integration it actually needed.
        named = ", ".join(outcome.unrelated)
        return error_response(
            "integration_not_in_run",
            f"{named} {'is' if len(outcome.unrelated) == 1 else 'are'} not part of this "
            "workflow's steps and this run never activated it. Name the integration "
            "the run actually needed, or decline with the kind that says why the "
            "sequence cannot hold.",
        )
    paused = outcome.paused
    if not paused:
        # The claim did not check out. Say so rather than pausing on it.
        return success_response(
            {"declined": True, "blocked": True, "paused": False},
            "Noted, but those integrations look connected from here, so the workflow is "
            "still active.",
        )
    return success_response(
        {
            "declined": True,
            "blocked": True,
            "paused": True,
            "integrations": paused,
        },
        f"Noted. This workflow is paused until {', '.join(paused)} "
        f"{'is' if len(paused) == 1 else 'are'} connected, and resumes by itself then.",
    )


@tool
async def decline_playbook(
    config: RunnableConfig,
    kind: Annotated[
        DeclineKind,
        "Which of the five cases this is. There is no member for 'the arguments "
        "differed', because placeholders already carry those, and none for 'the "
        "number of calls differed', which is what a for_each step is for.",
    ],
    reason: Annotated[str, "The specifics, in your own words."],
    integrations: Annotated[
        list[str] | None,
        "Required for blocked_missing_integration and blocked_auth_expired: the "
        "integration ids the run found unusable, e.g. ['github', 'slack'].",
    ] = None,
    branch_on: Annotated[
        str | None,
        "Required for order_branches: the ONE call that runs on some days and "
        "not others. If you cannot name such a call, the order does not branch.",
    ] = None,
    state: Annotated[dict[str, Any] | None, InjectedState] = None,
) -> dict[str, Any]:
    """
    Record that this run's sequence is not worth freezing as a playbook.

    Calling this is how you say no: a run asked to decide must end by calling
    exactly one of write_playbook or decline_playbook, so a missing decision is
    visible instead of looking identical to a considered no.

    A ``blocked_*`` kind is not really a no. It says the run never reached the
    work, so there was no sequence to judge: nothing is counted against the
    workflow, and if it names integrations that are genuinely not connected the
    workflow is paused until the user connects them.
    """
    try:
        workflow_id = get_workflow_id(config)
    except WorkflowConfigError as e:
        return error_response("not_in_workflow_run", str(e))
    log.set(tool={"name": "decline_playbook", "action": "decline"}, workflow_id=workflow_id)
    log.set_ns("playbook", declined=True, decline_kind=kind.value, decline_reason=reason)

    refused = _decline_request_problem(kind, integrations, branch_on)
    if refused is not None:
        return refused

    try:
        user_id = get_user_id(config)
        workflow = await workflow_repository.get_for_user(workflow_id, user_id)
        if workflow is None:
            return error_response("workflow_not_found", f"No workflow {workflow_id} for this user.")
        return await _record_decline(
            workflow,
            kind=kind,
            reason=reason,
            integrations=integrations,
            state=state,
            config=config,
        )
    except Exception as e:
        log.error(
            f"{LogTag.TOOL} decline_playbook: exception", error_type=type(e).__name__, exc_info=True
        )
        return error_response("decline_failed", str(e))


def _decline_request_problem(
    kind: DeclineKind, integrations: list[str] | None, branch_on: str | None
) -> dict[str, Any] | None:
    """The refusal for a decline whose kind needs a detail the call did not give."""

    if kind in INTEGRATION_DECLINE_KINDS and not integrations:
        return error_response(
            "integrations_required",
            f"{kind.value} has to name the integrations the run could not use. "
            "Call decline_playbook again with integrations=[...].",
        )
    if kind is DeclineKind.ORDER_BRANCHES and not (branch_on or "").strip():
        return error_response(
            "branch_on_required",
            "order_branches has to name the one call that runs on some days and not others, "
            "as branch_on. If every call you made happens every run and only their arguments "
            "differ, the order does not branch — use placeholders and call write_playbook. If "
            "only the NUMBER of times a call repeats differs, that is a for_each step, not a "
            "decline.",
        )
    return None


async def _record_decline(
    workflow: WorkflowDocument,
    *,
    kind: DeclineKind,
    reason: str,
    integrations: list[str] | None,
    state: Mapping[str, Any] | None,
    config: RunnableConfig,
) -> dict[str, Any]:
    """What one well-formed decline means for the workflow, by its kind.

    A blocked run pauses, a quiet day is checked against the run's own calls, and
    a decline inside a heal run removes the playbook that failed. Nothing is
    counted: the workflow is asked again on its next run until it has a playbook.
    """
    workflow_id, user_id = workflow.id, workflow.user_id
    if kind in BLOCKED_DECLINE_KINDS:
        return await _record_blocked_run(
            workflow_id,
            user_id,
            kind,
            integrations or [],
            used_by_run=_activated_integrations(state),
        )
    if kind is DeclineKind.NO_WORK_TODAY:
        # The claim is checked against the run's own record, not taken on
        # trust: a run that made a doing-call had work to freeze.
        worked = [
            name
            for name in _invoked_call_names(state)
            if name not in _RUN_BOOKKEEPING_TOOLS and is_work_call(name)
        ]
        if worked:
            return error_response(
                "work_happened",
                f"This run called {', '.join(sorted(set(worked)))}, so the work happened "
                "today. Freeze it with write_playbook, or decline with the kind that "
                "says why the sequence cannot hold.",
            )
        # The work never happened, so there was nothing to freeze.
        log.set_ns("playbook", quiet_day=True)
        return success_response(
            {"declined": True},
            "Noted: nothing to freeze on a day the work did not happen. The next run is "
            "asked again.",
        )

    playbook = await playbook_repository.get_for_workflow(workflow_id, user_id)
    if playbook is not None and playbook.authored_run == get_stream_id(config):
        # Seen on the real model: a valid write, then a decline in the same
        # turn. The write was checked against the run and stored; the
        # decline is a second voice of a decision already made.
        return success_response(
            {"declined": True},
            "This run already wrote a playbook, and that is its decision; nothing to record.",
        )

    # A decline inside a heal run is the agent saying the stored sequence
    # cannot hold. Leaving it FAILED/SUSPECT would brief every later fire
    # to heal it again.
    if playbook is not None and playbook.last_run_status in HEAL_STATUSES:
        await playbook_repository.delete_for_workflow(workflow_id, user_id)
        log.set_ns("playbook", disabled=True, reason=reason)
        return success_response(
            {"declined": True, "disabled": True},
            "Noted. The stored playbook was removed; the next run reasons it out and is "
            "asked again.",
        )
    return success_response(
        {"declined": True},
        "Noted. This run reasons it out; the next run is asked again.",
    )


@tool
async def disable_playbook(
    config: RunnableConfig,
    reason: Annotated[str, "Why this sequence no longer holds. Be specific."],
) -> dict[str, Any]:
    """
    Delete this workflow's playbook so its runs go back to being reasoned out.

    Use this when the frozen order stopped matching reality and you cannot write
    a correct replacement, for example the run now depends on what it finds.
    """
    try:
        workflow_id = get_workflow_id(config)
    except WorkflowConfigError as e:
        return error_response("not_in_workflow_run", str(e))
    log.set(tool={"name": "disable_playbook", "action": "disable"}, workflow_id=workflow_id)
    try:
        user_id = get_user_id(config)
        removed = await playbook_repository.delete_for_workflow(workflow_id, user_id)
        if not removed:
            # Not a decision: there was nothing to decide about. A briefed run
            # that has no playbook must write or decline, not disable air.
            return error_response(
                "nothing_to_disable",
                f"Workflow {workflow_id} has no playbook. Call write_playbook or "
                "decline_playbook instead.",
            )
        log.set_ns("playbook", disabled=True, reason=reason)
        return success_response(
            {"disabled": True}, "Playbook removed. This workflow reasons out every run again."
        )
    except Exception as e:
        log.error(
            f"{LogTag.TOOL} disable_playbook: exception", error_type=type(e).__name__, exc_info=True
        )
        return error_response("disable_failed", str(e))


tools = [read_run_record, write_playbook, read_playbook, decline_playbook, disable_playbook]

#: The run tracking its own plan and deciding its playbook: never the workflow's work.
_RUN_BOOKKEEPING_TOOLS = frozenset(TODO_TOOL_NAMES | PLAYBOOK_TOOL_NAMES)
#: Calls a playbook step can never be.
_UNPICKABLE_TOOLS = _RUN_BOOKKEEPING_TOOLS | PLAYBOOK_UNPICKABLE_TOOLS
