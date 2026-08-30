"""
Workflow worker functions for ARQ task processing.
Contains all workflow-related background tasks and execution logic.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from app.agents.core.background.executor_queue import (
    build_lock_value,
    get_lock_holder,
    release_lock_if_owned,
    try_acquire_lock,
)
from app.agents.core.background.workflow_platform_delivery import (
    deliver_workflow_result_to_platforms,
)
from app.agents.prompts.playbook_prompts import (
    PLAYBOOK_FALLBACK_TEMPLATE,
    PLAYBOOK_SUSPECT_FALLBACK_TEMPLATE,
)
from app.agents.prompts.workflow_prompts import (
    TODO_WORKFLOW_DESCRIPTION_TEMPLATE,
    TODO_WORKFLOW_PROMPT_TEMPLATE,
)
from app.api.v1.middleware.tiered_rate_limiter import (
    CostBudgetExceededException,
    RateLimitExceededException,
)
from app.config.settings import settings
from app.constants.agents import (
    PLAYBOOK_FALLBACK_CONTEXT_KEY,
    PLAYBOOK_HEAL_ATTEMPT_LIMIT,
    PLAYBOOK_SUSPECT_STREAK_LIMIT,
    AgentTag,
    wrap_agent_payload,
)
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.log_tags import LogTag
from app.core.websocket_manager import get_websocket_manager
from app.db.repositories.playbooks import playbook_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.decorators import enforce_daily_cost_budget
from app.decorators.rate_limiting import enforce_tiered_limit
from app.models.chat_models import MessageModel, ToolDataEntry
from app.models.message_models import MessageRequestWithHistory
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.models.payment_models import PlanType
from app.models.playbook_models import PlaybookDocument, PlaybookRunOutcome, PlaybookRunStatus
from app.models.todo_models import TodoUpdate
from app.models.user_models import AuthenticatedUser
from app.models.workflow_execution_models import RecordedCall
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    Workflow,
)
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.limit_upsell import LimitHitOrigin, mark_run_origin
from app.services.notification_service import notification_service
from app.services.triggers.batching import (
    coalesce_window_seconds,
    drain_trigger_batch,
    reschedule_if_refilled,
)
from app.services.user_service import get_user_by_id
from app.services.workflow.conversation_service import (
    add_playbook_run_messages,
    add_workflow_execution_messages,
    build_selected_workflow_data,
    get_or_create_workflow_conversation,
)
from app.services.workflow.execution_service import (
    PlaybookFallbackFailed,
    WorkflowFireOverlapped,
    WorkflowFireQueued,
    WorkflowFireTimedOut,
    complete_execution,
    create_execution,
)
from app.services.workflow.notifications import send_workflow_completion_notification
from app.services.workflow.playbook.check import HEAL_STATUSES, distrust_fresh_playbook
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.services.workflow.playbook.runner import PlaybookRunResult, run_playbook
from app.services.workflow.playbook.workflow_hash import workflow_hash
from app.services.workflow.run_trace import build_trace
from app.services.workflow.scheduler import WorkflowScheduler, workflow_scheduler
from app.services.workflow.service import WorkflowService
from app.services.workflow.thread_reset import reset_workflow_threads
from app.utils.errors import create_error
from app.utils.timezone import Timezone, format_local_time
from app.workers.config.worker_settings import WORKER_JOB_TIMEOUT_SECONDS
from shared.py.wide_events import WorkflowContext, log

# How far a fire may drift from its scheduled time before it is worth a warning.
_DRIFT_WARN_SECONDS = 300


async def process_workflow_generation_task(
    ctx: dict[str, Any],  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    todo_id: str,
    user_id: str,
    title: str,
    description: str = "",
) -> str:
    """
    Process workflow generation task for todos.
    Migrated from RabbitMQ to ARQ for unified task processing.
    Broadcasts WebSocket event when workflow generation completes.

    Args:
        ctx: ARQ context
        todo_id: Todo ID to generate workflow for
        user_id: User ID who owns the todo
        title: Todo title
        description: Todo description

    Returns:
        Processing result message
    """
    log.set(todo_id=todo_id, user_id=user_id, user={"id": user_id})
    try:
        # Build short card description plus detailed execution prompt
        workflow_description = TODO_WORKFLOW_DESCRIPTION_TEMPLATE.format(title=title)
        workflow_prompt = TODO_WORKFLOW_PROMPT_TEMPLATE.format(
            title=title,
            details_section=f"**Details:** {description}" if description else "",
        )
        # Create standalone workflow with todo workflow flag
        workflow_request = CreateWorkflowRequest(
            title=f"Todo: {title}",
            description=workflow_description,
            prompt=workflow_prompt,
            trigger_config=TriggerConfig(type=TriggerType.MANUAL, enabled=True),
            generate_immediately=True,
        )

        workflow = await WorkflowService.create_workflow(
            workflow_request,
            user_id,
            is_todo_workflow=True,
            source_todo_id=todo_id,
        )

        if workflow and workflow.id:
            # Verify workflow actually has steps before linking
            if not workflow.steps or len(workflow.steps) == 0:
                reason = workflow.error_message or "unknown error"
                raise create_error(
                    message=f"Workflow {workflow.id} created but has no steps — {reason}",
                    why="workflow generation completed without producing any steps",
                    fix="retry workflow generation for this todo",
                    workflow_id=workflow.id,
                    todo_id=todo_id,
                )

            linked = await todo_repository.update(
                todo_id, user_id=user_id, update=TodoUpdate(workflow_id=workflow.id)
            )

            if linked is not None:
                log.info(
                    f"{LogTag.WORKER} Successfully generated and linked standalone workflow",
                    workflow_id=workflow.id,
                    todo_id=todo_id,
                    steps_count=len(workflow.steps),
                )
                log.set(
                    workflow=WorkflowContext(
                        id=workflow.id,
                        steps_count=len(workflow.steps),
                        trigger_type=TriggerType.MANUAL.value,
                    )
                )

                capture_event(
                    user_id,
                    AnalyticsEvents.WORKFLOW_CREATED,
                    {
                        "workflow_id": workflow.id,
                        "steps_count": len(workflow.steps),
                        "is_todo_workflow": True,
                    },
                )

                try:
                    websocket_manager = get_websocket_manager()
                    await websocket_manager.broadcast_to_user(
                        user_id,
                        {
                            "type": "workflow.generated",
                            "todo_id": todo_id,
                            "workflow": workflow.model_dump(mode="json"),
                        },
                    )
                    log.set(websocket_broadcast_success=True)
                except Exception as ws_error:
                    log.set(websocket_broadcast_success=False)
                    log.warning(
                        f"{LogTag.WORKER} Failed to send WebSocket event",
                        error_type=type(ws_error).__name__,
                        error=str(ws_error),
                        workflow_id=workflow.id,
                        todo_id=todo_id,
                    )

                # Clear the generating flag
                # Deferred import: function-local re-bind in this success path; the workflow stack is already loaded by module-top service imports
                from app.services.workflow.queue_service import (  # noqa: PLC0415 -- deferred
                    WorkflowQueueService,
                )

                try:
                    await WorkflowQueueService.clear_workflow_generating_flag(todo_id)
                except Exception as cleanup_error:
                    # Cleanup must not mask the original failure re-raised below.
                    log.warning(
                        f"{LogTag.WORKER} Failed to clear workflow generating flag",
                        todo_id=todo_id,
                        error=str(cleanup_error),
                        error_type=type(cleanup_error).__name__,
                    )

                return (
                    f"Successfully generated standalone workflow {workflow.id} for todo {todo_id}"
                )
            raise create_error(
                message=f"Todo {todo_id} not found or not updated",
                why="the todo was deleted or the workflow-link update matched no document",
                fix="verify the todo still exists before regenerating its workflow",
                todo_id=todo_id,
            )

        # Mark workflow generation as failed
        log.error(
            f"{LogTag.WORKER} Failed to generate workflow for todo: no workflow created",
            todo_id=todo_id,
            user_id=user_id,
        )
        raise create_error(
            message="Workflow generation failed: No workflow created",
            why="WorkflowService.create_workflow returned no workflow",
            fix="check workflow generation logs for the underlying failure",
            todo_id=todo_id,
        )

    except Exception as e:
        # Clear the generating flag on failure too
        try:
            from app.services.workflow.queue_service import (  # noqa: PLC0415 -- heavy workflow queue loads only when this task runs
                WorkflowQueueService,
            )

            await WorkflowQueueService.clear_workflow_generating_flag(todo_id)
        except Exception as cleanup_error:
            # Cleanup must not mask the original failure re-raised below.
            log.warning(
                f"{LogTag.WORKER} Failed to clear workflow generating flag",
                todo_id=todo_id,
                error_type=type(cleanup_error).__name__,
            )

        # Broadcast failure WebSocket event so frontend can handle it
        try:
            websocket_manager = get_websocket_manager()
            await websocket_manager.broadcast_to_user(
                user_id,
                {
                    "type": "workflow.generation_failed",
                    "todo_id": todo_id,
                    "error": str(e),
                },
            )
            log.set(websocket_broadcast_success=True)
        except Exception as ws_error:
            log.set(websocket_broadcast_success=False)
            log.warning(
                f"{LogTag.WORKER} Failed to send failure WebSocket event",
                error_type=type(ws_error).__name__,
                error=str(ws_error),
                todo_id=todo_id,
                user_id=user_id,
            )

        raise


async def _completed_onboarding(user_id: str) -> bool:
    """Whether the user submitted the onboarding wizard (``onboarding.completed``)."""
    user = await user_repository.get(user_id)
    return bool(user and (user.onboarding or {}).get("completed"))


async def _rearm_if_scheduled(
    scheduler: WorkflowScheduler, workflow: Workflow | None, context: dict[str, Any] | None
) -> None:
    """Arm the next occurrence for cron-scheduled recurring workflows.

    Only scheduler-originated fires (trigger_type=schedule) advance the schedule;
    manual and integration-triggered runs must not shift it. A workflow deactivated
    while a fire was in flight must not be re-armed back into the scheduled loop —
    liveness is governed by `activated`.
    """
    if workflow is None or not workflow.repeat or not workflow.activated:
        return
    trigger_type = context.get("trigger_type") if context else None
    if trigger_type != TriggerType.SCHEDULE.value:
        return
    await scheduler.handle_recurring_task(workflow, (workflow.occurrence_count or 0) + 1)


async def _rearm_quietly(
    scheduler: WorkflowScheduler,
    workflow: Workflow | None,
    context: dict[str, Any] | None,
    workflow_id: str,
) -> None:
    """Arm the next occurrence. A re-arm failure must not change the outcome the
    execution itself already determined, in either direction."""
    try:
        await _rearm_if_scheduled(scheduler, workflow, context)
    except Exception as rearm_err:
        log.error(f"{LogTag.WORKER} Failed to re-arm workflow %s: %s" % (workflow_id, rearm_err))


def _log_schedule_drift(workflow: Workflow, workflow_id: str, actual_fire_utc: datetime) -> None:
    scheduled_at = getattr(workflow, "scheduled_at", None)
    if not isinstance(scheduled_at, datetime):
        return

    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    drift = int((actual_fire_utc - scheduled_at).total_seconds())
    log.set(
        scheduled_at_utc=scheduled_at.isoformat(),
        drift_from_scheduled_seconds=drift,
    )
    if abs(drift) > _DRIFT_WARN_SECONDS:
        log.warning(
            f"{LogTag.WORKER} Workflow fired off schedule (positive = late, negative = early)",
            workflow_id=workflow_id,
            drift=drift,
        )


async def _quota_exhausted_body(workflow: Workflow, reset_time_str: str) -> str:
    """Quota-exhausted copy, naming the reset time in the user's own timezone.
    Falls back to the undated wording if the reset stamp can't be rendered."""
    body = f"'{workflow.title}' couldn't run — you've used all your workflow executions for today."
    try:
        reset_dt = datetime.fromisoformat(reset_time_str)
        if reset_dt.tzinfo is None:
            reset_dt = reset_dt.replace(tzinfo=UTC)
        try:
            reset_user = await get_user_by_id(workflow.user_id)
            reset_tz = reset_user.get("timezone") if reset_user else None
        except Exception:
            reset_tz = None
        formatted_reset = format_local_time(reset_dt, reset_tz, fmt="%b %d at %I:%M %p %Z")
        return f"{body} Resets {formatted_reset}."
    except Exception:
        return body


