"""
ARQ worker tasks for executing scheduled tracked todos.

Handles:
- Acquiring Redis locks to prevent double-execution
- Retry logic with exponential backoff
- Workflow-based and agent-based execution paths
- Recurrence scheduling (re-enqueue after success)
- Safety-net cron for orphaned todos
"""

from datetime import UTC, datetime, timedelta
import random
from typing import Any, cast
from uuid import uuid4

from arq.connections import ArqRedis

from app.agents.core.agent import call_agent_silent
from app.constants.notifications import CHANNEL_TYPE_INAPP, NOTIFICATION_KIND_TODO_DONE
from app.constants.todos import FACET_DELIVERABLE, FACET_LOG, FACET_NOTES, FAILED_LABEL
from app.db.repositories.todos import todo_repository
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    ChannelConfig,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.models.todo_models import ExecutionStatus, TodoDocument, TodoUpdate
from app.models.user_models import AuthenticatedUser
from app.services.model_service import get_default_model
from app.services.notification_service import notification_service
from app.services.todo_canvas_storage import read_facet
from app.services.todos import gaia_todo_lifecycle as lifecycle
from app.services.tracked_todo_service import tracked_todo_service
from app.services.user_service import get_user_by_id
from app.utils.cron_utils import CronError, get_next_run_time
from app.utils.redis_utils import RedisPoolManager
from app.utils.timezone import Timezone
from shared.py.wide_events import log, wide_task

MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF = [timedelta(hours=1), timedelta(hours=4)]
LOCK_TTL_SECONDS = 1800


async def _load_user_with_tz(user_id: str) -> tuple[AuthenticatedUser, Timezone]:
    """Fetch user record once and resolve their home timezone.

    Returns (user_data with user_id populated, Timezone). Uses the canonical
    Timezone value object so a stored ±HH:MM offset doesn't crash ZoneInfo;
    falls back to UTC if the user record or timezone is missing.
    """
    try:
        user_data = await get_user_by_id(user_id)
        if user_data:
            user_data["user_id"] = user_id
            # The legacy bridge dict is a spread of a validated UserDocument plus
            # the user_id stamped above, which is exactly AuthenticatedUser's
            # shape — cast, not isinstance (Type Safety item 12). Narrowing it to
            # the fields the agent reads would drop `onboarding`, which
            # construct_langchain_messages needs for custom instructions.
            return cast(AuthenticatedUser, user_data), Timezone.parse(user_data.get("timezone"))
        return {"user_id": user_id}, Timezone.utc()
    except Exception as e:
        log.warning("tracked_todo.load_user_failed", user_id=user_id, error=str(e))
        return {"user_id": user_id}, Timezone.utc()


async def execute_tracked_todo(_ctx: dict[str, Any], todo_id: str) -> str:
    """
    ARQ task: execute a single scheduled tracked todo.

    Acquires a Redis lock to prevent concurrent execution, then delegates
    to the retry/execution helper. The lock is always released in the
    finally block.
    """
    async with wide_task("execute_tracked_todo", todo_id=todo_id):
        log.info("tracked_todo.execute_started", todo_id=todo_id)

        pool = await RedisPoolManager.get_pool()
        lock_key = f"gaia_todo_exec:{todo_id}"

        acquired = await pool.set(lock_key, "1", nx=True, ex=LOCK_TTL_SECONDS)
        if not acquired:
            log.info("tracked_todo.execute_lock_held", todo_id=todo_id)
            return f"skipped:{todo_id} (lock held)"

        try:
            return await _execute_todo_with_retry(todo_id, pool)
        finally:
            await pool.delete(lock_key)


