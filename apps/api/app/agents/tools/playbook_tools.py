"""Playbook tools: write, read, decline, and disable a workflow's frozen sequence.

A workflow keeps at most one playbook. There is no edit path and no version
history, because the agent revises by writing the whole document again, so a
write always replaces what was there and a rejected write leaves the previous
playbook untouched.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from app.constants.log_tags import LogTag
from app.db.repositories.playbooks import playbook_repository
from app.db.repositories.workflows import workflow_repository
from app.models.playbook_models import (
    PlaybookAsk,
    PlaybookDocument,
    PlaybookRunStatus,
    PlaybookStepInput,
    playbook_body_from_input,
)
from app.models.workflow_models import WorkflowUpdate
from app.services.workflow.playbook.check import HEAL_STATUSES, declined_for_good
from app.services.workflow.playbook.parser import dump_playbook, validate_playbook
from app.services.workflow.playbook.workflow_hash import workflow_hash
from app.utils.workflow_utils import (
    WorkflowConfigError,
    error_response,
    get_user_id,
    get_workflow_id,
    success_response,
)
from shared.py.wide_events import log


@tool
async def write_playbook(
    config: RunnableConfig,
    description: Annotated[str, "What this playbook does, in one or two lines."],
    steps: Annotated[
        list[PlaybookStepInput],
        "The calls to replay, in the order you made them: only the calls that did "
        "the work, never discovery or dead ends. Writing the result is not a step; "
        "that is what synthesize is for.",
    ],
    synthesize: Annotated[str, "How to write the run's result for the user."],
    ask: Annotated[
        dict[str, PlaybookAsk] | None,
        "Named slots a model fills at replay, for text you had to write rather "
        "than copy out of a result. Reference one as $ask.<name>.",
    ] = None,
) -> dict[str, Any]:
    """
    Freeze this workflow run's settled tool sequence as a playbook, so later runs
    execute it instead of reasoning it out again. The playbook attaches to the
    workflow this run is executing; there is no id to supply.

    The steps are checked against the real tools before anything is stored: if a
    tool or an argument does not exist, NOTHING is written and the problems come
    back so you can fix them and call this again. A successful write replaces the
    workflow's previous playbook entirely, which is also how you revise one.

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

        body = playbook_body_from_input(description, steps, synthesize, ask)

        validation = await validate_playbook(body, user_id)
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
                created_at=now,
                updated_at=now,
                description=body.description,
                steps=body.steps,
                ask=body.ask,
                synthesize=body.synthesize,
            )
        )
        # A written playbook answers the question the declines were about.
        await workflow_repository.update_for_user(
            workflow_id,
            user_id,
            WorkflowUpdate(playbook_declines=0, playbook_declined_hash=None),
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


@tool
async def decline_playbook(
    config: RunnableConfig,
    reason: Annotated[
        str,
        "Why this run's SEQUENCE OF CALLS would not hold tomorrow. Content that "
        "changes per run is not a reason; only a changing call order is.",
    ],
) -> dict[str, Any]:
    """
    Record that this run's sequence is not worth freezing as a playbook.

    Calling this is how you say no: a run asked to decide must end by calling
    exactly one of write_playbook or decline_playbook, so a missing decision is
    visible instead of looking identical to a considered no. The decline is
    kept on the workflow: after a few on the same unchanged workflow the
    question stops being asked until the workflow is edited. Declining while a
    stored playbook is being healed removes that playbook.
    """
    try:
        workflow_id = get_workflow_id(config)
    except WorkflowConfigError as e:
        return error_response("not_in_workflow_run", str(e))
    log.set(tool={"name": "decline_playbook", "action": "decline"}, workflow_id=workflow_id)
    log.set_ns("playbook", declined=True, decline_reason=reason)
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
        current_hash = workflow_hash(workflow.prompt, workflow.steps)
        declines = (
            workflow.playbook_declines + 1 if workflow.playbook_declined_hash == current_hash else 1
        )
        await workflow_repository.update_for_user(
            workflow_id,
            user_id,
            WorkflowUpdate(playbook_declines=declines, playbook_declined_hash=current_hash),
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
                {"declined": True, "disabled": True},
                "Noted. The stored playbook was removed; this workflow reasons out every run "
                "again.",
            )
        return success_response(
            {"declined": True},
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
