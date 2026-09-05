"""Playbook tools: write, read, decline, and disable a workflow's frozen sequence.

A workflow keeps at most one playbook. There is no edit path and no version
history, because the agent revises by writing the whole document again, so a
write always replaces what was there and a rejected write leaves the previous
playbook untouched.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import ValidationError
from pydantic.v1 import ValidationError as LegacyValidationError

from app.constants.agents import PLAYBOOK_REPLAYED_CALLS_KEY
from app.constants.log_tags import LogTag
from app.db.repositories.playbooks import playbook_repository
from app.db.repositories.workflows import workflow_repository
from app.models.playbook_models import (
    BLOCKED_DECLINE_KINDS,
    INTEGRATION_DECLINE_KINDS,
    DeclineKind,
    PlaybookDocument,
    PlaybookRunStatus,
    PlaybookStepInput,
    playbook_body_from_input,
)
from app.models.workflow_execution_models import RecordedCall, parse_result
from app.models.workflow_models import WorkflowUpdate
from app.services.workflow.playbook.check import declined_for_good
from app.services.workflow.playbook.lifecycle import HEAL_STATUSES
from app.services.workflow.playbook.parser import (
    RecordedResult,
    RunResults,
    dump_playbook,
    validate_playbook,
)
from app.services.workflow.playbook.workflow_hash import workflow_hash
from app.utils.workflow_utils import (
    WorkflowConfigError,
    error_response,
    get_stream_id,
    get_user_id,
    get_workflow_id,
    success_response,
)
from shared.py.wide_events import log


def _render_location(location: tuple[int | str, ...]) -> str:
    """One pydantic error location as the author wrote it: ``steps[0].tool``."""
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


def _answered_calls(state: Mapping[str, Any] | None) -> list[tuple[str, dict[str, Any], object]]:
    """Every tool call in the run's messages that has an answer: name, args, parsed answer.

    Failed calls are kept, unlike the handoff record's successful-only lines
    (``call_record.py``): a step frozen on a call that errored is precisely one
    of the things the validator has to catch. A call with no answer is one still
    in flight (this very tool call, in every real run) and is left out.
    """
    if state is None:
        return []
    messages = state.get("messages")
    if not isinstance(messages, list):
        return []
    answers: dict[str, object] = {}
    for message in messages:
        if isinstance(message, ToolMessage) and message.tool_call_id:
            content = message.content
            answers[message.tool_call_id] = parse_result(
                content if isinstance(content, str) else json.dumps(content, default=str)
            )
    calls: list[tuple[str, dict[str, Any], object]] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            call_id = call.get("id")
            name = str(call.get("name") or "")
            if name and call_id in answers:
                calls.append((name, dict(call.get("args") or {}), answers[call_id]))
    return calls


def _replayed_results(config: RunnableConfig) -> list[RecordedResult]:
    """The calls a stopped replay made this fire, as results a write may freeze.

    They ran, they produced their results, and the fallback brief told the agent
    not to run them again. They are this run's calls in every sense the
    validator cares about.
    """
    raw = (config.get("configurable") or {}).get(PLAYBOOK_REPLAYED_CALLS_KEY) or []
    replayed = [RecordedCall.model_validate(item) for item in raw]
    return [
        RecordedResult(
            tool_name=call.tool_name, args=call.args, result=parse_result(call.result_digest)
        )
        for call in replayed
    ]


def _run_results(state: Mapping[str, Any] | None) -> RunResults | None:
    """The authoring run's tool calls with what each one returned, in call order.

    ``None`` when there is no run to read: the dev ``/dev/executor`` route and
    the unit tests build these tools without a graph, and a playbook written
    there is validated exactly as it was before rather than refused for a run
    that was never recorded. An empty list is NOT the same answer — it means the
    run really made no calls, and a playbook freezing calls is wrong.

    Failed calls are kept, unlike the handoff record's successful-only lines
    (``call_record.py``): a step frozen on a call that errored is precisely one
    of the things the validator has to catch.
    """
    if state is None:
        return None
    messages = state.get("messages")
    if not isinstance(messages, list):
        return None
    return [
        RecordedResult(tool_name=name, args=args, result=answer)
        for name, args, answer in _answered_calls(state)
    ]


@tool
async def write_playbook(
    config: RunnableConfig,
    description: Annotated[str, "What this playbook does, in one or two lines."],
    steps: Annotated[
        list[PlaybookStepInput],
        "The calls to replay, in the order you made them: only the calls that did "
        "the work, never discovery or dead ends. Writing the result is not a step; "
        "that is what result_brief is for.",
    ],
    result_brief: Annotated[
        str,
        "How to write the run's result for the user from the steps' results. "
        "Classification, judgement and summarising go here.",
    ],
    #: The run's own messages, injected by the graph and absent from the schema
    #: the model sees. Defaulted because a tool built without a graph (the dev
    #: executor route, the unit tests) is called with arguments only.
    state: Annotated[dict[str, Any] | None, InjectedState] = None,
) -> dict[str, Any]:
    """
    Freeze this workflow run's settled tool sequence as a playbook, so later runs
    execute it instead of reasoning it out again. The playbook attaches to the
    workflow this run is executing; there is no id to supply.

    The steps are checked against the real tools AND against what this run's
    calls actually returned before anything is stored: if a tool or an argument
    does not exist, if a step froze a call this run never made or one that came
    back empty, or if a $steps reference reads a field the result does not have,
    NOTHING is written and the problems come back so you can fix them and call
    this again. A successful write replaces the workflow's previous playbook
    entirely, which is also how you revise one.

    Only write a playbook when the same order of calls would work tomorrow
    unchanged. A run whose order depends on what it finds is not a playbook.
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

        try:
            body = playbook_body_from_input(description, steps, result_brief)
        except ValueError as e:
            # A shape the body cannot take (a for_each without its ceiling) is
            # an authoring error like a bad reference: refused, not raised.
            return error_response("invalid_playbook", f"The playbook was not written. {e}")

        results = _run_results(state)
        if results is not None:
            # The replay's calls come first: they ran before anything the agent did.
            results = [*_replayed_results(config), *results]
        # On the wide event because it is the one thing a rejected-or-accepted
        # write cannot show from its outcome: whether the run's own results
        # were in hand (None: no graph state reached the tool at all).
        log.set_ns("playbook", checked_against_calls=None if results is None else len(results))
        validation = await validate_playbook(body, user_id, results)
        if not validation.valid:
            # The issues themselves, not just how many. A refused playbook is
            # diagnosed from the reason, and a count in a structured field that
            # the console format drops tells whoever is watching nothing at all.
            log.warning(
                f"{LogTag.TOOL} write_playbook: rejected — "
                + "; ".join(f"{issue.where}: {issue.problem}" for issue in validation.issues[:5]),
                issues=len(validation.issues),
                workflow_id=workflow_id,
            )
            return error_response(
                "invalid_playbook",
                "The playbook was not written. Fix these and call write_playbook again: "
                + "; ".join(f"{issue.where}: {issue.problem}" for issue in validation.issues),
            )

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
        # A written playbook answers the question the declines were about, and
        # supersedes the discard that recorded why the last one was thrown away.
        await workflow_repository.update_for_user(
            workflow_id,
            user_id,
            WorkflowUpdate(
                playbook_declines=0, playbook_declined_hash=None, last_playbook_discard=None
            ),
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
) -> dict[str, Any]:
    """Settle a run that never reached the work.

    Nothing is counted against the workflow — see :data:`BLOCKED_DECLINE_KINDS`
    for why a strike here is the bug rather than the record. The stored playbook
    is deliberately left alone even mid-heal: a heal run that could not run at
    all has learned nothing about whether the frozen sequence still holds, and
    deleting it would throw away a working shortcut over a disconnected account.
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
            {"declined": True, "blocked": True, "counted": False},
            "Noted — this run never reached the work, so it does not count against the "
            "workflow. It will be asked again on a run that gets further.",
        )

    paused = await pause_workflow_for_missing_integrations(workflow_id, user_id, integrations)
    if not paused:
        # The claim did not check out. Say so rather than pausing on it, and
        # still do not count a strike: a run that believed it was blocked did
        # not judge the sequence either.
        return success_response(
            {"declined": True, "blocked": True, "counted": False, "paused": False},
            "Noted, but those integrations look connected from here, so the workflow is "
            "still active.",
        )
    return success_response(
        {
            "declined": True,
            "blocked": True,
            "counted": False,
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

    try:
        user_id = get_user_id(config)
        workflow = await workflow_repository.get_for_user(workflow_id, user_id)
        if workflow is None:
            return error_response("workflow_not_found", f"No workflow {workflow_id} for this user.")
        # Past the limit the check is no longer asked; a decline now answers a
        # question nobody put, and counting it would let a copied "step" grow
        # the tally forever.
        if declined_for_good(workflow):
            return error_response(
                "not_asked",
                "This workflow is no longer asked about a playbook; nothing to decline.",
            )
        if kind in BLOCKED_DECLINE_KINDS:
            return await _record_blocked_run(workflow_id, user_id, kind, integrations or [])
        if kind is DeclineKind.NO_WORK_TODAY:
            # Not a verdict on the sequence: the work never happened, so there
            # was nothing to freeze. Asked again on a day it does.
            log.set_ns("playbook", quiet_day=True)
            return success_response(
                {"declined": True, "counted": False},
                "Noted: nothing to freeze on a day the work did not happen. This does not "
                "count against the workflow.",
            )

        run_id = get_stream_id(config)
        written = await playbook_repository.get_for_workflow(workflow_id, user_id)
        if written is not None and written.authored_run == run_id:
            # Seen on the real model: a valid write, then a decline in the same
            # turn. The write was checked against the run and stored; the
            # decline is a second voice of a decision already made.
            return success_response(
                {"declined": True, "counted": False},
                "This run already wrote a playbook, and that is its decision; nothing to record.",
            )

        # Counted once per run, however many times this run voices it: the
        # calls a model issues in one turn run in parallel on one state, so no
        # call can see another's answer. The repository matches on the run.
        declines = await workflow_repository.count_playbook_decline(
            workflow_id,
            user_id,
            run_id=run_id,
            workflow_hash=workflow_hash(workflow.prompt, workflow.steps),
        )
        if declines is None:
            return success_response(
                {"declined": True, "counted": False},
                "Already noted for this run. A run is one decision; nothing more to record.",
            )
        log.set_ns("playbook", declines=declines)

        # A decline inside a heal run is the agent saying the stored sequence
        # cannot hold. Leaving it FAILED/SUSPECT would brief every later fire
        # to heal it again.
        playbook = await playbook_repository.get_for_workflow(workflow_id, user_id)
        if playbook is not None and playbook.last_run_status in HEAL_STATUSES:
            await playbook_repository.delete_for_workflow(workflow_id, user_id)
            log.set_ns("playbook", disabled=True, reason=reason)
            return success_response(
                {"declined": True, "counted": True, "declines": declines, "disabled": True},
                "Noted. The stored playbook was removed; this workflow reasons out every run "
                "again.",
            )
        return success_response(
            {"declined": True, "counted": True, "declines": declines},
            "Noted. This workflow keeps reasoning out every run for now.",
        )
    except Exception as e:
        log.error(
            f"{LogTag.TOOL} decline_playbook: exception", error_type=type(e).__name__, exc_info=True
        )
        return error_response("decline_failed", str(e))


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


tools = [write_playbook, read_playbook, decline_playbook, disable_playbook]