async def _execute_todo_with_retry(todo_id: str, pool: ArqRedis) -> str:
    """
    Fetch the todo document, run the appropriate execution path, and
    handle retry / recurrence logic on the result.
    """
    doc = await todo_repository.get_by_id(todo_id)
    if not doc:
        log.warning("tracked_todo.execute_not_found", todo_id=todo_id)
        return f"not_found:{todo_id}"

    if doc.completed:
        log.info("tracked_todo.execute_already_completed", todo_id=todo_id)
        return f"completed:{todo_id}"

    # Skip expired todos — let maintenance sweep handle gracefully
    if doc.expires_at and doc.expires_at <= datetime.now(UTC):
        log.info(
            "tracked_todo.execute_expired",
            todo_id=todo_id,
            expires_at=doc.expires_at.isoformat(),
        )
        return f"expired:{todo_id}"

    # Skip failed todos — the user must retry (POST /todos/{id}/retry clears this
    # label) before re-execution.
    if FAILED_LABEL in doc.labels:
        log.info("tracked_todo.execute_marked_failed", todo_id=todo_id)
        return f"skipped:{todo_id} (marked failed)"

    user_id: str = doc.user_id
    retry_count: int = doc.gaia_retry_count

    if not user_id:
        log.error("tracked_todo.execute_missing_user_id", todo_id=todo_id)
        return f"error:{todo_id} (missing user_id)"

    # Single user fetch per run — pattern matches workflow_tasks.py:416–427.
    # Reused for both agent execution (timezone/model config) and the next-run
    # computation below, so a tz change takes effect on the next fire without
    # an extra DB round-trip.
    user_data, user_tz = await _load_user_with_tz(user_id)

    try:
        await lifecycle.mark_execution_status(todo_id, user_id, ExecutionStatus.RUNNING)
        run_summary = await _run_execution(doc, user_id, user_data=user_data)

        # Resolve the post-run state. The agent may have completed the todo
        # mid-run (DONE), or turned it into a proposal awaiting approval, or hit
        # a blocker (needs_you) — leave those. Otherwise: a recurring todo
        # re-arms to queued for its next fire; a one-shot work order (no
        # recurrence) is DONE now that its run finished — it produced its
        # deliverable and must not linger "in progress" forever.
        post = await todo_repository.get_by_id(todo_id)
        post_status = post.execution_status if post else None
        if (
            post
            and not post.completed
            and post_status not in (ExecutionStatus.PROPOSED, ExecutionStatus.NEEDS_YOU)
        ):
            if doc.recurrence:
                await lifecycle.mark_execution_status(todo_id, user_id, ExecutionStatus.QUEUED)
            else:
                await tracked_todo_service.complete_tracked_todo(
                    todo_id, user_id, summary="Completed overnight by GAIA."
                )

        # Ping the user when a run actually finished (DONE), scoped so goal-lane
        # prep stays silent — the morning brief narrates those instead.
        await _notify_done_if_scoped(todo_id, user_id, doc, run_summary)

        # scheduled_at must always name the NEXT planned execution — it is the
        # field find_due_tracked_all_users selects on, so a value left pointing
        # at the run that just happened makes the safety net re-enqueue this
        # todo on every scan. Recurrence is evaluated in the user's stored
        # timezone (looked up once at the top of this run).
        next_run = (
            _compute_next_run(doc.recurrence, user_tz.value, anchor=doc.scheduled_at)
            if doc.recurrence
            else None
        )
        await todo_repository.update(
            todo_id,
            user_id=user_id,
            update=TodoUpdate(gaia_retry_count=0, scheduled_at=next_run),
        )

        if next_run:
            await pool.enqueue_job(
                "execute_tracked_todo",
                todo_id,
                _defer_until=next_run,
            )
            log.info(
                "tracked_todo.re_enqueued",
                todo_id=todo_id,
                next_run=next_run.isoformat(),
            )

        return f"success:{todo_id}"

    except Exception as exc:
        log.exception("tracked_todo.execution_failed", todo_id=todo_id, error=str(exc))
        new_retry_count = retry_count + 1

        if new_retry_count >= MAX_RETRY_ATTEMPTS:
            await todo_repository.update(
                todo_id, user_id=user_id, update=TodoUpdate(gaia_retry_count=new_retry_count)
            )
            await _mark_todo_failed(todo_id, user_id, doc)
            return f"failed:{todo_id} (max retries reached)"

        # Compute backoff delay
        backoff_index = min(new_retry_count - 1, len(RETRY_BACKOFF) - 1)
        backoff = RETRY_BACKOFF[backoff_index]
        next_attempt = datetime.now(UTC) + backoff
        # Park scheduled_at on the backoff target as well: left in the past it
        # keeps matching the safety net's due-query, which would fire the retry
        # on the next 30-minute scan and flatten the 1h/4h ladder.
        await todo_repository.update(
            todo_id,
            user_id=user_id,
            update=TodoUpdate(gaia_retry_count=new_retry_count, scheduled_at=next_attempt),
        )
        await pool.enqueue_job(
            "execute_tracked_todo",
            todo_id,
            _defer_until=next_attempt,
        )
        log.info(
            "tracked_todo.retry_enqueued",
            todo_id=todo_id,
            next_attempt=next_attempt.isoformat(),
            attempt=new_retry_count,
            max_attempts=MAX_RETRY_ATTEMPTS,
        )
        return f"retry:{todo_id} (attempt {new_retry_count})"