async def _rate_limit_failure_content(
    error: Exception, workflow: Workflow
) -> tuple[str, NotificationAction | None]:
    """Failure copy plus the upgrade CTA for a budget-, quota-, or plan-blocked run."""
    # HTTPException.detail is typed str | None upstream, but
    # RateLimitExceededException always assigns a dict at runtime — read it via
    # getattr to avoid narrowing against the (incorrect for this subclass)
    # inherited annotation.
    raw_detail = getattr(error, "detail", None)
    detail: dict[str, str] = raw_detail if isinstance(raw_detail, dict) else {}
    reset_time_str = detail.get("reset_time", "")
    # A user already on the top tier has nothing to upgrade to — drop the
    # pitch and the upgrade action for them.
    is_pro = detail.get("current_plan") == PlanType.PRO.value
    # Only two tiers exist, so the upgrade target is always Pro even when
    # plan_required is absent (a count wall on a feature free can still use).
    upgrade_plan = (detail.get("plan_required") or PlanType.PRO.value).capitalize()

    if isinstance(error, CostBudgetExceededException):
        # Budget (cost) wall, not the execution-count quota — different cause,
        # different copy. Runs resume after the daily reset; the caller's
        # re-arm keeps the cron.
        body = (
            f"'{workflow.title}' couldn't run — you're out of "
            f"AI usage for today. It will run again after your usage resets."
        )
        if not is_pro:
            body += f" Upgrade to {upgrade_plan} for much higher limits."
    elif reset_time_str:
        body = await _quota_exhausted_body(workflow, reset_time_str)
        if not is_pro:
            body += f" Upgrade to {upgrade_plan} for higher daily limits."
    else:
        # Plan-gated — feature isn't available on their plan at all. Only a
        # free user can reach here (Pro has access).
        body = (
            f"'{workflow.title}' couldn't run — "
            f"automated workflow execution is not available on your current plan. "
            f"Upgrade to {upgrade_plan} to unlock this feature."
        )

    upgrade_action = (
        None
        if is_pro
        else NotificationAction(
            type=ActionType.REDIRECT,
            label=f"Upgrade to {upgrade_plan}",
            style=ActionStyle.PRIMARY,
            config=ActionConfig(
                redirect=RedirectConfig(
                    url="/settings?section=subscription",
                    open_in_new_tab=False,
                    close_notification=True,
                )
            ),
        )
    )
    return body, upgrade_action


async def _notify_workflow_failed(error: Exception, workflow: Workflow) -> None:
    """Tell the user the workflow failed. Best-effort: a notification failure must
    not mask the error that caused it."""
    try:
        if isinstance(error, RateLimitExceededException):
            body, upgrade_action = await _rate_limit_failure_content(error, workflow)
        else:
            body = f"Your workflow '{workflow.title}' encountered an error and could not complete."
            upgrade_action = None

        # A budget skip is a pause, not a failure — the run resumes after the
        # daily reset, and the title must not read like something broke.
        title = (
            f"Workflow Paused: {workflow.title}"
            if isinstance(error, CostBudgetExceededException)
            else f"Workflow Failed: {workflow.title}"
        )

        await notification_service.create_notification(
            NotificationRequest(
                user_id=workflow.user_id,
                source=NotificationSourceEnum.WORKFLOW_FAILED,
                type=NotificationType.ERROR,
                content=NotificationContent(
                    title=title,
                    body=body,
                    actions=[upgrade_action] if upgrade_action else None,
                ),
                metadata={
                    "workflow_id": workflow.id,
                    "error_type": type(error).__name__,
                },
            )
        )
    except Exception as notify_err:
        log.debug(f"{LogTag.WORKER} Failed to send failure notification: %s" % notify_err)


