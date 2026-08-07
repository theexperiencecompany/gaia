"""
Tracked todo service — Mongo-backed lifecycle for GAIA's working memory todos.

A tracked todo is a regular todo with:
- vfs_path (display label) set to /users/{user_id}/todos/{todo_id}/
- assignee == "gaia" (the discriminator for GAIA-owned todos)
- facet content on the doc: deliverable / notes (agent-written, indexed in
  ChromaDB) and log (system-written audit trail)

Facet content lives on the todo document itself — see
``app/services/todo_canvas_storage.py`` for the storage primitives. No
JuiceFS / FUSE mount is required, so tracked todos work in every dev mode.
"""

from datetime import UTC, datetime
import re

from app.constants.todos import (
    ASSIGNEE_GAIA,
    DELIVERABLE_TEMPLATE,
    FACET_DELIVERABLE,
    FACET_LOG,
    FACET_NOTES,
    NOTES_TEMPLATE,
    facet_from_doc,
)
from app.db.repositories.todos import todo_repository
from app.models.todo_models import (
    ExecutionStatus,
    Priority,
    TodoDocument,
    TodoModel,
    TodoResponse,
    TodoUpdate,
)
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from app.services.todo_canvas_storage import (
    append_facet,
    build_vfs_label,
    read_facet,
)
from app.services.todos import gaia_todo_lifecycle as lifecycle
from app.services.todos.todo_service import TodoService
from app.utils.analytics import track
from app.utils.canvas_vector_utils import (
    mark_canvas_completed,
    store_canvas_embedding,
    update_canvas_embedding,
)
from shared.py.wide_events import log


def _pin_active_todo(docs: list[TodoDocument], active_todo_id: str | None) -> None:
    """Move the matching todo to the front of `docs` in-place (no-op if not found)."""
    if not active_todo_id:
        return
    for i, d in enumerate(docs):
        if d.id == active_todo_id and i > 0:
            docs.insert(0, docs.pop(i))
            return


def _format_due_string(due_date: datetime | None, now: datetime) -> str:
    """Render the due-date suffix: ` due(Nd)`, ` OVERDUE(Nd)`, or empty."""
    if not due_date:
        return ""
    days_until = (due_date - now).days
    if days_until < 0:
        return f" OVERDUE({-days_until}d)"
    return f" due({days_until}d)"


# Capture everything under the "## Key Details" heading up to the next "## "
# heading (or end of text). A tempered greedy token — "any char that does not
# begin a new section" — avoids a reluctant quantifier entirely.
_KEY_DETAILS_RE = re.compile(r"## Key Details\n((?:(?!\n## ).)*)", re.DOTALL)
_KEY_DETAILS_MAX_LINES = 5


async def _extract_canvas_key_details(doc: TodoDocument, user_id: str) -> str:
    """Pull the Key Details section text from a tracked todo's notes (empty on miss)."""
    todo_id = doc.id
    try:
        notes = await read_facet(todo_id, user_id, FACET_NOTES)
    except Exception as e:
        log.warning(
            "tracked_todo.notes_read_failed",
            todo_id=todo_id,
            error=str(e),
        )
        return ""
    if not notes:
        return ""
    match = _KEY_DETAILS_RE.search(notes)
    return match.group(1).strip() if match else ""


def _format_signal_entry(doc: TodoDocument, key_details: str) -> str:
    """Render one tracked todo as a signal-matching context bullet (+ indented key details)."""
    labels_str = f" [{', '.join(doc.labels)}]" if doc.labels else ""
    entry = f'- "{doc.title}"{labels_str} (ID: {doc.id}, vfs: {doc.vfs_path or ""})'
    if key_details:
        for dl in key_details.split("\n")[:_KEY_DETAILS_MAX_LINES]:
            entry += f"\n    {dl.strip()}"
    return entry


def _format_tracked_todo_line(doc: TodoDocument, now: datetime, active_todo_id: str | None) -> str:
    """Format one tracked-todo doc as a context-injection summary line.

    State (and the blocker question, when waiting) is what lets the agent act
    on a chat reply — "yes send it" needs the proposed item, an answer needs
    the blocked one.
    """
    age_days = (now - (doc.created_at or now)).days
    last_update = (now - (doc.updated_at or now)).days
    labels_str = f" [{', '.join(doc.labels)}]" if doc.labels else ""
    todo_id = doc.id
    prefix = "⭐ ACTIVE " if todo_id == active_todo_id else ""
    state = doc.execution_status
    state_str = f" | state: {state.value}" if state else ""
    if state == ExecutionStatus.NEEDS_YOU and doc.blocker_question:
        state_str += f' | waiting on user: "{doc.blocker_question}"'
    return (
        f'  {prefix}"{doc.title}"{labels_str}{_format_due_string(doc.due_date, now)}'
        f" — {age_days}d old, updated {last_update}d ago"
        f"{state_str} | ID: {todo_id} | VFS: {doc.vfs_path or 'none'}"
    )