async def _run_execution(doc: TodoDocument, user_id: str, *, user_data: AuthenticatedUser) -> str | None:
    """
    Dispatch execution to the correct path:
    - If the todo has a workflow_id, queue the workflow (no summary to return).
    - Otherwise, run the agent directly and return its completion summary.
    """
    workflow_id: str | None = doc.workflow_id

    if workflow_id:
        # Deferred import to avoid circular dependency
        from app.services.workflow.queue_service import WorkflowQueueService

        context = {
            "trigger_type": "scheduled_todo",
            "todo_id": doc.id,
        }
        success = await WorkflowQueueService.queue_workflow_execution(workflow_id, user_id, context)
        if not success:
            raise RuntimeError(f"Failed to queue workflow {workflow_id} for todo {doc.id}")
        log.info(
            "tracked_todo.workflow_queued",
            workflow_id=workflow_id,
            todo_id=doc.id,
        )
        return None
    return await _execute_via_agent(doc, user_id, user_data=user_data)


def _extract_learnings(ref_canvas: str) -> str | None:
    """Return the ``## Learnings`` section of a canvas, or None if absent."""
    if not ref_canvas or "## Learnings" not in ref_canvas:
        return None
    learnings_start = ref_canvas.index("## Learnings")
    next_section = ref_canvas.find("\n## ", learnings_start + 1)
    if next_section != -1:
        return ref_canvas[learnings_start:next_section]
    return ref_canvas[learnings_start:]


async def _collect_reference_context(ref_ids: list[str], user_id: str) -> str:
    """Gather ``## Learnings`` from up to 5 referenced todos for prompt context."""
    if not ref_ids:
        return ""
    ref_parts: list[str] = []
    for ref_id in ref_ids[:5]:  # Cap at 5 to avoid context bloat
        try:
            ref_doc = await todo_repository.get_by_id(ref_id)
            if not ref_doc:
                continue
            learnings = _extract_learnings(await read_facet(ref_id, user_id, FACET_NOTES))
            if learnings:
                ref_parts.append(
                    f'From past todo "{ref_doc.title or "Unknown"}":\n{learnings.strip()}'
                )
        except Exception as e:
            log.debug("execute_todo.reference_read_failed", ref_id=ref_id, error=str(e))
            continue
    if not ref_parts:
        return ""
    return "\n\nPast experience (from similar completed todos):\n" + "\n\n".join(ref_parts)