async def _record_execution_failure(
    error: Exception,
    workflow: Workflow | None,
    workflow_id: str,
    execution_id: str | None,
    *,
    after_replay: PlaybookFallbackFailed | None = None,
) -> None:
    """Close out a failed run: mark the execution record, bump the failure count
    and notify the user. Every step is best-effort — none of this bookkeeping
    may mask ``error``. The error itself is recorded on the wide event by the
    caller's except block (this helper is bookkeeping only). ``trace`` is what
    the fire had already done before it failed, so the next fire reads it as
    history instead of repeating it."""
    if execution_id:
        try:
            await complete_execution(
                execution_id=execution_id,
                status="failed",
                error_message=str(error),
                conversation_id=after_replay.conversation_id if after_replay else None,
                trace=after_replay.trace if after_replay else None,
            )
        except Exception as e2:
            log.debug(f"{LogTag.WORKER} Failed to complete execution record: %s" % e2)

    if workflow is None:
        return

    # A spent daily cost budget is a clean skip, not a failure: no work ran and
    # the workflow resumes after the budget resets, so it must not be counted
    # against the workflow's stats.
    if not isinstance(error, CostBudgetExceededException):
        try:
            await WorkflowService.increment_execution_count(
                workflow_id, workflow.user_id, is_successful=False
            )
        except Exception as e2:
            log.debug(f"{LogTag.WORKER} Failed to update workflow stats: %s" % e2)

    await _notify_workflow_failed(error, workflow)


def _origin_for(trigger_type: str) -> LimitHitOrigin:
    """A manual fire is the user standing there; a schedule or webhook is not.

    Picks which email a limit hit sends, so getting it wrong tells a user who
    clicked Run that their workflows are paused, or tells a user who did nothing
    that *they* hit *their* limit.
    """
    return (
        LimitHitOrigin.INTERACTIVE
        if trigger_type == TriggerType.MANUAL.value
        else LimitHitOrigin.BACKGROUND
    )


#: A completed line as the fallback agent reads it. The narration reads the
#: full result (its own bound); the agent needs to know what ran and roughly
#: what came back, not the whole payload again in its brief.
FALLBACK_LINE_MAX_CHARS = 1_500


def _bounded_line(line: str) -> str:
    return line if len(line) <= FALLBACK_LINE_MAX_CHARS else line[:FALLBACK_LINE_MAX_CHARS] + "..."


def _fallback_note(result: PlaybookRunResult) -> str:
    """The replay that did not hold, stopped or untrusted, addressed to the agent
    that has to finish the run."""
    completed = "\n".join(f"- {_bounded_line(line)}" for line in result.completed) or "- nothing"
    if result.ok:
        body = PLAYBOOK_SUSPECT_FALLBACK_TEMPLATE.format(
            reason=result.suspect or "no reason was recorded", completed=completed
        )
    else:
        body = PLAYBOOK_FALLBACK_TEMPLATE.format(
            failure=result.failure or "The replay stopped without saying why.",
            completed=completed,
        )
    return wrap_agent_payload(AgentTag.PLAYBOOK_FALLBACK, body)


#: The execution-record summary of a fire the agent reasoned out.
#: Execution summaries, as the workflows page shows them. Plain words: the
#: reader is the workflow's owner, not the engineer who wrote the replay.
AGENT_RUN_SUMMARY = "Ran the full workflow"
HEAL_RUN_SUMMARY = "Ran the full workflow and repaired its saved shortcut"
REPLAY_SUMMARY = "Ran from the saved shortcut"
REPLAY_STOPPED_SUMMARY = "The saved shortcut stopped partway, so GAIA ran the rest itself"
REPLAY_FLAGGED_SUMMARY = (
    "The saved shortcut's result looked wrong ({reason}), so GAIA ran the workflow itself"
)
OVERLAPPED_SUMMARY = (
    "Skipped: a previous run of this workflow was still going, and that run delivered the result"
)
QUEUED_MESSAGE = (
    "This run started while the previous one was still going, so it waited and ran after "
    "it. If this keeps happening, give the workflow a longer interval than one run takes."
)
SHORTCUT_DISCARDED_SUMMARY = (
    "Ran the full workflow; the saved shortcut was discarded because the workflow changed"
)


async def _discard_playbook(
    workflow_id: str, user_id: str, playbook: PlaybookDocument, *, reason: str, **details: object
) -> None:
    """Drop a playbook the worker has given up on, saying why. Never raises: the
    fire still runs on the agent, and a failed delete only costs the next check."""
    try:
        await playbook_repository.delete_for_workflow(workflow_id, user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.WORKER} Playbook delete failed; it stays on file for now",
            workflow_id=workflow_id,
            playbook_id=playbook.playbook_id,
            reason=reason,
            error_type=type(e).__name__,
        )
        return
    log.warning(
        f"{LogTag.WORKER} Playbook discarded",
        workflow_id=workflow_id,
        playbook_id=playbook.playbook_id,
        reason=reason,
        **details,
    )


@dataclass(frozen=True)
class _Fire:
    """One fire of one workflow, as the run paths see it."""

    workflow: Workflow
    workflow_id: str
    context: dict[str, Any]
    user: AuthenticatedUser


async def _run_workflow(
    workflow: Workflow, workflow_id: str, context: dict[str, Any]
) -> tuple[str, list[RecordedCall], str]:
    """Run the fire on whichever path can carry it. Returns the conversation, the
    trace, and the summary the execution record should carry.

    A playbook is replayed only while its ``workflow_hash`` still matches the
    workflow: the frozen sequence answered one particular prompt and set of
    steps, so a user edit makes it an answer to a question nobody asked. A
    replay that stops partway hands the rest to the agent WITH its own record,
    which is the only thing standing between a half-finished run and a second
    copy of every side effect it already caused.
    """
    # ONE charge per fire, before any path runs. It lives here rather than on the
    # two run functions because a replay that stops partway hands the rest to the
    # agent path: charged on both, one result would cost the user two executions,
    # so a drifting playbook would burn their quota at double rate because OUR
    # optimisation failed. Charging up front also keeps the pre-work refusal the
    # decorator gave us — an over-quota user is stopped before any side effect,
    # not after. Actual resource consumption stays metered by
    # ``enforce_daily_cost_budget`` above, which is where "it ran twice" belongs.
    await enforce_tiered_limit(workflow.user_id, "trigger_workflow_executions")

    user: AuthenticatedUser = {"user_id": workflow.user_id}

    # A playbook is an optimisation over the agentic path, never a precondition
    # for it. If this read fails the user's workflow must still run, so the
    # failure costs the replay and nothing else — without this guard a playbooks
    # collection outage would take down every workflow run on the platform.
    try:
        playbook = await playbook_repository.get_for_workflow(workflow_id, workflow.user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.WORKFLOW} playbook lookup failed; running the workflow agentically",
            workflow_id=workflow_id,
            error_type=type(e).__name__,
        )
        log.set_ns("playbook", mode="agent", reason="lookup_failed", llm_calls=0)
        return *await execute_workflow_as_chat(workflow, user, context), AGENT_RUN_SUMMARY

    if playbook is None:
        log.set_ns("playbook", mode="agent", reason="no_playbook", llm_calls=0)
        return *await execute_workflow_as_chat(workflow, user, context), AGENT_RUN_SUMMARY

    if playbook.workflow_hash != workflow_hash(workflow.prompt, workflow.steps):
        # Deleted, not merely skipped: the check brief only asks for a playbook
        # when there is none, so a stale one left on file would never be
        # re-authored and the workflow would run at full agent cost forever.
        await _discard_playbook(
            workflow_id, workflow.user_id, playbook, reason="stale_workflow_hash"
        )
        log.set_ns(
            "playbook",
            mode="agent",
            reason="stale_workflow_hash",
            playbook_id=playbook.playbook_id,
            llm_calls=0,
        )
        return *await execute_workflow_as_chat(workflow, user, context), SHORTCUT_DISCARDED_SUMMARY

    # A playbook the last run did not trust is not replayed again: the agent
    # runs this fire with the heal brief carrying the recorded reason, and ends
    # by rewriting the playbook or disabling it. Replaying it a second time
    # only repeats the same wrong result, and the streak limit then deletes
    # the playbook before any agent has seen why. An attempt is a heal run
    # that completed and left the body still distrusted: it is counted after
    # the agent returns and only against the revision it was healing, so a
    # fire that never reached the agent (a DNS outage, a crashed worker) spends
    # nothing, and a rewrite starts the new body at zero. Past the limit the
    # playbook goes.
    if playbook.last_run_status in HEAL_STATUSES:
        if playbook.heal_attempts >= PLAYBOOK_HEAL_ATTEMPT_LIMIT:
            await _discard_playbook(
                workflow_id,
                workflow.user_id,
                playbook,
                reason="heal_attempts_exhausted",
                heal_attempts=playbook.heal_attempts,
            )
            log.set_ns(
                "playbook",
                mode="agent",
                reason="heal_attempts_exhausted",
                playbook_id=playbook.playbook_id,
                heal_attempts=playbook.heal_attempts,
                llm_calls=0,
            )
            return *await execute_workflow_as_chat(workflow, user, context), AGENT_RUN_SUMMARY
        log.set_ns(
            "playbook",
            mode="agent",
            reason="heal",
            playbook_id=playbook.playbook_id,
            last_run_status=playbook.last_run_status.value,
            heal_attempts=playbook.heal_attempts,
            llm_calls=0,
        )
        healed = await execute_workflow_as_chat(workflow, user, context)
        await playbook_repository.increment_heal_attempts(
            workflow_id,
            workflow.user_id,
            playbook_id=playbook.playbook_id,
            revision=playbook.revision,
        )
        return *healed, HEAL_RUN_SUMMARY

    conversation_id, result = await execute_workflow_as_playbook(workflow, user, context, playbook)
    # From here on the replay's calls are history that happened. Whatever ends
    # this fire — a result, a queued hand-off, or a failure — carries them, or
    # the next fire reads an empty record and repeats every side effect.
    try:
        return await _finish_after_replay(
            _Fire(workflow=workflow, workflow_id=workflow_id, context=context, user=user),
            playbook,
            conversation_id,
            result,
        )
    except WorkflowFireQueued as queued:
        queued.trace = [*result.trace, *queued.trace]
        raise
    except Exception as exc:
        raise PlaybookFallbackFailed(
            exc, conversation_id=conversation_id, trace=result.trace
        ) from exc