# A staged proposal ships the exact content in its deliverable, so it must not
# carry unfilled template tokens — [Name], [industry], [specific problem].
# Matches a bracketed run that starts with a letter and is NOT a markdown link
# ([t](url), excluded by the negative lookahead) nor a task checkbox ([ ]/[x],
# excluded by requiring ≥2 inner chars).
_PLACEHOLDER_RE = re.compile(r"\[[A-Za-z][^\]\n]{1,60}\](?!\()")


def _has_unfilled_placeholders(text: str) -> bool:
    """True if the text still holds send-blocking template placeholders."""
    return _PLACEHOLDER_RE.search(text) is not None


def _embedding_text(notes: str | None, deliverable: str | None) -> str:
    """Concatenate the searchable facets (notes + deliverable) for one embedding.

    The log facet is audit noise and is deliberately excluded from the index.
    """
    parts = [p for p in (notes, deliverable) if p and p.strip()]
    return "\n\n".join(parts)


class TrackedTodoService:
    """Manages VFS lifecycle for tracked (GAIA working memory) todos.

    All methods are static — the service holds no instance state. The
    ``tracked_todo_service`` singleton is kept for call-site compatibility.
    """

    @staticmethod
    async def create_tracked_todo(
        user_id: str,
        title: str,
        serves: str,
        *,
        requires_approval: bool,
        kind: str = "task",
        goal_id: str | None = None,
        description: str | None = None,
        project_id: str | None = None,
        due_date: datetime | None = None,
        priority: Priority = Priority.NONE,
        labels: list[str] | None = None,
        initial_deliverable: str | None = None,
        initial_notes: str | None = None,
        auto_execute: bool = True,
    ) -> TodoResponse:
        """Create a GAIA-assigned todo with facet content and ChromaDB indexing.

        Creation is gated (the junk-todo fix): ``serves`` must trace the todo to
        a goal/memory/user request, and server-side budgets cap proposals and
        in-flight work. Entry state follows the approval rule:
        ``requires_approval`` (outward-facing) → ``proposed``; internal-only →
        ``queued``.
        """
        serves, entry_status = await lifecycle.gate_creation(
            user_id, serves, requires_approval, title=title, kind=kind
        )
        # The staging invariant behind every Approve button: a proposal releases
        # exactly the content in its DELIVERABLE facet, so it cannot be created
        # without it. Prep work happens first (internal todo), and the run that
        # finishes the prep creates the proposal carrying the deliverable.
        if entry_status is ExecutionStatus.PROPOSED and not (initial_deliverable or "").strip():
            raise lifecycle.TraceabilityError(
                "A proposal must carry its staged work: pass `initial_deliverable` "
                "with the exact content approving will release (drafts, list, post). "
                "If the content does not exist yet, create the internal prep todo "
                "first and stage this proposal when the prep run finishes."
            )
        # A proposal releases its deliverable verbatim, so template placeholders
        # would be sent literally ("Hi [Name], …"). Reject unfilled tokens at the
        # gate so the run must fill them with real values (or do the prep first).
        if entry_status is ExecutionStatus.PROPOSED and _has_unfilled_placeholders(
            initial_deliverable or ""
        ):
            raise lifecycle.TraceabilityError(
                "A proposal cannot ship template placeholders: the staged "
                "deliverable still has unfilled tokens like [Name] or [industry], so "
                "approving would release literal brackets. Fill every placeholder "
                "with the real value before staging — if you don't have it yet, do "
                "the prep to get it first."
            )

        # `assignee == "gaia"` is the discriminator now, so we no longer stamp
        # the `gaia-tracked` label (it was redundant and showed as a stray chip).
        all_labels = list(labels or [])

        # Create the todo
        todo = TodoModel(
            title=title,
            description=description,
            project_id=project_id,
            due_date=due_date,
            priority=priority,
            labels=all_labels,
            assignee=ASSIGNEE_GAIA,
            execution_status=entry_status,
            serves=serves,
            kind="goal" if kind == "goal" else "task",
            goal_id=goal_id,
        )
        result = await TodoService.create_todo(todo, user_id)
        todo_id = result.id
        if entry_status is not None:
            # Budgets are hard laws even under parallel tool calls (see
            # lifecycle.enforce_budget_post_insert).
            await lifecycle.enforce_budget_post_insert(user_id, todo_id, entry_status)

        # Persist facets + display label on the todo doc itself. A proposal
        # carries its finished deliverable; an internal todo starts from the
        # light template. Notes always seed from the working-memory template
        # unless the caller supplied a head start.
        vfs_path = build_vfs_label(user_id, todo_id)
        deliverable_content = initial_deliverable or DELIVERABLE_TEMPLATE.format(title=title)
        notes_content = initial_notes or NOTES_TEMPLATE.format(title=title)
        now = datetime.now(UTC)
        log_content = (
            f"# System Log: {title}\n\n"
            f"## {now.isoformat()} [CREATED]\n"
            f"- Source: agent\n"
            f"- Labels: {', '.join(all_labels)}\n"
        )

        await todo_repository.update(
            todo_id,
            user_id=user_id,
            update=TodoUpdate(
                vfs_path=vfs_path,
                deliverable_content=deliverable_content,
                notes_content=notes_content,
                log_content=log_content,
            ),
        )

        # Index notes + deliverable in ChromaDB (log is audit noise, skipped).
        await store_canvas_embedding(
            todo_id=todo_id,
            content=_embedding_text(notes_content, deliverable_content),
            user_id=user_id,
            title=title,
            labels=all_labels,
        )

        # Update result with vfs_path
        result.vfs_path = vfs_path

        log.info(
            "tracked_todo.created",
            todo_id=todo_id,
            user_id=user_id,
            title=title,
            vfs_path=vfs_path,
        )
        schedule_gaia_tasks_sync(user_id)
        if entry_status == ExecutionStatus.PROPOSED:
            track(user_id, "todo_proposed", {"todo_id": todo_id, "serves": serves})
        elif entry_status is ExecutionStatus.QUEUED and auto_execute:
            # The approval rule's other half: internal work executes without
            # permission — immediately, not only when a schedule happens to be
            # attached. Callers arming their own schedule pass auto_execute=False.
            await todo_repository.update(
                todo_id, user_id=user_id, update=TodoUpdate(scheduled_at=now)
            )
            await lifecycle.schedule_execution(todo_id, now)
        return result

    @staticmethod
    async def complete_tracked_todo(todo_id: str, user_id: str, summary: str) -> bool:
        """Complete a tracked todo: append completion to log, mark done, archive label."""
        doc = await todo_repository.get(todo_id, user_id=user_id)
        if not doc:
            return False

        # Guard against double-completion
        if doc.completed:
            return True

        vfs_path = doc.vfs_path or build_vfs_label(user_id, todo_id)
        now = datetime.now(UTC)

        # Append completion to log
        await append_facet(
            todo_id,
            user_id,
            FACET_LOG,
            f"\n## {now.isoformat()} [COMPLETED]\n- Summary: {summary}\n",
        )

        # Switch the display label to the archived form (purely cosmetic).
        archive_path = vfs_path.replace("/todos/", "/todos/archive/")

        # Update todo (the execution_status flip goes through the lifecycle so
        # the transition is broadcast; it also emits the completion track event).
        # The repository write invalidates the entity/query cache automatically.
        await todo_repository.update(
            todo_id,
            user_id=user_id,
            update=TodoUpdate(completed=True, completed_at=now, vfs_path=archive_path),
        )
        await lifecycle.mark_execution_status(todo_id, user_id, ExecutionStatus.DONE)

        # Mark as completed in ChromaDB (keep embedding but mark completed)
        await mark_canvas_completed(todo_id)

        log.info(
            "tracked_todo.completed",
            todo_id=todo_id,
            user_id=user_id,
            summary=summary,
        )
        schedule_gaia_tasks_sync(user_id)
        return True

    @staticmethod
    async def get_active_tracked_summary(user_id: str, active_todo_id: str | None = None) -> str:
        """Formatted summary of active tracked todos for context injection.

        When active_todo_id is provided, that todo is pinned at the top with
        an ⭐ ACTIVE marker so the agent can quickly identify the run's
        bound canvas.
        """
        # Dismissed/expired proposals are terminal — never re-surface them to
        # the agent (they teach via the strike summary instead).
        docs = await todo_repository.list_active_gaia_for_summary(user_id, limit=15)
        strikes = await lifecycle.get_rejection_strikes_summary(user_id)
        if not docs:
            return f"\n{strikes}" if strikes else ""

        _pin_active_todo(docs, active_todo_id)

        now = datetime.now(UTC)
        lines = ["ACTIVE TRACKED TODOS:"]
        lines.extend(_format_tracked_todo_line(doc, now, active_todo_id) for doc in docs)
        if strikes:
            lines.append(strikes)
        return "\n".join(lines)

    @staticmethod
    async def append_activity_marker(todo_id: str, user_id: str, entry: str) -> bool:
        """Append a chronological activity marker to the LOG facet.

        Called by code (not agent) to guarantee a paper trail for scheduled runs
        regardless of what the LLM writes. The log facet IS the activity
        timeline, so markers are appended to it directly (oldest first) — there
        is one home for chronological activity, not a duplicate Timeline section.
        """
        line = entry if entry.startswith("- ") else f"- {entry}"
        try:
            return await append_facet(todo_id, user_id, FACET_LOG, line)
        except Exception as e:
            log.warning(
                "tracked_todo.activity_marker_write_failed",
                todo_id=todo_id,
                error=str(e),
            )
            return False

    @staticmethod
    async def system_log(todo_id: str, user_id: str, event_type: str, details: str) -> None:
        """Append a system log entry to a tracked todo's log.

        Called by code (not agent) for audit trail. Agent writes to canvas.
        """
        await lifecycle.system_log(todo_id, user_id, event_type, details)

    @staticmethod
    async def get_signal_matching_context(user_id: str) -> str:
        """Compact tracked todos summary optimized for signal matching.

        Includes key IDs (thread_ids, email addresses, event_ids) so the
        agent can match incoming signals to relevant todos.
        """
        docs = await todo_repository.list_active_tracked(user_id, limit=15)
        if not docs:
            return ""

        lines = [
            _format_signal_entry(doc, await _extract_canvas_key_details(doc, user_id))
            for doc in docs
        ]
        return "ACTIVE TRACKED TODOS (check if incoming signal relates to any):\n" + "\n".join(
            lines
        )

    @staticmethod
    async def reindex_canvas(todo_id: str, user_id: str) -> bool:
        """Re-index a todo's notes + deliverable in ChromaDB after the agent writes.

        The searchable content is the notes and deliverable facets concatenated
        into the one-doc-per-todo embedding; the log facet is skipped.
        """
        doc = await todo_repository.get(todo_id, user_id=user_id)
        if not doc:
            return False

        allow_canvas_fallback = doc.execution_status == ExecutionStatus.PROPOSED
        raw = doc.model_dump()
        content = _embedding_text(
            facet_from_doc(raw, FACET_NOTES, allow_canvas_fallback=allow_canvas_fallback),
            facet_from_doc(raw, FACET_DELIVERABLE, allow_canvas_fallback=allow_canvas_fallback),
        )
        if not content:
            return False

        return await update_canvas_embedding(
            todo_id=todo_id,
            content=content,
            user_id=user_id,
            title=doc.title,
            labels=doc.labels,
        )

    @staticmethod
    async def schedule_execution(todo_id: str, scheduled_at: datetime) -> bool:
        """Enqueue an ARQ deferred job to execute this tracked todo at scheduled_at.

        Returns True if job was enqueued successfully, False otherwise.
        """
        return await lifecycle.schedule_execution(todo_id, scheduled_at)

    @staticmethod
    async def reschedule_execution(todo_id: str, new_scheduled_at: datetime) -> bool:
        """Cancel any existing ARQ job for this todo and enqueue a new one.

        Note: ARQ does not support cancelling deferred jobs by argument.
        We enqueue a new job; the task itself uses a Redis lock to prevent
        double-execution. This is safe — at most one execution fires per lock window.
        """
        return await lifecycle.reschedule_execution(todo_id, new_scheduled_at)

    @staticmethod
    async def archive_tracked_todo(todo_id: str, user_id: str, reason: str) -> bool:
        """Archive a tracked todo by marking it completed with a system-generated summary.

        Used by maintenance sweep when a todo expires cleanly (no action needed).
        Logs the archival reason to log.md before completing.
        """
        try:
            await TrackedTodoService.system_log(
                todo_id,
                user_id,
                "auto_archived",
                f"Archived by maintenance sweep: {reason}",
            )
            return await TrackedTodoService.complete_tracked_todo(
                todo_id, user_id, summary=f"Auto-archived: {reason}"
            )
        except Exception as e:
            log.warning("tracked_todo.archive_failed", todo_id=todo_id, error=str(e))
            return False


tracked_todo_service = TrackedTodoService()