# How to save results. The deliverable is the whole point — it is what the user
# sees and what Approve releases — so it must be the finished output, clean and
# complete, kept apart from GAIA's scratch. This directive is what stops the
# canvas from becoming a mixed blob of research + logs + half-drafts.
_FACET_AUTHORING_DIRECTIVE = (
    "This is a background prep run. Do the REAL work (research the web, draft, "
    "compile) and never invent facts (no fabricated names, numbers, or quotes; "
    "if you can't verify it, leave it out).\n\n"
    "CRITICAL: this todo has SEPARATE facets, not one canvas with sections. "
    "Where results go decides whether the user ever sees them:\n"
    "- Your process (research, findings, drafts-in-progress, the plan) goes in "
    "NOTES: update_tracked_todo_canvas(todo_id, facet='notes', ...).\n"
    "- Your run is NOT finished until you have written the COMPLETE, polished "
    "output to the DELIVERABLE facet as the final step:\n"
    "    update_tracked_todo_canvas(todo_id, facet='deliverable', mode='replace', "
    "content=<the whole finished result>)\n"
    "  The deliverable is the actual thing the user uses or sends (the real code, "
    "the real vetted list, the real drafts), complete, with NO placeholders like "
    "[Name] and NO research/log/'Work Order' sections mixed in. This is exactly "
    "what the user reads and what Approve releases.\n"
    "- Do NOT put a '## Deliverable' or '## Output' section inside notes. The "
    "finished output lives ONLY in the deliverable facet; notes must never hold it.\n"
    "- log: one short line of what you did this run.\n"
    '- Before finishing, end NOTES with a "## Learnings" section: 2-4 bullets a '
    "FUTURE run on a similar task must know, written for a stranger: what worked, "
    'what to avoid, key contacts/links/IDs with dates (e.g. "Replies came only '
    'from subject lines naming their portfolio company", "foo@fund.com bounced '
    '2026-07-09, use their partner form"). Not a diary of this run; only reusable '
    "knowledge.\n\n"
    "Before you finish, check: is the complete finished result in the DELIVERABLE "
    "facet (not just notes)? If not, write it there now. If a real value doesn't "
    "exist yet, do the work to get it; never ship a placeholder.\n\n"
    "THE BAR: the user must be able to tap Approve without editing a single word. "
    "For each draft, match the target channel's real format: an email gets a "
    "specific subject line and a first line only its recipient could receive (a "
    "researched fact about them: their fund's recent investment, their post, their "
    "product); a LinkedIn post gets a hook line and short paragraphs; a tweet fits "
    "the length and reads native. Before writing the deliverable, do the "
    "recipient/audience research the draft depends on. Final check: read the "
    "deliverable as the user would; if they would change anything before sending, "
    "fix it now, in this run.\n\n"
    "Anything a human will read in the deliverable (emails, posts, messages, docs) "
    "must sound like the USER wrote it, not an LLM: vary sentence length, open on "
    "the point (no 'I hope this finds you well'), use plain words, take a position "
    "instead of hedging, and never use an em dash or filler like 'delve', "
    "'seamless', 'leverage', or 'excited to connect'. Keep it natural and specific, "
    "not forced or quirky."
)


# The user APPROVED this proposal — this run must PERFORM the outward action from
# the (already-final) deliverable, not re-draft it. Without this an approved run
# hits the prep directive above and just rewrites the draft, so nothing is sent.
_RELEASE_DIRECTIVE = (
    "The user has APPROVED this; your job now is to PERFORM the action, not to "
    "draft, plan, or propose it. Actually send the emails, post the content, or "
    "create the records described above, using the EXACT approved content in the "
    "deliverable and the appropriate connected integration (Gmail, LinkedIn, X, "
    "etc.). Do NOT reword, re-draft, re-plan, or ask again: the content is final "
    "and approved. Send to EXACTLY the recipients/destinations named in the "
    "deliverable and no others.\n"
    "Sends are per-recipient. The send record above lists any recipient already "
    "marked sent; those are DONE, so never send to them again, even on a retry. As "
    "each send completes or fails, immediately append one line to the log facet "
    "(update_tracked_todo_canvas, facet='log'): recipient, outcome, confirmation "
    "ID. One failure does not stop the rest: complete every remaining recipient, "
    "then report the exact split ('sent 3 of 5: A, B, C; failed for D (bounce), E "
    "(rate limit)'). A partial send is reported as partial: never round it up to "
    "done, and never re-send a success to make the count clean. If the integration "
    "is not connected at all, STOP and say so plainly; never claim anything was "
    "sent when it was not.\n"
    "The log facet is the permanent record of this release: the briefing and "
    "every future follow-up run read it, so it must contain the full recipient "
    "list, timestamps, and confirmation IDs even when everything succeeded."
)