async def _notify_replay_finished(
    workflow: Workflow, user: AuthenticatedUser, conversation_id: str, text: str
) -> None:
    """Deliver a finished replay exactly as the executor path delivers an agent
    run: into the user's linked platforms, then the in-app heads-up. Gated on
    ``notify_on_completion`` like that path; best-effort like that path."""
    if not workflow.notify_on_completion:
        log.info(
            f"{LogTag.WORKER} Replay completion notification skipped (workflow is silent)",
            workflow_id=workflow.id,
        )
        return
    try:
        await deliver_workflow_result_to_platforms(
            user=user,
            user_id=workflow.user_id,
            notification_text=text,
            origin=f'workflow "{workflow.title}" (id {workflow.id})',
        )
        await send_workflow_completion_notification(
            workflow_id=workflow.id or "",
            workflow_title=workflow.title,
            conversation_id=conversation_id,
            user_id=workflow.user_id,
        )
    except Exception as e:
        log.warning(
            f"{LogTag.WORKER} Replay completion notification failed",
            workflow_id=workflow.id,
            error=str(e),
            error_type=type(e).__name__,
        )


async def _finish_after_replay(
    fire: _Fire,
    playbook: PlaybookDocument,
    conversation_id: str,
    result: PlaybookRunResult,
) -> tuple[str, list[RecordedCall], str]:
    """Record the replay's outcome, then deliver its result or let the agent finish the run.

    Only a trusted result is delivered. A replay that stopped partway (FAILED)
    or finished with a result the runner did not trust (SUSPECT, from either
    the deterministic check or the narration) hands the fire to the agent WITH
    its record, so the user gets one result per fire and never a confident
    wrong brief. Suspect outcomes accumulate on the playbook; at
    ``PLAYBOOK_SUSPECT_STREAK_LIMIT`` it is dropped before the agent runs, so
    that run is asked to author afresh rather than to heal.
    """
    workflow, workflow_id, context, user = fire.workflow, fire.workflow_id, fire.context, fire.user
    if not result.ok:
        status = PlaybookRunStatus.FAILED
        reason = result.failure
    elif result.suspect:
        status = PlaybookRunStatus.SUSPECT
        reason = result.suspect
    else:
        status = PlaybookRunStatus.SUCCESS
        reason = None
    updated = await playbook_repository.record_run_outcome(
        workflow_id,
        workflow.user_id,
        PlaybookRunOutcome(
            status,
            reason=reason,
            # The narration's verdict is an opinion: it hands the fire to the
            # agent but does not move the playbook toward deletion. Only the
            # record's check does.
            counts_toward_streak=result.suspect_source != "narration",
        ),
        playbook_id=playbook.playbook_id,
        revision=playbook.revision,
    )
    if updated is None:
        # Rewritten or removed while this replay ran: the verdict describes a
        # body that is no longer there, so it is neither recorded nor counted.
        log.warning(
            f"{LogTag.WORKER} Playbook replay outcome not recorded; the playbook changed mid-run",
            workflow_id=workflow_id,
            playbook_id=playbook.playbook_id,
            revision=playbook.revision,
            outcome=status.value,
        )

    if status is PlaybookRunStatus.SUCCESS:
        log.set_ns(
            "playbook",
            mode="replay",
            reason="workflow_hash_match",
            playbook_id=playbook.playbook_id,
            llm_calls=result.llm_calls,
            outcome=status.value,
        )
        # Only a trusted replay writes the turn. The others leave the
        # conversation to the agent run that takes over, so the user sees one
        # result for one fire instead of a half-run followed by a real one.
        await add_playbook_run_messages(
            conversation_id=conversation_id,
            user_id=workflow.user_id,
            workflow=workflow,
            response=result.text,
            trace=result.trace,
            playbook=playbook,
        )
        await _notify_replay_finished(workflow, user, conversation_id, result.text)
        return conversation_id, result.trace, REPLAY_SUMMARY

    disabled = False
    if status is PlaybookRunStatus.SUSPECT and updated is not None:
        disabled = updated.suspect_streak >= PLAYBOOK_SUSPECT_STREAK_LIMIT
        if disabled:
            await playbook_repository.delete_for_workflow(workflow_id, workflow.user_id)
            log.warning(
                f"{LogTag.WORKER} Playbook disabled after repeated suspect replays",
                workflow_id=workflow_id,
                playbook_id=playbook.playbook_id,
                reason=reason,
                suspect_streak=updated.suspect_streak,
            )
    if status is PlaybookRunStatus.FAILED:
        log.set_ns(
            "playbook",
            mode="agent",
            reason="replay_stopped",
            playbook_id=playbook.playbook_id,
            llm_calls=result.llm_calls,
            outcome=status.value,
        )
        log.warning(
            f"{LogTag.WORKER} Playbook replay stopped; the agent is finishing this run",
            workflow_id=workflow_id,
            playbook_id=playbook.playbook_id,
            failure=result.failure,
        )
        summary = REPLAY_STOPPED_SUMMARY
    else:
        log.set_ns(
            "playbook",
            mode="agent",
            reason="replay_suspect",
            playbook_id=playbook.playbook_id,
            llm_calls=result.llm_calls,
            outcome=status.value,
            suspect_reason=reason,
            disabled=disabled,
        )
        log.warning(
            f"{LogTag.WORKER} Playbook replay not trusted; the agent is finishing this run",
            workflow_id=workflow_id,
            playbook_id=playbook.playbook_id,
            reason=reason,
        )
        # reason is result.suspect on this branch, and SUSPECT status is reached
        # only when that is set, so there is no empty case left to name here.
        summary = REPLAY_FLAGGED_SUMMARY.format(reason=str(reason).rstrip("."))
    conversation_id, agent_trace = await execute_workflow_as_chat(
        workflow, user, {**context, PLAYBOOK_FALLBACK_CONTEXT_KEY: _fallback_note(result)}
    )
    # This was a heal run too: it carried the heal brief and ended with a
    # decision, so it spends an attempt on the body it healed (a rewrite moved
    # the revision on, and the count then lands nowhere).
    if not disabled:
        await playbook_repository.increment_heal_attempts(
            workflow_id,
            workflow.user_id,
            playbook_id=playbook.playbook_id,
            revision=playbook.revision,
        )
    # The replay's own calls stay on the record: they are what the agent was
    # told not to repeat, and the next run reads this trace as its history.
    return conversation_id, [*result.trace, *agent_trace], summary


def _parse_scheduled_for(context: dict[str, Any] | None, workflow_id: str) -> "datetime | None":
    """The occurrence stamp the fire was armed for, or None when unstamped.

    Only a numeric stamp is scheduler provenance: manual "run now" callers
    control their own context dict, so a hand-typed trigger_type/scheduled_for
    must be ignored (ungated), not crash fromtimestamp mid-run.
    """
    scheduled_for = context.get("scheduled_for") if context else None
    if isinstance(scheduled_for, bool) or not isinstance(scheduled_for, (int, float)):
        if scheduled_for is not None:
            # Present but not a number: a manual caller hand-typing its own
            # context. Discard loudly — silence here would hide real bugs.
            log.warning(
                f"{LogTag.WORKER} Unparseable scheduled_for on scheduled fire; treating as unstamped",
                workflow_id=workflow_id,
                scheduled_for=str(scheduled_for)[:32],
            )
        return None
    try:
        return datetime.fromtimestamp(scheduled_for, tz=UTC)
    except (ValueError, OverflowError, OSError):
        log.warning(
            f"{LogTag.WORKER} Unparseable scheduled_for on scheduled fire; treating as unstamped",
            workflow_id=workflow_id,
            scheduled_for=str(scheduled_for)[:32],
        )
        return None


def _derive_trigger_type(context: dict[str, Any] | None) -> str:
    # An explicit trigger_type always wins; only an ABSENT one falls back — to
    # "integration" when the context carries a webhook payload (trigger fires
    # queued before the trigger service stamped trigger_type), else to "manual".
    trigger_type = context.get("trigger_type") if context else None
    if trigger_type is not None:
        return str(trigger_type)
    has_payload = bool(context and "trigger_data" in context)
    return TriggerType.INTEGRATION.value if has_payload else TriggerType.MANUAL.value


async def _claim_scheduled_fire(
    scheduler: WorkflowScheduler, workflow_id: str, context: dict[str, Any] | None
) -> bool:
    # The claim pins the occurrence the fire was armed for (``scheduled_for``,
    # stamped by the scheduler at enqueue). ARQ has no job cancellation, so
    # after a reschedule the old deferred job still fires;
    # trigger_config.next_run has moved on and the mismatch rejects it instead
    # of running the workflow at its original time. Jobs enqueued before the
    # stamp existed carry no key and are ungated, so a deploy never strands a
    # schedule.
    expected_next_run = _parse_scheduled_for(context, workflow_id)
    claimed = await scheduler.claim_scheduled_for_execution(
        workflow_id, expected_next_run=expected_next_run
    )
    if not claimed:
        log.warning(
            f"{LogTag.WORKER} Workflow not in scheduled state "
            "(already claimed, running, deactivated, or rescheduled away); "
            "skipping stale scheduled fire",
            workflow_id=workflow_id,
            # The raw stamp (epoch seconds) reads better in Loki than a datetime
            # repr, and is exactly what the enqueue carried.
            scheduled_for=(context or {}).get("scheduled_for"),
        )
    return claimed


async def _admit_fire(
    workflow: Workflow,
    workflow_id: str,
    trigger_type: str,
    context: dict[str, Any] | None,
    actual_fire_utc: datetime,
) -> str | None:
    """The gates a fire passes before any work: why it was skipped, or None."""
    # Scheduler-originated fires: atomically claim the occurrence (scheduled ->
    # executing) so a concurrent recovery scan can't double-execute a workflow
    # whose previous fire is still running. Manual/integration "run now" fires
    # don't go through the scan and must not be status-gated.
    if trigger_type == TriggerType.SCHEDULE.value and not await _claim_scheduled_fire(
        workflow_scheduler, workflow_id, context
    ):
        return f"Workflow {workflow_id} already claimed; skipped duplicate scheduled fire"

    _log_schedule_drift(workflow, workflow_id, actual_fire_utc)

    # System-initiated runs (schedule and trigger fires) don't run for a
    # user who never finished the onboarding wizard: their auto-created
    # workflows would drain the daily budget for someone who hasn't
    # started using GAIA, then aim "you hit your limit" messaging at them.
    # Re-arm quietly so a recurring workflow resumes if they finish later.
    if trigger_type != TriggerType.MANUAL.value and not await _completed_onboarding(
        workflow.user_id
    ):
        log.info(
            f"{LogTag.WORKER} Workflow skipped — user has not completed onboarding",
            workflow_id=workflow_id,
            user_id=workflow.user_id,
        )
        await _rearm_quietly(workflow_scheduler, workflow, context, workflow_id)
        return f"Workflow {workflow_id} skipped — user has not completed onboarding"
    return None