def _build_execution_prompt(
    *,
    title: str,
    description: str,
    deliverable: str | None,
    notes: str | None,
    reference_context: str,
    intent: str | None = None,
    log_facet: str | None = None,
    instruction: str | None = None,
) -> str:
    """Assemble the scheduled-run prompt from the todo's facets and context.

    ``intent='release'`` means the user approved this proposal, so the run must
    PERFORM the outward action from the deliverable instead of doing prep/drafting.
    For a release, the LOG facet is injected as the send record so a retry sees
    which recipients already went out — instead of trusting the agent to fetch it.
    ``instruction`` is the user's verbatim qualification at approval; it overrides
    the staged content where they conflict.
    """
    if intent == "release":
        parts = [f"APPROVED ACTION — execute this now: {title}"]
        if description:
            parts.append(f"What was approved: {description}")
        if deliverable:
            parts.append(
                f"The approved content to send/perform (final — do not change it):\n{deliverable}"
            )
        if instruction and instruction.strip():
            parts.append(
                "The user approved WITH an instruction, in their own words — follow "
                "it exactly; where it narrows or adjusts the approved content (e.g. "
                "send only a subset), the instruction wins over the staged content:\n"
                f"{instruction.strip()}"
            )
        if log_facet and log_facet.strip():
            parts.append(
                "Send record from previous runs (recipients already marked sent are "
                f"DONE — never send to them again):\n{log_facet.strip()}"
            )
        if reference_context:
            parts.append(reference_context)
        parts.append(_RELEASE_DIRECTIVE)
        return "\n\n".join(parts)

    prompt_parts = [f"Execute the following scheduled task: {title}"]
    if description:
        prompt_parts.append(f"Details: {description}")
    if notes:
        prompt_parts.append(f"Working notes:\n{notes}")
    if deliverable:
        prompt_parts.append(f"Current deliverable:\n{deliverable}")
    if reference_context:
        prompt_parts.append(reference_context)
    prompt_parts.append(_FACET_AUTHORING_DIRECTIVE)
    return "\n\n".join(prompt_parts)


# An approved (release) run must actually PERFORM the outward action. We verify
# this from the run's REAL tool results, not the agent's prose — the agent can
# fabricate what it *says* ("sent, msg-12345") but not what a tool *returns*.
# Deterministic + free (no model call, which matters when the primary model is
# unavailable): a release counts as performed only if a tool whose name denotes
# an outward action (send/post/create — NOT a draft or a read) was actually
# invoked. Limitation: a called-but-errored action still counts; refine to parse
# tool outputs when a real end-to-end trace is available to validate against.
_RELEASE_ACTION_VERBS = (
    "SEND",
    "POST",
    "PUBLISH",
    "SUBMIT",
    "REPLY",
    "CREATE",
    "ADD",
    "INSERT",
    "UPDATE",
    "DELETE",
)
_RELEASE_NAME_KEYS = ("tool_name", "name", "tool", "toolName")


def _collect_tool_names(blob: object) -> list[str]:
    """Recursively pull every tool-name string out of a tool_data structure,
    flattening nested subagent groups (the send may run inside a sub-agent)."""
    names: list[str] = []
    if isinstance(blob, dict):
        for key in _RELEASE_NAME_KEYS:
            v = blob.get(key)
            if isinstance(v, str) and v and v not in ("subagent_group", "tool_calls_data"):
                names.append(v)
        for v in blob.values():
            names.extend(_collect_tool_names(v))
    elif isinstance(blob, list):
        for item in blob:
            names.extend(_collect_tool_names(item))
    return names


def _release_performed(tool_data: object) -> bool:
    """True if the run actually invoked an outward-action tool (not a draft/read).

    Integration/composio tools that reach external services are UPPER_SNAKE
    (``GMAIL_SEND_EMAIL``); GAIA's own internal tools are lower_snake
    (``update_tracked_todo_canvas``) — only the former perform outward actions, so
    an internal tool that merely *contains* an action verb (update/create) never
    counts.
    """
    for raw in _collect_tool_names(tool_data):
        if not raw.isupper():
            continue
        if "DRAFT" in raw:
            continue
        if any(verb in raw for verb in _RELEASE_ACTION_VERBS):
            return True
    return False