async def _drain_trigger_events(
    batch_key: str | None, context: dict[str, Any] | None, workflow_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Take the coalesced batch; returns ``(context, skip_reason)``.

    An empty take means another run already drained these events and there is
    nothing left to do. A Redis outage leaves the buffer intact — the returned
    reason makes the caller exit WITHOUT claiming the events were drained; the
    finally's refill check (or the next inbound event) schedules a fresh run
    once Redis returns.
    """
    if not batch_key:
        return context, None
    events = await drain_trigger_batch(str(batch_key))
    if events is None:
        log.set_ns("workflow", outcome="trigger_batch_unavailable")
        return context, f"Workflow {workflow_id} skipped — trigger batch unavailable"
    log.set_ns("workflow", trigger_batch_size=len(events))
    if not events:
        log.set_ns("workflow", outcome="trigger_batch_empty")
        return context, f"Workflow {workflow_id} skipped — trigger batch empty"
    merged = {**(context or {}), "trigger_data": {"events": events, "count": len(events)}}
    return merged, None


async def _run_and_record_success(
    workflow: Workflow,
    workflow_id: str,
    trigger_type: str,
    context: dict[str, Any] | None,
    execution_id: str,
) -> str:
    # Replay the workflow's playbook when it still describes this workflow,
    # otherwise run the agent. A replay that stops partway hands the rest of
    # the run to the agent, carrying what it already did so the agent does
    # not repeat a side effect. The agent path delivers its own result from
    # the background delivery path (gated by workflow_id); a trusted replay
    # delivers inside _finish_after_replay.
    conversation_id, trace, summary = await _run_workflow(workflow, workflow_id, context or {})

    # Track successful execution
    await WorkflowService.increment_execution_count(
        workflow_id, workflow.user_id, is_successful=True
    )

    # Complete execution record with success. The run did complete either
    # way; the summary says how, so a flagged replay never reads as a clean
    # one in the history.
    await complete_execution(
        execution_id=execution_id,
        status="success",
        summary=summary,
        conversation_id=conversation_id,
        trace=trace,
    )

    # A playbook this run wrote is checked against this run's own results:
    # frozen on an empty result, it is distrusted before it is ever replayed.
    await distrust_fresh_playbook(
        workflow_id, workflow.user_id, trace, healing=summary != AGENT_RUN_SUMMARY
    )

    # Analytics: the run-now endpoint already captures manual executions at
    # queue time (workflows.py); background-origin runs — scheduler,
    # tracked-todo, and integration triggers — only flow through this task,
    # so their completion is captured here. `trigger_type` already folds
    # unstamped integration fires in (see the derivation above).
    if trigger_type != TriggerType.MANUAL.value:
        capture_event(
            workflow.user_id,
            AnalyticsEvents.WORKFLOW_EXECUTED,
            {"workflow_id": workflow_id, "trigger_type": trigger_type},
        )

    # Arm the next occurrence (scheduled recurring workflows only). A re-arm
    # failure must not turn a successful execution into a reported failure.
    await _rearm_quietly(workflow_scheduler, workflow, context, workflow_id)

    return f"Workflow {workflow_id} executed successfully"


def _unwrapped(raised: Exception) -> Exception:
    """The real error behind a failure that arrived wrapped with a replay's trace."""
    return raised.cause if isinstance(raised, PlaybookFallbackFailed) else raised


async def _record_run_failure(
    raised: Exception,
    workflow: Workflow | None,
    workflow_id: str,
    execution_id: str | None,
    context: dict[str, Any] | None,
) -> str:
    # A failure after a partial replay arrives wrapped with the replay's
    # trace; the bookkeeping below classifies the real error, and the
    # record keeps the calls that already happened.
    after_replay = raised if isinstance(raised, PlaybookFallbackFailed) else None
    e = _unwrapped(raised)
    if after_replay is None:
        await _record_execution_failure(e, workflow, workflow_id, execution_id)
    else:
        await _record_execution_failure(
            e, workflow, workflow_id, execution_id, after_replay=after_replay
        )

    # Still arm the next occurrence — a transient failure (rate limit, LLM
    # error) must not permanently kill a recurring workflow.
    await _rearm_quietly(workflow_scheduler, workflow, context, workflow_id)

    return f"Error executing workflow {workflow_id}: {e}"


async def _reschedule_refill_safe(
    workflow: Workflow | None,
    workflow_id: str,
    batch_key: str | None,
    context: dict[str, Any] | None,
) -> None:
    # Events that landed while this run held the batch could not schedule
    # their own run (the job id was occupied). Every exit owes them a
    # follow-up — a failed or gate-skipped run must strand them no more
    # than a successful one. Best-effort: a scheduling error only warns.
    if batch_key is None or workflow is None:
        return
    try:
        await reschedule_if_refilled(
            workflow_id,
            str(batch_key),
            coalesce_window_seconds(workflow.trigger_config),
            context or {},
        )
    except Exception as refill_error:
        log.warning(
            f"{LogTag.WORKER} Trigger batch refill check failed",
            workflow_id=workflow_id,
            error=str(refill_error),
            error_type=type(refill_error).__name__,
        )


async def _record_queued_fire(
    queued: WorkflowFireQueued,
    workflow: Workflow | None,
    workflow_id: str,
    execution_id: str | None,
    context: dict[str, Any] | None,
) -> str:
    # This fire never ran: one executor runs per conversation, and the
    # workflow's previous fire still held the lock, so this one went on the
    # queue. Completing it as "success" is what made every fire after the
    # first look like work on a workflow whose run outlasts its own cron
    # period, and the fake record then became the "last run" the NEXT fire
    # reads as its history. It is not a failure to notify about either: the
    # queued task runs on its own and delivers its own result, so this path
    # sends neither the completion nor the failure notification.
    log.set_ns(
        "workflow",
        queued=True,
        queued_task_id=queued.task_id,
        outcome="queued_behind_in_flight_run",
    )
    log.warning(
        f"{LogTag.WORKER} Workflow fire queued behind its previous run — nothing executed",
        workflow_id=workflow_id,
        queued_task_id=queued.task_id,
    )
    if execution_id:
        await complete_execution(
            execution_id=execution_id,
            status="failed",
            error_message=QUEUED_MESSAGE,
            conversation_id=queued.conversation_id,
            trace=queued.trace,
        )
    # Counted like any other fire that produced no result, so the workflow's
    # success ratio reflects what actually happened.
    await WorkflowService.increment_execution_count(
        workflow_id, queued.user_id, is_successful=False
    )
    await _rearm_quietly(workflow_scheduler, workflow, context, workflow_id)
    return f"Workflow {workflow_id} did not run — queued behind its previous run"


async def _record_overlapped_fire(
    overlapped: WorkflowFireOverlapped,
    workflow: Workflow | None,
    workflow_id: str,
    execution_id: str | None,
    context: dict[str, Any] | None,
) -> str:
    # This fire never ran either: its playbook replay found the workflow's
    # conversation already held by another run of the same workflow, and
    # dropped out rather than replay every side effect a second time. That
    # run delivers the result, so, as with the queued case, this is recorded
    # honestly and the user is told nothing.
    log.set_ns(
        "workflow",
        overlapped=True,
        lock_holder=overlapped.holder,
        outcome="overlapped_in_flight_run",
    )
    log.warning(
        f"{LogTag.WORKER} Workflow fire overlapped an in-flight run — nothing executed",
        workflow_id=workflow_id,
        conversation_id=overlapped.conversation_id,
        lock_holder=overlapped.holder,
    )
    if execution_id:
        await complete_execution(
            execution_id=execution_id,
            status="skipped",
            summary=OVERLAPPED_SUMMARY,
            conversation_id=overlapped.conversation_id,
        )
    await WorkflowService.increment_execution_count(
        workflow_id, overlapped.user_id, is_successful=False
    )
    await _rearm_quietly(workflow_scheduler, workflow, context, workflow_id)
    return f"Workflow {workflow_id} did not run — overlapped an in-flight run"


async def _record_fire_that_never_ran(
    never_ran: WorkflowFireQueued | WorkflowFireOverlapped,
    workflow: Workflow | None,
    workflow_id: str,
    execution_id: str | None,
    context: dict[str, Any] | None,
) -> str:
    if isinstance(never_ran, WorkflowFireQueued):
        return await _record_queued_fire(never_ran, workflow, workflow_id, execution_id, context)
    return await _record_overlapped_fire(never_ran, workflow, workflow_id, execution_id, context)


async def _record_timed_out_fire(
    workflow: Workflow | None,
    workflow_id: str,
    execution_id: str | None,
    context: dict[str, Any] | None,
) -> None:
    # The worker's job timeout cancels the job rather than raising into it,
    # so this is the only place a fire that ran out of time can be closed.
    # Seen live: a heal run whose model calls stalled for minutes each was
    # cut off at the limit and its record read "running" for good. Recorded
    # as failed and re-armed like any other failure; the caller re-raises the
    # cancel so ARQ sees the timeout it raised.
    timed_out = WorkflowFireTimedOut(WORKER_JOB_TIMEOUT_SECONDS)
    log.error(
        f"{LogTag.WORKER} Workflow fire cut off by the job timeout",
        workflow_id=workflow_id,
        error=str(timed_out),
        error_type=type(timed_out).__name__,
    )
    await _record_execution_failure(timed_out, workflow, workflow_id, execution_id)
    if workflow is not None:
        # Whatever the fire was replaying may have run its side effects
        # before the cut. Recorded as a failed run so the next fire heals
        # with that on record instead of replaying them again.
        await playbook_repository.record_run_outcome(
            workflow_id,
            workflow.user_id,
            PlaybookRunOutcome(PlaybookRunStatus.FAILED, reason=str(timed_out)),
        )
    await _rearm_quietly(workflow_scheduler, workflow, context, workflow_id)


async def execute_workflow_by_id(
    ctx: dict[str, Any],  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    workflow_id: str,
    context: dict[str, Any] | None = None,
) -> str:
    """
    Execute a workflow by ID with proper execution count tracking.
    """
    log.set(workflow_id=workflow_id)
    actual_fire_utc = datetime.now(UTC)
    log.set(actual_fire_utc=actual_fire_utc.isoformat())
    log.info(f"{LogTag.WORKER} Processing workflow execution", workflow_id=workflow_id)

    # Process-wide singleton, initialized once by init_workflow_service(). A
    # per-job instance opened its own ARQ Redis pool on every execution and
    # closed it in `finally` — thousands of pool churns an hour, which drove
    # the worker into repeated OOM kills.
    scheduler = workflow_scheduler
    workflow = None
    execution_id = None
    # Resolved before the try so the finally's refill check can see it on
    # every exit path.
    batch_key = (context or {}).get("trigger_batch_key")

    try:
        workflow = await scheduler.get_task(workflow_id)

        if not workflow:
            return f"Workflow {workflow_id} not found"

        # A coalesced trigger run carries its events (keyed by batch_key) in
        # Redis rather than in the job payload, so that concurrent enqueues
        # could dedup down to this one job. Drained only AFTER the gates below
        # — a run the onboarding or budget gate rejects must leave the buffer
        # intact for a later run, not consume the events and discard them.

        # Everything below runs as this kind of work: the budget wall, the run's
        # own tiered limit, and every rate-limited tool the agent reaches.
        trigger_type = _derive_trigger_type(context)
        mark_run_origin(_origin_for(trigger_type))
        log.set(
            workflow=WorkflowContext(
                id=workflow_id,
                trigger_type=trigger_type,
                steps_count=len(workflow.steps),
            )
        )

        skipped = await _admit_fire(workflow, workflow_id, trigger_type, context, actual_fire_utc)
        if skipped:
            return skipped

        # Cost wall BEFORE any execution record or LLM work: when the user's
        # daily budget is spent the run is skipped cleanly (no confusing
        # "failed" row) and the except branch below sends the budget-specific
        # notification + re-arms the next occurrence, so a recurring workflow
        # resumes after the budget resets.
        await enforce_daily_cost_budget(
            workflow.user_id,
            feature_key="trigger_workflow_executions",
        )

        # Both gates passed — take the batch.
        context, skip_reason = await _drain_trigger_events(batch_key, context, workflow_id)
        if skip_reason:
            return skip_reason

        # Create execution record at start (before running, so the failure
        # handler below can reference it).
        execution = await create_execution(
            workflow_id=workflow_id,
            user_id=workflow.user_id,
            trigger_type=trigger_type,
        )
        execution_id = execution.execution_id

        return await _run_and_record_success(
            workflow, workflow_id, trigger_type, context, execution_id
        )

    except (WorkflowFireQueued, WorkflowFireOverlapped) as never_ran:
        # Recorded on the wide event from the block that caught it; the helper
        # below is bookkeeping only. Neither is a failure to alert on.
        log.warning(
            f"{LogTag.WORKER} Workflow fire did not run",
            workflow_id=workflow_id,
            reason=str(never_ran),
            error_type=type(never_ran).__name__,
        )
        return await _record_fire_that_never_ran(
            never_ran, workflow, workflow_id, execution_id, context
        )
    except asyncio.CancelledError:
        await _record_timed_out_fire(workflow, workflow_id, execution_id, context)
        raise
    except Exception as e:
        # Logged here, in the block that caught it, so the wide event carries
        # the error from the fire's own frame; the helper only does bookkeeping.
        cause = _unwrapped(e)
        if isinstance(cause, RateLimitExceededException):
            # User hit their plan's workflow-execution quota: an expected,
            # by-design outcome, not a worker failure. WARNING keeps it off the
            # ARQ failed-task alert.
            log.warning(
                f"{LogTag.WORKER} Workflow skipped — rate limit exceeded",
                workflow_id=workflow_id,
                error=str(cause),
                error_type=type(cause).__name__,
            )
        else:
            log.exception(
                f"{LogTag.WORKER} Error executing workflow",
                workflow_id=workflow_id,
                error=str(cause),
                error_type=type(cause).__name__,
            )
        return await _record_run_failure(e, workflow, workflow_id, execution_id, context)
    finally:
        await _reschedule_refill_safe(workflow, workflow_id, batch_key, context)


async def _resolve_workflow_user(workflow: Workflow, user_id: str) -> AuthenticatedUser:
    """The user bag a workflow run executes as, with its home zone resolved.

    There is no request header here (ARQ worker), so prefer the real profile
    zone; fall back to the workflow's own schedule zone before UTC so a missing
    or poisoned profile doesn't silently run hours off. Both run paths read the
    zone off ``user_data["timezone"]`` — the agent through ``build_agent_config``,
    the replay through ``$now`` / ``$today``.
    """
    try:
        # The legacy bridge dict is a spread of a validated UserDocument plus
        # the user_id stamped below — AuthenticatedUser's shape by construction
        # (Type Safety item 12).
        user_data = cast(AuthenticatedUser, await get_user_by_id(user_id) or {})
        user_data["user_id"] = user_id

        profile_tz = (user_data.get("timezone") or "").strip()
        # trigger_config always declares timezone, so read it directly. Unset or
        # blank becomes None rather than a spelled-out UTC fallback: Timezone.parse
        # already answers UTC for None, and a literal here would be a branch no
        # input can reach.
        stored_schedule_tz = workflow.trigger_config.timezone
        schedule_tz = stored_schedule_tz.strip() if stored_schedule_tz else None
        resolved_tz = Timezone.parse(
            profile_tz if profile_tz and profile_tz.upper() != "UTC" else (schedule_tz or None)
        )
        if resolved_tz.is_utc:
            log.warning(
                f"{LogTag.WORKER} Workflow agent time falling back to UTC; "
                "no real user/schedule timezone",
                workflow_id=workflow.id,
                user_id=user_id,
            )
        log.set(workflow_agent_timezone=resolved_tz.value)
        user_data["timezone"] = resolved_tz.value
    except Exception as e:
        log.warning(
            f"{LogTag.WORKER} Could not resolve workflow timezone",
            user_id=user_id,
            workflow_id=workflow.id,
            error_type=type(e).__name__,
            error=str(e),
        )
        user_data = {"user_id": user_id}
    return user_data


# Deliberately NOT decorated with ``tiered_rate_limit``. One fire must cost the
# user exactly one execution against their plan quota, and a replay that stops
# partway hands the run to the agent path — which carries the decorator. Charging
# here as well would bill twice for one result, so a user whose playbook drifts
# would burn their quota at double rate because OUR optimisation failed. The
# caller charges the successful-replay case explicitly instead. Real resource
# consumption is metered separately by ``enforce_daily_cost_budget``, which is
# where "it genuinely ran twice" belongs.
async def execute_workflow_as_playbook(
    workflow: Workflow,
    user: AuthenticatedUser,
    context: dict[str, Any],
    playbook: PlaybookDocument,
) -> tuple[str, PlaybookRunResult]:
    """Replay the workflow's playbook in its conversation.

    Returns the conversation id and the replay's own report. A stopped replay is
    NOT an exception: it comes back with ``ok=False`` so the caller can hand the
    rest of the run to the agent knowing exactly what already happened. The
    turn itself is written by the caller once the outcome is recorded, because
    how the text is labelled depends on that outcome.

    The replay holds the conversation's executor busy lock for its whole
    duration — the same lock ``call_executor`` takes for an agentic run — so
    two fires of one workflow can never replay at once, and a replay can never
    run alongside an agentic run of the same workflow. A held lock raises
    :class:`WorkflowFireOverlapped` before any step runs; nothing waits and
    nothing is queued.
    """
    user_id = user["user_id"]
    user_data = await _resolve_workflow_user(workflow, user_id)
    conversation_id = await get_or_create_workflow_conversation(
        workflow_id=workflow.id,
        user_id=user_id,
        workflow_title=workflow.title,
    )

    # Same lock value shape as call_executor's; a replay has no stream, so the
    # value is ":{task_id}" (build_lock_value(None, ...) == build_lock_value("", ...)).
    task_id = str(uuid4())
    if not await try_acquire_lock(
        f"{EXECUTOR_BUSY_PREFIX}{conversation_id}", build_lock_value(None, task_id)
    ):
        holder = await get_lock_holder(conversation_id) or ""
        log.warning(
            f"{LogTag.WORKER} Playbook replay skipped; another run of this workflow "
            "holds its conversation",
            workflow_id=workflow.id,
            conversation_id=conversation_id,
            lock_holder=holder,
        )
        raise WorkflowFireOverlapped(
            user_id=user_id, conversation_id=conversation_id, holder=holder
        )

    try:
        result = await run_playbook(
            playbook,
            user=PlaybookUser(
                email=user_data.get("email") or "",
                name=user_data.get("name") or "",
                timezone=user_data.get("timezone") or Timezone.utc().value,
            ),
            conversation_id=conversation_id,
            trigger=context,
        )
    finally:
        await release_lock_if_owned(conversation_id, "", task_id)
    return conversation_id, result


# The plan-quota charge moved up to ``_run_workflow``, which is now the single
# place a fire is billed — see the note there. It cannot live here any more:
# a replay that stops partway calls this function to finish the run, and one
# result must never cost the user two executions. The seam still reads the run's
# origin, which execute_workflow_by_id sets from trigger_type.
async def execute_workflow_as_chat(
    workflow: Workflow, user: AuthenticatedUser, context: dict[str, Any]
) -> tuple[str, list[RecordedCall]]:
    """Run a workflow as a silent chat turn; return its conversation id and trace.

    The workflow is fed to the agent exactly like an interactive chat turn (same
    ``call_agent_silent`` entry, same ``selectedWorkflow`` awareness). Comms
    delegates the whole workflow to the executor, which runs every step and
    synthesizes one result. That result is delivered as the workflow-completion
    notification from the background executor path (gated by ``workflow_id`` in
    the trigger context), so this function only kicks off the run and persists
    the trigger message; it does not build or send the result here.

    The run's tool calls come back as the trace so the caller can persist them on
    the execution record — the next run reads that instead of replaying this one
    out of the conversation's checkpoints, which is why they are reset below.
    """

    # Avoid circular import
    from app.agents.core.agent import (  # noqa: PLC0415 -- agent cycle
        AgentRunOptions,
        call_agent_silent,
    )

    user_id = user["user_id"]

    try:
        log.info(
            f"{LogTag.WORKER} Executing workflow as chat session",
            workflow_id=workflow.id,
            user_id=user_id,
        )

        user_data = await _resolve_workflow_user(workflow, user_id)

        # Get or create the workflow conversation for thread context
        conversation_id = await get_or_create_workflow_conversation(
            workflow_id=workflow.id,
            user_id=user_id,
            workflow_title=workflow.title,
        )
        log.set(conversation_context_found=bool(conversation_id))

        # Drop the checkpoint threads this conversation accumulated, so the run
        # starts clean instead of replaying every previous run. The previous run
        # reaches the executor as its recorded trace (see call_executor).
        if settings.WORKFLOW_THREAD_RESET_ENABLED:
            await reset_workflow_threads(conversation_id)

        selected_workflow_data = build_selected_workflow_data(workflow)

        # Persist the trigger as the user message. The text is left empty so the
        # UI renders just the workflow card (via selectedWorkflow), not a literal
        # "Run workflow: ..." bubble. The result is saved by the delivery path.
        trigger_message = MessageModel(
            type="user",
            response="",
            date=datetime.now(UTC).isoformat(),
            message_id=str(uuid4()),
            selectedWorkflow=selected_workflow_data,
        )
        await add_workflow_execution_messages(
            conversation_id=conversation_id,
            workflow_execution_messages=[trigger_message],
            user_id=user_id,
        )

        request = MessageRequestWithHistory(
            message=f"Execute workflow: {workflow.title}",
            messages=[],
            fileIds=[],
            fileData=[],
            selectedTool=None,
            selectedWorkflow=selected_workflow_data,
        )

        # Same entry as chat, silent. workflow_id/title in the trigger context
        # routes the executor's final result to the completion notification.
        result = await call_agent_silent(
            request=request,
            conversation_id=conversation_id,
            user=user_data,
            options=AgentRunOptions(
                trigger_context={
                    **(context or {}),
                    "workflow_id": workflow.id,
                    "workflow_title": workflow.title,
                    "workflow_notify_on_completion": workflow.notify_on_completion,
                    "execution_mode": "background",
                }
            ),
        )

        # `call_agent_silent` returns the accumulated bag; its "tool_data" list is
        # the ordered entries (executor's and its subagents') this run emitted.
        entries = cast(list[ToolDataEntry], result.tool_data.get("tool_data") or [])
        trace = build_trace(entries)

        # Comms delegated, and the delegation was queued behind the workflow's
        # PREVIOUS fire, which still holds this conversation's executor lock. The
        # comms reply is an acknowledgement of work that has not started, so this
        # fire produced nothing and must not come back as a normal result.
        if result.queued_task_id:
            raise WorkflowFireQueued(
                task_id=result.queued_task_id,
                user_id=user_id,
                conversation_id=conversation_id,
                trace=trace,
            )

        return conversation_id, trace

    except WorkflowFireQueued:
        # Not an agent error — a fire that never started. Straight past the
        # error logging below, to the caller's own terminal handling.
        raise
    except Exception as e:
        # Re-raise so caller marks execution as failed instead of fake-success.
        log.error(
            "workflow_chat_execution_failed",
            workflow_id=workflow.id,
            workflow_title=getattr(workflow, "title", None),
            user_id=user.get("user_id") if isinstance(user, dict) else None,
            error_type=type(e).__name__,
            error=str(e)[:500],
            outcome="agent_error",
            exc_info=True,
        )
        raise


async def regenerate_workflow_steps(
    ctx: dict[str, Any],  # noqa: ARG001 -- framework contract
    workflow_id: str,
    user_id: str,
    regeneration_reason: str,
    force_different_tools: bool = True,
) -> str:
    """
    Regenerate workflow steps for an existing workflow.

    Args:
        ctx: ARQ context
        workflow_id: ID of the workflow to regenerate steps for
        user_id: ID of the user who owns the workflow
        regeneration_reason: Reason for regeneration
        force_different_tools: Whether to force different tools

    Returns:
        Processing result message
    """
    log.set(workflow_id=workflow_id, user_id=user_id, user={"id": user_id})
    log.info(
        f"{LogTag.WORKER} Regenerating workflow steps",
        workflow_id=workflow_id,
        user_id=user_id,
        reason=regeneration_reason,
    )

    # Import here to avoid circular imports
    from app.services.workflow.service import WorkflowService  # noqa: PLC0415 -- cycle

    # Regenerate steps using the service method (without background queue)
    await WorkflowService.regenerate_workflow_steps(
        workflow_id,
        user_id,
        regeneration_reason,
        force_different_tools,
    )

    log.info(f"{LogTag.WORKER} Successfully regenerated workflow steps", workflow_id=workflow_id)
    return f"Successfully regenerated steps for workflow {workflow_id}"


async def generate_workflow_steps(ctx: dict[str, Any], workflow_id: str, user_id: str) -> str:  # noqa: ARG001 -- contract
    """
    Generate workflow steps for a workflow.
    Broadcasts WebSocket event when complete if it's a todo workflow.

    Args:
        ctx: ARQ context
        workflow_id: ID of the workflow to generate steps for
        user_id: ID of the user who owns the workflow

    Returns:
        Processing result message
    """
    log.set(workflow_id=workflow_id, user_id=user_id)
    # Import here to avoid circular imports
    from app.services.workflow.service import WorkflowService  # noqa: PLC0415 -- cycle

    # Generate steps using the service method
    await WorkflowService._generate_workflow_steps(workflow_id, user_id)

    # Fetch the updated workflow to get the generated steps
    updated_workflow = await WorkflowService.get_workflow(workflow_id, user_id)

    if updated_workflow:
        log.set(
            workflow=WorkflowContext(
                id=workflow_id,
                steps_count=len(updated_workflow.steps),
            )
        )

    # If this is a todo workflow, send WebSocket event
    if updated_workflow and updated_workflow.is_todo_workflow and updated_workflow.source_todo_id:
        try:
            websocket_manager = get_websocket_manager()
            await websocket_manager.broadcast_to_user(
                user_id,
                {
                    "type": "workflow.generated",
                    "todo_id": updated_workflow.source_todo_id,
                    "workflow": updated_workflow.model_dump(mode="json"),
                },
            )
            log.set(websocket_broadcast_success=True)
        except Exception as ws_error:
            log.set(websocket_broadcast_success=False)
            log.warning(
                f"{LogTag.WORKER} Failed to send WebSocket event",
                error_type=type(ws_error).__name__,
                error=str(ws_error),
                workflow_id=workflow_id,
                user_id=user_id,
            )

    log.info(f"{LogTag.WORKER} Successfully generated workflow steps", workflow_id=workflow_id)
    return f"Successfully generated steps for workflow {workflow_id}"