async def _execute_via_agent(
    doc: TodoDocument, user_id: str, *, user_data: AuthenticatedUser
) -> str:
    """
    Execute the todo using call_agent_silent directly (no workflow needed).

    Returns the first 200 chars of the agent response.
    """
    todo_id = doc.id

    user_model_config = None
    try:
        user_model_config = await get_default_model()
    except Exception as exc:
        log.warning("tracked_todo.model_config_failed", todo_id=todo_id, error=str(exc))

    # Read the notes + deliverable facets from the todo's Mongo-backed fields.
    # A release run also reads the LOG facet: it holds the per-recipient send
    # record so a retry never double-sends a recipient that already went out.
    notes: str | None = None
    deliverable: str | None = None
    log_facet: str | None = None
    is_release = doc.execution_intent == "release"
    try:
        notes = await read_facet(todo_id, user_id, FACET_NOTES)
        deliverable = await read_facet(todo_id, user_id, FACET_DELIVERABLE)
        if is_release:
            log_facet = await read_facet(todo_id, user_id, FACET_LOG)
    except Exception as exc:
        log.warning(
            "tracked_todo.facet_read_failed",
            todo_id=todo_id,
            error=str(exc),
        )

    # Read referenced notes for institutional memory
    reference_context = await _collect_reference_context(doc.references, user_id)

    # Build prompt
    title: str = doc.title or "Untitled Todo"
    prompt = _build_execution_prompt(
        title=title,
        description=doc.description or "",
        deliverable=deliverable,
        notes=notes,
        reference_context=reference_context,
        intent=doc.execution_intent,
        log_facet=log_facet,
        instruction=doc.approve_instruction,
    )

    # Generate a fresh conversation_id for each execution to prevent
    # history accumulation in PostgreSQL. Each execution is independent.
    conversation_id = str(uuid4())

    # Persisted up front so the dashboard can link into the live run, not just
    # the finished one.
    await todo_repository.update(
        todo_id,
        user_id=user_id,
        update=TodoUpdate(last_run_conversation_id=conversation_id),
    )

    # The human turn must be in `messages` — construct_langchain_messages does
    # not consult `message` alone when no workflow/tool is selected, so an empty
    # list fails the run with "No human message or selected tool".
    request = MessageRequestWithHistory(
        message=prompt,
        messages=[MessageDict(role="user", content=prompt)],
        fileIds=[],
        fileData=[],
        selectedTool=None,
    )

    trigger_context = {
        "trigger_type": "scheduled_todo",
        "todo_id": todo_id,
        "todo_title": title,
        "active_todo_id": todo_id,
        "execution_mode": "background",
        # Lane-child prep todos (linked to a goal) run silently overnight — the
        # morning briefing reports them, so no per-todo chat ping.
        "suppress_platform_delivery": bool(doc.goal_id),
    }

    # Structural paper trail — write a start marker to the canvas Timeline
    # BEFORE the agent runs, so the run leaves evidence even if the LLM forgets.
    short_conv = conversation_id[:8]
    start_iso = datetime.now(UTC).isoformat()
    await tracked_todo_service.append_activity_marker(
        todo_id=todo_id,
        user_id=user_id,
        entry=f"▶ {start_iso} — scheduled run started (conversation_id={short_conv})",
    )

    complete_message: str = ""
    try:
        complete_message, tool_data = await call_agent_silent(
            request=request,
            conversation_id=conversation_id,
            user=user_data,
            user_model_config=user_model_config,
            trigger_context=trigger_context,
        )

        if complete_message and complete_message.startswith("Error when calling silent agent:"):
            raise RuntimeError(complete_message)
    except Exception as exc:
        # End marker: failure
        fail_iso = datetime.now(UTC).isoformat()
        await tracked_todo_service.append_activity_marker(
            todo_id=todo_id,
            user_id=user_id,
            entry=f"✗ {fail_iso} — scheduled run failed ({type(exc).__name__})",
        )
        raise

    # End marker: success
    end_iso = datetime.now(UTC).isoformat()
    summary = (complete_message or "").strip().replace("\n", " ")[:120]
    await tracked_todo_service.append_activity_marker(
        todo_id=todo_id,
        user_id=user_id,
        entry=f"✓ {end_iso} — scheduled run finished (summary={summary!r})",
    )

    # Honesty gate for approved (release) runs: the agent may claim it sent when
    # it only drafted or did nothing. Verify from the REAL tool results — if no
    # outward-action tool actually ran, DON'T let this be marked done/sent; flip
    # it to needs_you with the truth so the user is never told a lie.
    if is_release and not _release_performed(
        tool_data.get("tool_data") if isinstance(tool_data, dict) else tool_data
    ):
        log.warning("tracked_todo.release_not_performed", todo_id=todo_id)
        await lifecycle.mark_execution_status(
            todo_id,
            user_id,
            ExecutionStatus.NEEDS_YOU,
            blocker_question=(
                "GAIA prepared this but couldn't confirm the send actually went "
                "through. Retry the send, or will you handle it yourself?"
            ),
        )

    log.info("tracked_todo.agent_completed", todo_id=todo_id)
    return complete_message[:200] if complete_message else ""


async def _notify_done_if_scoped(
    todo_id: str, user_id: str, doc: TodoDocument, run_summary: str | None
) -> None:
    """In-app ping when a run finished (DONE), scoped to work the user asked for.

    Fires only for a release run (approved outward action) or a standalone todo
    (no ``goal_id``). Goal-lane prep completions stay silent — the morning brief
    narrates them. Explicit ``inapp`` channel so this never double-delivers over
    chat (standalone chat delivery already happens in the run). Best-effort: the
    completion is already persisted, so a delivery failure only drops the ping.

    Workflow-backed todos are excluded: they carry their own completion
    notification (WORKFLOW_DONE_COPY), so a second ping here would double up.
    """
    if doc.workflow_id:
        return
    final = await todo_repository.get_by_id(todo_id)
    if not final or final.execution_status != ExecutionStatus.DONE:
        return
    if doc.execution_intent != "release" and doc.goal_id:
        return

    title: str = final.title or "your todo"
    body = (run_summary or "").strip()[:200] or "GAIA finished this and it's ready for you."
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=NotificationType.SUCCESS,
                channels=[ChannelConfig(channel_type=CHANNEL_TYPE_INAPP)],
                content=NotificationContent(
                    title=f"Shipped: {title}",
                    body=body,
                    actions=[
                        NotificationAction(
                            type=ActionType.REDIRECT,
                            label="Open todo",
                            style=ActionStyle.PRIMARY,
                            config=ActionConfig(
                                redirect=RedirectConfig(
                                    url=f"/todos?todoId={todo_id}",
                                    open_in_new_tab=False,
                                    close_notification=True,
                                )
                            ),
                        )
                    ],
                ),
                metadata={"kind": NOTIFICATION_KIND_TODO_DONE, "todo_id": todo_id},
            )
        )
    except Exception as notify_exc:
        log.warning(
            "tracked_todo.done_notification_failed",
            todo_id=todo_id,
            error=str(notify_exc),
        )


async def _mark_todo_failed(todo_id: str, user_id: str, doc: TodoDocument) -> None:
    """
    Mark the todo as permanently failed by adding a 'failed' label,
    then send an in-app notification to the user.
    """
    await todo_repository.add_labels(todo_id, user_id=user_id, labels=[FAILED_LABEL])
    await lifecycle.mark_execution_status(
        todo_id,
        user_id,
        ExecutionStatus.FAILED,
        error_message=f"Execution failed after {MAX_RETRY_ATTEMPTS} attempts",
    )
    log.info("tracked_todo.marked_failed", todo_id=todo_id)

    title: str = doc.title or "Untitled Todo"
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=NotificationType.ERROR,
                content=NotificationContent(
                    title=f"Scheduled Task Failed: {title}",
                    body=(
                        f"Your scheduled task '{title}' could not be completed after "
                        f"{MAX_RETRY_ATTEMPTS} attempts. Please check the task and try again."
                    ),
                ),
                metadata={
                    "todo_id": todo_id,
                    "retry_count": MAX_RETRY_ATTEMPTS,
                },
            )
        )
    except Exception as notify_exc:
        log.warning(
            "tracked_todo.failure_notification_failed",
            todo_id=todo_id,
            error=str(notify_exc),
        )


def _compute_next_run(
    recurrence: str,
    recurrence_tz: str | None = None,
    anchor: datetime | None = None,
) -> datetime | None:
    """
    Compute the next scheduled run time from a recurrence string.

    Evaluated in the user's timezone (recurrence_tz, IANA name). Returned as
    a UTC-aware datetime suitable for ARQ's _defer_until.

    Supports named shortcuts:
    - "daily"    → next occurrence at the anchor's local wall-clock time
    - "weekly"   → next occurrence at the anchor's local weekday + time
    - "every_4h" → +4 hours (interval)
    - "every_1h" → +1 hour (interval)

    "daily"/"weekly" are anchored to ``anchor`` (the original scheduled_at) so
    a late run does NOT drift the wall-clock time forward. The next fire keeps
    the anchor's local time-of-day and advances by whole days/weeks until it is
    strictly in the future. Without an anchor we fall back to a plain delta.

    Falls back to croniter for cron expressions (e.g. "0 9 * * *"), which are
    evaluated in recurrence_tz so "9am" means user-local 9am.
    Returns None if the recurrence string is unrecognised.
    """
    # Canonical, offset-safe zone resolution (a stored ±HH:MM won't crash here).
    home_tz = Timezone.parse(recurrence_tz)
    tz = home_tz.tzinfo

    now_utc = datetime.now(UTC)

    interval_shortcuts: dict[str, timedelta] = {
        "every_4h": timedelta(hours=4),
        "every_1h": timedelta(hours=1),
    }
    if recurrence in interval_shortcuts:
        # Intervals are deltas from "now" — drift is acceptable/expected.
        return now_utc + interval_shortcuts[recurrence]

    anchored_steps: dict[str, timedelta] = {
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
    }
    if recurrence in anchored_steps:
        step = anchored_steps[recurrence]
        if anchor is None:
            # No anchor available — fall back to a plain delta from now.
            return now_utc + step
        # Anchor to the original local wall-clock time. Advance whole
        # days/weeks from the anchor until strictly after now, preserving
        # the time-of-day (and weekday for weekly).
        anchor_local = anchor.astimezone(tz)
        next_local = anchor_local
        if next_local <= now_utc.astimezone(tz):
            elapsed = now_utc.astimezone(tz) - anchor_local
            steps_to_skip = (elapsed // step) + 1
            next_local = anchor_local + step * steps_to_skip
        return next_local.astimezone(UTC)

    # Cron expression — evaluate in the user's local timezone via the canonical
    # helper (single source of cron-in-zone math + observability).
    try:
        return get_next_run_time(recurrence, now_utc, home_tz)
    except CronError:
        log.warning("tracked_todo.next_run_unrecognised", recurrence=recurrence)
        return None


async def safety_net_check_orphaned_todos(_ctx: dict[str, Any]) -> str:
    """
    Cron safety net: find scheduled tracked todos that should have run but
    were never picked up (e.g. worker was down, job was lost).

    Queries todos where:
    - scheduled_at <= now
    - completed = False
    - assignee == "gaia"
    - gaia_retry_count < MAX_RETRY_ATTEMPTS

    For each, checks whether the execution lock already exists; if not,
    re-enqueues with a random 0–60 second jitter to spread load.
    """
    async with wide_task("safety_net_check_orphaned_todos"):
        now = datetime.now(UTC)
        log.info("tracked_todo.safety_net_scan_started")

        docs = await todo_repository.find_due_tracked_all_users(
            now=now, max_retries=MAX_RETRY_ATTEMPTS, limit=100
        )

        pool = await RedisPoolManager.get_pool()
        re_enqueued = 0
        skipped = 0

        for doc in docs:
            todo_id = doc.id
            lock_key = f"gaia_todo_exec:{todo_id}"

            lock_exists = await pool.exists(lock_key)
            if lock_exists:
                skipped += 1
                continue

            # Random jitter: 0–60 seconds
            jitter_seconds = random.randint(0, 60)  # nosec B311  # NOSONAR python:S2245 — non-crypto scheduling jitter
            run_at = now + timedelta(seconds=jitter_seconds)
            await pool.enqueue_job("execute_tracked_todo", todo_id, _defer_until=run_at)
            re_enqueued += 1
            log.info(
                "tracked_todo.safety_net_re_enqueued",
                todo_id=todo_id,
                run_at=run_at.isoformat(),
            )

        log.info(
            "tracked_todo.safety_net_done",
            re_enqueued=re_enqueued,
            skipped=skipped,
        )
        return f"re_enqueued:{re_enqueued} skipped:{skipped}"
