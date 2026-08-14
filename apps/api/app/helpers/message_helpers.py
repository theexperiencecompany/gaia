import asyncio
from datetime import UTC, datetime
from typing import Any, Literal, NamedTuple

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.prompts.onboarding_prompts import (
    ONBOARDING_FIRST_CONVERSATION_SYSTEM_PROMPT,
)
from app.agents.prompts.workflow_prompts import (
    EMAIL_TRIGGERED_WORKFLOW_PROMPT,
    SIGNAL_MATCHING_INSTRUCTIONS,
    WORKFLOW_AUTO_NOTIFY_SECTION,
    WORKFLOW_EXECUTION_PROMPT,
    WORKFLOW_SILENT_NOTIFY_SECTION,
)
from app.agents.templates.agent_template import (
    EXECUTOR_PROMPT_TEMPLATE,
    get_comms_static_prompt,
)
from app.agents.workspace.paths import (
    safe_upload_filename,
    session_dir,
)
from app.constants.chat import UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS
from app.db.redis import get_cache, set_cache
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.users import user_repository
from app.memory.engine import memory_engine
from app.memory.mappers import entry_to_note
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.models.todo_models import TodoDocument
from app.models.user_models import OnboardingPhase
from app.services.gaia_knowledge_service import gaia_knowledge_service
from app.services.integrations.user_integrations import get_connected_integrations_named
from app.services.tracked_todo_service import tracked_todo_service
from app.services.workflow import WorkflowService
from app.utils.artifact_utils import artifact_url_base
from app.utils.timezone import Timezone
from app.utils.user_preferences_utils import (
    format_user_preferences_for_agent,
)
from shared.py.wide_events import log

# Sentinel marker on dynamic-context SystemMessages so
# manage_system_prompts_node can keep only the latest one.
DYNAMIC_CONTEXT_MARKER = "dynamic_context"

# Sentinel marker on the memory-recall SystemMessage. This slot holds the
# byte-stable core memory documents (the always-on "what GAIA knows about this
# user" block). It carries its own marker so manage_system_prompts_node can
# slot it at the TAIL of the system block — after the byte-stable
# [static, dynamic] prefix — keeping that prefix cacheable across turns.
MEMORY_RECALL_MARKER = "memory_recall"

# Sentinel marker on the volatile per-turn tail (recent-activity journal,
# per-query memory recall, GAIA knowledge, skills, tracked todos, run-binding
# banners). This content churns every turn, so it lives AFTER the time
# message — the very last message in the request — where its churn never
# shifts the cached prefix ahead of it.
MEMORY_VOLATILE_MARKER = "memory_volatile"

# Cache-bounded size for the volatile memory-recall slot (see the cap in
# build_dynamic_context_messages). Head keeps the always-on core memory; the
# tail keeps the todo/run-banner directives; the churning middle is dropped.
MEMORY_RECALL_MAX_CHARS = 8_000
MEMORY_RECALL_HEAD_CHARS = 4_000
MEMORY_RECALL_TAIL_CHARS = 4_000

# Per-section caps for the volatile per-turn tail. Every byte of it churns
# turn-to-turn and is NEVER cached, so its total size directly caps the
# prompt-cache hit rate (~1k volatile chars costs ~3.5 points on a ~28k-token
# request); the caps below bound it to ~2300 chars so the hit rate can reach
# ~95%. The stable parts (user_stable_parts, core_memory_section) are NOT
# capped — they sit inside the cached prefix.
RECENT_ACTIVITY_CAP_CHARS = 300
MEMORIES_CAP_CHARS = 300
GAIA_KNOWLEDGE_CAP_CHARS = 100
SKILLS_CAP_CHARS = 100
TRACKED_TODOS_CAP_CHARS = 150
AGENDA_CAP_CHARS = 300

# Byte-stable truncation markers: identical every turn, so an overflowing
# section always emits marker + exactly `limit` chars regardless of how long
# the source content grows.
RECENT_ACTIVITY_TRUNC_MARKER = "...[recent activity truncated, newest entries kept]..."
MEMORIES_TRUNC_MARKER = "...[memory recall truncated, most relevant kept]..."
GAIA_KNOWLEDGE_TRUNC_MARKER = "...[GAIA knowledge truncated]..."
SKILLS_TRUNC_MARKER = "...[skills list truncated]..."
TRACKED_TODOS_TRUNC_MARKER = "...[tracked todos truncated]..."
AGENDA_TRUNC_MARKER = "...[agenda truncated, newest commitments kept]..."


def _cap_section(text: str, limit: int, marker: str) -> str:
    """Cap a volatile section's size without churning the truncation boundary.

    Returns ``text`` unchanged when it fits within ``limit`` characters.
    Otherwise keeps the LAST ``limit`` characters — for the recent-activity
    journal and recall results the newest / most-relevant content is at the
    end — and prepends the static ``marker`` line, so the emitted bytes are
    stable (marker + exactly ``limit`` chars) no matter how long the source
    grows.
    """
    if len(text) <= limit:
        return text
    return f"{marker}\n{text[-limit:]}"


def create_system_message(
    user_id: str | None = None,
    user_name: str | None = None,
    agent_type: Literal["comms", "executor"] = "comms",
    source: str | None = None,
) -> SystemMessage:
    """Return the STATIC main system prompt for the given agent.

    The content is byte-identical across every user on the same channel so
    the provider's implicit prompt cache can match across users — the first
    web user of the day warms the cache, every subsequent web user hits it
    on turn 1. For comms, the per-channel variants embed the output-format
    addendum (OpenUI on web/mobile/desktop; text-only restrictions on
    messaging platforms). The executor prompt is single-variant.

    All user, time, and memory context is delivered in the dynamic-context
    messages produced by ``build_dynamic_context_messages`` and does NOT live
    in this static prefix.
    """
    del user_id, user_name  # intentionally unused — static prefix only
    if agent_type == "executor":
        return SystemMessage(content=EXECUTOR_PROMPT_TEMPLATE)
    return SystemMessage(content=get_comms_static_prompt(source))


def build_current_time_message(
    user_timezone: str | None = None,
) -> HumanMessage:
    """Return a tiny HumanMessage carrying the current UTC + local time.

    We keep the clock OUT of ``system_instruction`` and put it in
    ``contents`` instead. Reason: Gemini's implicit cache matches the
    longest common prefix. Any byte in ``system_instruction`` that ticks
    every minute would push the cache boundary back to just before that
    byte, so a call at 00:59 and a call at 01:01 would share less prefix
    than they need to. Since ``contents`` already differ per turn anyway
    (the user's actual message differs), attaching the clock to contents
    costs us nothing on the cache budget but keeps ``system_instruction``
    fully stable.
    """
    utc_now = datetime.now(UTC).strftime("%A, %B %d, %Y, %H:%M UTC")
    parts = [f"[Current UTC Time: {utc_now}]"]
    if user_timezone:
        try:
            # Timezone.parse handles both IANA names and ±HH:MM offsets (ZoneInfo
            # raised on offsets, silently dropping this line).
            local_now = Timezone.parse(user_timezone).now().strftime("%A, %B %d, %Y, %H:%M")
            parts.append(f"[User Local Time ({user_timezone}): {local_now}]")
        except Exception as e:
            log.warning(
                "Error formatting user local time", error=str(e), error_type=type(e).__name__
            )
    return HumanMessage(
        content="\n".join(parts),
        additional_kwargs={"time_context": True},
    )


async def _get_user_memories_section(query: str, user_id: str) -> str:
    """
    Search for user's conversation memories and format them.

    Args:
        query: The search query
        user_id: The user's ID

    Returns:
        Formatted memories section or empty string
    """
    try:
        results = await memory_engine.recall(user_id, query, limit=5)
        if results.memories:
            log.info("Added memories to context", memories_count=len(results.memories))
            return (
                "\n\nBased on our previous conversations (bracketed dates say when "
                "something happened / was last mentioned):\n"
                + "\n".join(f"- {entry_to_note(mem)}" for mem in results.memories)
            )
    except Exception as e:
        log.warning(
            "Error retrieving memories", error=str(e), error_type=type(e).__name__, user_id=user_id
        )

    return ""


_CORE_MEMORY_HEADING = "What you remember about this user (memory core)"
_AGENDA_HEADING = "## Current agenda"
_RECENT_ACTIVITY_HEADING = "## Recent activity"


async def _get_core_memory_parts(user_id: str) -> tuple[str, str]:
    """Split the memory core into the byte-stable documents and the volatile
    per-turn tail content (agenda + recent-activity journal).

    The stable part (the user / assistant-conventions documents — identity,
    preferences, routines, ...) changes only when the consolidation pass
    rewrites it — NOT per turn — so it can sit in the cached prefix. The
    ``## Current agenda`` document (with its commitments / deadlines / owed
    items) and the recent-activity journal both churn every turn, so they must
    live in the volatile tail AFTER the time message. Redis-cached inside the
    engine (plan F1, sub-5ms steady state).

    Returns ``(stable_documents, volatile_tail_content)``; either may be "".
    """
    try:
        core_context = await memory_engine.get_core_context(user_id)
    except Exception as e:
        log.warning(
            "Error retrieving core memory context",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return "", ""
    if not core_context:
        return "", ""

    volatile_parts: list[str] = []
    # The agenda document churns every turn (reminders fire, deadlines move,
    # owed items resolve) — measured as a per-turn byte-divergence inside the
    # cached prefix; it belongs in the volatile tail.
    agenda_marker = f"\n\n{_AGENDA_HEADING}"
    if agenda_marker in core_context:
        stable, agenda = core_context.split(agenda_marker, 1)
        core_context = stable
        # Cap the agenda document so the volatile tail stays bounded. The
        # static heading stays outside the cap (readable even when the body
        # is truncated); the marker is byte-stable across turns.
        volatile_parts.append(
            f"{_AGENDA_HEADING}{_cap_section(agenda, AGENDA_CAP_CHARS, AGENDA_TRUNC_MARKER)}"
        )
    # The recent-activity journal grows/churns every turn (new entries land).
    activity_marker = f"\n\n{_RECENT_ACTIVITY_HEADING}"
    if activity_marker in core_context:
        stable, activity = core_context.split(activity_marker, 1)
        core_context = stable
        volatile_parts.append(f"{_RECENT_ACTIVITY_HEADING}{activity}")

    stable_core = f"{_CORE_MEMORY_HEADING}:\n{core_context}" if core_context else ""
    return stable_core, "\n\n".join(volatile_parts)


async def _core_memory_parts(user_id: str) -> tuple[str, str]:
    """Awaitable wrapper over :func:`_get_core_memory_parts` for gathers."""
    return await _get_core_memory_parts(user_id)


async def _empty_section() -> str:
    """Awaitable empty section, for gathers with conditionally skipped fetches."""
    return ""


async def _get_gaia_knowledge_section(query: str) -> str:
    """
    Search GAIA knowledge base (ChromaDB) and format results.

    Args:
        query: The search query

    Returns:
        Formatted knowledge section or empty string
    """
    try:
        results = await gaia_knowledge_service.search_knowledge(query=query, limit=5)
        if results:
            log.info("Added knowledge items to context", results_count=len(results))
            return "\n\nAbout Gaia (your identity and capabilities):\n" + "\n".join(
                f"- {result.content}" for result in results
            )
    except Exception as e:
        log.warning("Error retrieving GAIA knowledge", error=str(e), error_type=type(e).__name__)

    return ""


async def _get_tracked_todos_section(user_id: str, active_todo_id: str | None = None) -> str:
    """Fetch active tracked-todo summary with 60s Redis cache.

    When active_todo_id is set, bypasses cache so the pinned-todo marker
    reflects the current binding rather than a stale list.
    """
    if active_todo_id:
        # Pinned view is per-run-binding — caching it would cross-pollinate
        # other turns. Cheap call, not worth caching.
        return await tracked_todo_service.get_active_tracked_summary(
            user_id, active_todo_id=active_todo_id
        )

    cache_key = f"tracked_todos:summary:{user_id}"

    try:
        cached = await get_cache(cache_key)
        if cached:
            return cached if isinstance(cached, str) else str(cached)
    except Exception as cache_err:
        log.debug("tracked_todo_summary.cache_get_failed", error=str(cache_err))

    summary = await tracked_todo_service.get_active_tracked_summary(user_id)

    if summary:
        try:
            await set_cache(cache_key, summary, ttl=60)
        except Exception as cache_err:
            log.debug("tracked_todo_summary.cache_set_failed", error=str(cache_err))

    return summary


BACKGROUND_EXECUTION_BANNER = (
    "🤖 BACKGROUND EXECUTION (no human is reading this turn)\n"
    "   - You were woken by a scheduled trigger. There is no user to ask.\n"
    "   - Do NOT ask clarifying questions, present plans for approval, or seek confirmation.\n"
    '   - Do NOT produce conversational acknowledgements ("Sure, I\'ll…", "Let me know if…").\n'
    "   - Just execute. If you need a decision you cannot make, write the question into "
    "the active todo's canvas (Context section) and stop.\n"
    "   - Your output is consumed by the system, not a human. Be terse and action-only."
)


def build_workspace_session_banner(session_id: str) -> str:
    """State the agent's own session directory and the public artifact URL base.

    The agent never otherwise learns its conversation/session id, so a prompt
    that asks it to report an absolute ``/workspace/sessions/<id>/...`` path
    forces it to guess — and a weak model fabricates one, writing the
    deliverable outside the session the artifact watcher scans, where it is
    silently lost. Stating the real path removes the guess.

    The agent also knows a file's workspace path but not the URL the browser
    fetches it from, so it cannot link or embed an artifact (in an HTML page it
    generates, an email body, etc.). Stating the public URL base gives it the
    one fact it is missing.
    """
    return (
        f"Session directory: {session_dir(session_id)}\n"
        f"Public artifact URL: a file at `artifacts/<name>` is served at "
        f"{artifact_url_base(session_id)}/<name>"
    )


def _format_active_todo_banner(todo: TodoDocument) -> str:
    title = todo.title or "Untitled"
    todo_id = todo.id
    return (
        "🎯 ACTIVE TODO (this run is bound to this todo)\n"
        f"   id: {todo_id}\n"
        f"   title: {title}\n"
        "\n"
        "   Default write target for this turn: this todo's canvas.\n"
        f'   - Use `update_tracked_todo_canvas(todo_id="{todo_id}", ...)` for any progress, outcome, or learning from this run.\n'
        "   - Use `add_memory(...)` ONLY for durable cross-cutting facts unrelated to this todo (rare).\n"
        "   - To work on a different todo, you must reference it explicitly by id."
    )


async def _build_active_todo_banner(user_id: str, active_todo_id: str | None) -> str:
    if not active_todo_id:
        return ""
    try:
        doc = await todo_repository.get(active_todo_id, user_id=user_id)
        if not doc:
            return ""
        return _format_active_todo_banner(doc)
    except Exception as e:
        log.warning("active_todo_banner_fetch_failed", error=str(e))
        return ""


def _mark_dynamic_context(msg: SystemMessage) -> SystemMessage:
    """Mark a SystemMessage as dynamic context.

    Uses additional_kwargs so LangGraph / pydantic serialization preserves it
    across checkpointer round-trips. `manage_system_prompts_node` keeps only
    the latest message carrying this marker.
    """
    msg.additional_kwargs[DYNAMIC_CONTEXT_MARKER] = True
    # Back-compat: existing filter logic looks at `memory_message` too.
    msg.additional_kwargs.setdefault("memory_message", True)
    return msg


def _mark_memory_recall(msg: SystemMessage) -> SystemMessage:
    """Mark a SystemMessage as the volatile memory-recall slot.

    Only carries ``memory_recall`` — deliberately NOT the dynamic-context or
    ``memory_message`` markers — so ``manage_system_prompts_node`` slots it
    separately at the tail of the system block instead of collapsing it into
    the stable dynamic slot.
    """
    msg.additional_kwargs[MEMORY_RECALL_MARKER] = True
    return msg


def _mark_memory_volatile(msg: SystemMessage) -> SystemMessage:
    """Mark a SystemMessage as the volatile per-turn tail slot.

    Carries ``memory_volatile`` only, so ``manage_system_prompts_node`` places
    it AFTER the time message — the last message in the request — where its
    per-turn churn cannot shift the byte-stable prefix ahead of it.
    """
    msg.additional_kwargs[MEMORY_VOLATILE_MARKER] = True
    return msg


class DynamicContextMessages(NamedTuple):
    """The system messages that carry per-user, per-turn context.

    ``stable`` holds identity content (name, timezone, preferences, connected
    integrations) that changes only when preferences/integrations change — it
    stays at index 1 so the ``[static, stable]`` prefix is cacheable across
    turns. ``memory_recall`` holds the byte-stable core memory documents (the
    always-on "what GAIA knows about this user" block); ``None`` when there is
    no core to inject. ``volatile_tail`` holds the per-turn churning content
    (recent-activity journal, per-query memory recall, GAIA knowledge, skills,
    tracked todos, run banners) — placed after the time message, the last
    message in the request, so its churn never shifts the cached prefix.
    """

    stable: SystemMessage
    memory_recall: SystemMessage | None
    volatile_tail: SystemMessage | None = None


# Default header for the comms agent: pure capability awareness.
CONNECTED_INTEGRATIONS_HEADER = (
    "Connected integrations (hand off to the matching subagent to use them):"
)

# Header for the executor, which is the agent that actually performs handoffs.
# States that the list is live (fetched this turn), names the parenthesised id
# as the handoff subagent_id, and guards against treating always-available
# built-in subagents as "not connected" just because they are not listed here.
EXECUTOR_CONNECTED_INTEGRATIONS_HEADER = (
    "CONNECTED INTEGRATIONS (live snapshot of the user's currently connected accounts as of "
    "this turn; this is the latest connected set, so trust it over retrieve_tools for what is "
    "connected). To act on one, handoff to its subagent using the id in parentheses as the "
    "handoff subagent_id. If the user asks for a provider that is NOT listed here, STILL do the "
    "handoff: the handoff is what shows the user the connect card. Telling the user to connect "
    "WITHOUT handing off leaves them hunting for a button that was never rendered. Built-in "
    "subagents (reminders, todos, gaia_knowledge_guide, docgen) are always available and are "
    "not listed here:"
)


async def build_connected_integrations_manifest(
    user_id: str,
    header: str = CONNECTED_INTEGRATIONS_HEADER,
) -> str:
    """One line per connected integration so the agent knows what it can reach.

    Capability awareness only — the agent learns Slack/Linear/GitHub/etc. are
    available without first running tool retrieval. Detailed tool schemas still
    come from ``retrieve_tools`` at inference time. Names (platform and custom
    MCP) are resolved and cached by ``get_connected_integrations_named``.

    The parenthesised id is also the ``subagent_id`` the executor passes to
    ``handoff``. ``header`` lets each agent frame the same list for its own use
    (comms gets capability awareness; the executor gets handoff instructions).
    Each line reads ``- Name (id)``, collapsing to ``- id`` only when the name
    is the id itself, so a custom integration whose name equals its id never
    renders the value twice.
    """
    try:
        items = await get_connected_integrations_named(user_id)
    except Exception as e:
        log.warning(
            "Error building connected-integrations manifest",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return ""
    if not items:
        return ""
    lines = [header]
    for item in items:
        iid, name = item["id"], item["name"]
        lines.append(f"- {name} ({iid})" if name and name != iid else f"- {iid}")
    return "\n".join(lines)


async def build_dynamic_context_messages(
    user_id: str | None,
    query: str | None,
    user_name: str | None = None,
    user_timezone: str | None = None,
    user_preferences: dict[str, Any] | None = None,
    writing_style: dict[str, Any] | None = None,
    source: str | None = None,
    include_openui: bool = False,
    memories_text: str | None = None,
    skills_text: str | None = None,
    active_todo_id: str | None = None,
    execution_mode: Literal["interactive", "background"] = "interactive",
) -> DynamicContextMessages:
    """Build the dynamic-context system messages, split by volatility.

    Returns TWO messages so the provider's implicit prompt cache survives
    across turns:

    - ``stable``: the byte-stable identity block (user name, timezone,
      preferences, connected-integrations manifest). It changes only when the
      user edits preferences or connects/disconnects an integration — NOT per
      turn — so ``manage_system_prompts_node`` keeps it at index 1 and the
      ``[static, stable]`` prefix stays cacheable across every turn.
    - ``memory_recall``: the byte-stable core memory documents. They change
      only when the consolidation pass rewrites them — NOT per turn — so they
      are slotted at the TAIL of the system block (after the stable prefix)
      and stay cacheable. ``None`` when the user has no core memory.
    - ``volatile_tail``: everything that churns turn-to-turn (agenda,
      recent-activity journal, per-query memory recall, GAIA knowledge,
      installable skills, tracked-todos summary, and — on bound / headless
      runs — the run-binding banners). Slotted AFTER the time message, so its
      churn never shifts the cacheable bytes ahead of it, and capped
      head+tail at ``MEMORY_RECALL_MAX_CHARS`` so its per-request token cost
      stays bounded. ``None`` when there is no volatile content to inject.

    OpenUI / platform restrictions and the clock are NOT here:

    - Output-format addendums (OpenUI or text-only) are part of the static
      per-channel prompt so they cache across every user on that channel.
    - Current time lives in a HumanMessage so minute ticks never invalidate
      the ``system_instruction`` prefix.

    Args:
        user_id: For memory/knowledge retrieval. If None, skips ChromaDB calls.
        query: Search query for memory/knowledge retrieval.
        user_name: User's display name.
        user_timezone: IANA timezone string (used to format the address in the
            static body; the actual clock is emitted in a HumanMessage).
        user_preferences: Onboarding preferences.
        source: Conversation source (web, whatsapp, telegram, ...). Preserved
            on the wide event for observability; doesn't change what's here.
        include_openui: Preserved for signature compatibility. OpenUI now
            lives in the static per-channel prompt, not this message.
        memories_text: Pre-fetched memories section. If provided, skips the
            ChromaDB lookup.
        skills_text: Pre-fetched skills section. Same rationale as memories.
        active_todo_id: When this run is bound to a tracked todo, appends the
            active-todo banner (canvas write-target directive) LAST in the
            volatile tail, so the directive gets recency.
        execution_mode: When "background" (headless scheduled run), appends the
            background-execution banner so the agent stays terse and action-only.

    Returns:
        A ``DynamicContextMessages`` — ``stable`` marked ``dynamic_context``
        (and ``memory_message`` for back-compat), ``memory_recall`` marked
        ``memory_recall``, and ``volatile_tail`` marked ``memory_volatile``
        (each of the latter two ``None`` when empty).
    """
    del include_openui  # accepted for back-compat; OpenUI is in static prompt now
    try:
        user_stable_parts: list[str] = []
        variable_parts: list[str] = []

        # --- Stable across turns for this user -----------------------------
        if user_name:
            user_stable_parts.append(f"User Name: {user_name}")
        if user_timezone:
            user_stable_parts.append(f"User Timezone: {user_timezone}")
        if user_preferences or writing_style:
            if formatted := format_user_preferences_for_agent(
                user_preferences or {}, writing_style=writing_style
            ):
                user_stable_parts.append(f"User Preferences:\n{formatted}")
        # Connected-integrations manifest sits with the stable block: it only
        # changes when the user connects/disconnects an integration, not per turn.
        if user_id:
            if manifest := await build_connected_integrations_manifest(user_id):
                user_stable_parts.append(manifest)

        # --- Fetches (may change turn-to-turn) -----------------------------
        # Core memory context (engine-cached, invalidated on ingestion) is
        # fetched in the same gather as the per-query lookups. It splits into
        # the byte-stable documents (the memory_recall slot, inside the cached
        # prefix) and the volatile recent-activity journal (the volatile tail,
        # after the time message): the journal churns every turn and must not
        # sit inside the prefix (measured: it was the dominant per-turn
        # uncached chunk, capping the comms hit rate ~10 points below the
        # harness ceiling).
        if memories_text is not None:
            memories_section = memories_text
            gaia_knowledge_section = ""
            if user_id:
                (core_stable, recent_activity), gaia_knowledge_section = await asyncio.gather(
                    _core_memory_parts(user_id),
                    _get_gaia_knowledge_section(query) if query else _empty_section(),
                )
                core_memory_section = core_stable
            else:
                core_memory_section, recent_activity = "", ""
        elif user_id and query:
            (
                (core_stable, recent_activity),
                memories_section,
                gaia_knowledge_section,
            ) = await asyncio.gather(
                _core_memory_parts(user_id),
                _get_user_memories_section(query, user_id),
                _get_gaia_knowledge_section(query),
            )
            core_memory_section = core_stable
        else:
            core_stable, recent_activity = (
                await _core_memory_parts(user_id) if user_id else ("", "")
            )
            core_memory_section = core_stable
            memories_section = ""
            gaia_knowledge_section = ""

        if core_memory_section:
            variable_parts.append(core_memory_section)
        if recent_activity:
            variable_parts.append(
                _cap_section(
                    recent_activity.lstrip("\n"),
                    RECENT_ACTIVITY_CAP_CHARS,
                    RECENT_ACTIVITY_TRUNC_MARKER,
                )
            )
        if memories_section:
            variable_parts.append(
                _cap_section(
                    memories_section.lstrip("\n"),
                    MEMORIES_CAP_CHARS,
                    MEMORIES_TRUNC_MARKER,
                )
            )
        if gaia_knowledge_section:
            variable_parts.append(
                _cap_section(
                    gaia_knowledge_section.lstrip("\n"),
                    GAIA_KNOWLEDGE_CAP_CHARS,
                    GAIA_KNOWLEDGE_TRUNC_MARKER,
                )
            )
        if skills_text:
            variable_parts.append(_cap_section(skills_text, SKILLS_CAP_CHARS, SKILLS_TRUNC_MARKER))

        # Tracked-todos summary + run-binding banners — appended LAST in the
        # volatile block so the directives land with recency right before the
        # user's turn. The active-todo banner and background banner only appear
        # on bound / headless runs.
        active_todo_banner = ""
        if user_id:
            tracked_todos_section, active_todo_banner = await asyncio.gather(
                _get_tracked_todos_section(user_id, active_todo_id),
                _build_active_todo_banner(user_id, active_todo_id),
            )
            if tracked_todos_section:
                variable_parts.append(
                    _cap_section(
                        tracked_todos_section.lstrip("\n"),
                        TRACKED_TODOS_CAP_CHARS,
                        TRACKED_TODOS_TRUNC_MARKER,
                    )
                )
        if execution_mode == "background":
            variable_parts.append(BACKGROUND_EXECUTION_BANNER)
        if active_todo_banner:
            variable_parts.append(active_todo_banner)

        stable_content = "\n".join(user_stable_parts)
        # The FIRST variable part is the byte-stable core memory documents
        # (appended above as ``core_memory_section``); EVERYTHING after it
        # churns turn-to-turn (recent activity, per-query recall, GAIA
        # knowledge, skills, todos, banners) and must live in the volatile
        # tail — after the time message — where its churn never shifts the
        # cached prefix. The memory_recall slot keeps ONLY the stable core.
        core_stable_parts: list[str] = []
        volatile_parts: list[str] = []
        for i, part in enumerate(variable_parts):
            (core_stable_parts if i == 0 else volatile_parts).append(part)
        recall_content = "\n\n".join(core_stable_parts)
        volatile_content = "\n\n".join(volatile_parts)
        # Cache note: the volatile tail is rebuilt every turn and every
        # changed byte writes NEW blocks to the provider's bounded prompt
        # cache. It sits after the time message so it can't break the prefix,
        # but its SIZE still costs tokens per request — keep the head (recent
        # activity) and the tail (todos/banners — the directives with recency
        # value) and drop the middle, bounding the request-size footprint.
        if len(volatile_content) > MEMORY_RECALL_MAX_CHARS:
            volatile_content = (
                volatile_content[:MEMORY_RECALL_HEAD_CHARS]
                + "\n…[recall truncated to keep the prompt cache warm]…\n"
                + volatile_content[-MEMORY_RECALL_TAIL_CHARS:]
            )

        log.set(
            dynamic_context={
                "source": source or "web",
                "has_core_memory": bool(core_memory_section),
                "has_memories": bool(memories_section),
                "has_gaia_knowledge": bool(gaia_knowledge_section),
                "has_skills": bool(skills_text),
                "used_pinned_memories": memories_text is not None,
                "has_active_todo": bool(active_todo_id),
                "execution_mode": execution_mode,
                "stable_chars": len(stable_content),
                "memory_recall_chars": len(recall_content),
                "has_memory_recall": bool(recall_content),
            }
        )

        stable_msg = _mark_dynamic_context(SystemMessage(content=stable_content))
        recall_msg = (
            _mark_memory_recall(SystemMessage(content=recall_content)) if recall_content else None
        )
        volatile_msg = (
            _mark_memory_volatile(SystemMessage(content=volatile_content))
            if volatile_content
            else None
        )
        return DynamicContextMessages(
            stable=stable_msg, memory_recall=recall_msg, volatile_tail=volatile_msg
        )

    except Exception as e:
        log.error(
            "Error creating dynamic context messages",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        # Return a byte-stable empty stable message so a persistent failure here
        # doesn't change the prompt prefix every minute and silently invalidate
        # the implicit prompt cache. The clock lives in a HumanMessage built by
        # build_current_time_message, so omitting time here is safe.
        return DynamicContextMessages(
            stable=_mark_dynamic_context(SystemMessage(content="")),
            memory_recall=None,
            volatile_tail=None,
        )


def format_tool_selection_message(
    selected_tool: str, existing_content: str, tool_category: str | None = None
) -> str:
    """Format tool selection message, handling both standalone and combined requests.

    The comms_agent delegates to executor via call_executor. The executor will
    use semantic search to find the right tool/subagent, then execute.
    """
    tool_name = selected_tool.replace("_", " ").title()
    search_hint = f"{selected_tool} {tool_category}" if tool_category else selected_tool

    # If user provided content, append tool instruction to their message
    if existing_content:
        return f"""{existing_content}

**TOOL SELECTION:** The user has specifically selected the '{tool_name}' tool (category: {tool_category or "general"}).

Use call_executor to delegate this task. The executor should:
1. Use `retrieve_tools(query="{search_hint}")` to find the tool or subagent
2. If a subagent is returned (e.g. subagent:{tool_category}), use `handoff(subagent_id="{tool_category}", task="Use {selected_tool} to [user's request]")`
3. If a direct tool is returned, bind it with `retrieve_tools(exact_tool_names=[...])` and execute

Execute immediately without asking for clarification."""

    # Pure tool execution without user message
    return f"""**TOOL EXECUTION REQUEST:** The user has selected the '{tool_name}' tool (category: {tool_category or "general"}).

Use call_executor to delegate this task. The executor should:
1. Use `retrieve_tools(query="{search_hint}")` to find the tool or subagent
2. If a subagent is returned (e.g. subagent:{tool_category}), use `handoff(subagent_id="{tool_category}", task="Use {selected_tool} to execute the user's request")`
3. If a direct tool is returned, bind it with `retrieve_tools(exact_tool_names=[...])` and execute

Execute immediately without asking for clarification."""


async def format_workflow_execution_message(
    selected_workflow: SelectedWorkflowData,
    user_id: str | None = None,
    # Open by construction: schedulers spread arbitrary provider trigger data
    # through this alongside the agent's own keys, so there is no fixed shape.
    trigger_context: dict[str, Any] | None = None,
    existing_content: str = "",
) -> str:
    """Format workflow execution message, handling both manual and automated triggers."""
    # Fetch the latest workflow data from database
    workflow = None
    if user_id:
        try:
            workflow = await WorkflowService.get_workflow(selected_workflow.id, user_id)
        except Exception as e:
            log.error(
                "Failed to fetch workflow",
                id=selected_workflow.id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )

    # Use fresh database data if available, otherwise use passed data
    if workflow and workflow.steps:
        steps_text = "\n".join(
            f"{i}. **{step.title}** (Category: {step.category})\n   Description: {step.description}"
            for i, step in enumerate(workflow.steps, 1)
        )
        workflow_title = workflow.title
        workflow_description = workflow.effective_prompt
    else:
        # Fallback to passed data
        steps_text = "\n".join(
            f"{i}. **{step['title']}** (Category: {step['category']})\n   Description: {step['description']}"
            for i, step in enumerate(selected_workflow.steps, 1)
        )
        workflow_title = selected_workflow.title
        workflow_description = selected_workflow.prompt or selected_workflow.description

    # Build signal matching section from tracked todos
    tracked_todos_ctx = ""
    if trigger_context:
        tracked_todos_ctx = trigger_context.get("tracked_todos_context", "")

    signal_matching_section = ""
    if tracked_todos_ctx:
        signal_matching_section = "\n" + SIGNAL_MATCHING_INSTRUCTIONS.format(
            tracked_todos_context=tracked_todos_ctx
        )

    # Background workflow runs (workflow_id in trigger_context) send an automatic
    # completion notification unless the workflow opted out — tell the agent which
    # mode it's in so it neither double-notifies nor stays silent when the
    # workflow's own instructions ask for an alert. Interactive runs get neither
    # section: no automatic notification exists there.
    notification_section = ""
    if trigger_context and trigger_context.get("workflow_id"):
        notify_on_completion = (
            workflow.notify_on_completion
            if workflow
            else trigger_context.get("workflow_notify_on_completion", True)
        )
        notification_section = (
            WORKFLOW_AUTO_NOTIFY_SECTION if notify_on_completion else WORKFLOW_SILENT_NOTIFY_SECTION
        )

    common_args = {
        "workflow_title": workflow_title,
        "workflow_description": workflow_description,
        "workflow_steps": steps_text,
        "signal_matching_section": signal_matching_section,
        "notification_section": notification_section,
    }

    # Email-triggered workflows get enhanced context
    if trigger_context and trigger_context.get("type") == "gmail":
        email_data = trigger_context.get("email_data", {})
        msg_text = email_data.get("message_text", "")

        return EMAIL_TRIGGERED_WORKFLOW_PROMPT.format(
            email_sender=email_data.get("sender", "Unknown"),
            email_subject=email_data.get("subject", "No Subject"),
            email_content_preview=msg_text[:200] + ("..." if len(msg_text) > 200 else ""),
            trigger_timestamp=trigger_context.get("triggered_at", "Unknown"),
            **common_args,
        )

    # Manual workflow execution
    return WORKFLOW_EXECUTION_PROMPT.format(
        user_message=existing_content or f"Execute workflow: {workflow_title}",
        **common_args,
    )


def format_calendar_event_context(
    selected_calendar_event: SelectedCalendarEventData, existing_content: str = ""
) -> str:
    """Format calendar event context for AI conversation."""
    event = selected_calendar_event

    # Format time
    if event.isAllDay:
        time = f"All day on {event.start.get('date', 'Unknown date')}"
    else:
        time = f"{event.start.get('dateTime', 'Unknown')} to {event.end.get('dateTime', 'Unknown')}"

    # Build context
    context = f"""**CALENDAR EVENT:** {event.summary}
Description: {event.description or "None"}
Time: {time}"""

    if event.calendarTitle:
        context += f"\nCalendar: {event.calendarTitle}"

    return f"{context}\n\n{existing_content}" if existing_content else context


def format_reply_context(reply_to_message: ReplyToMessageData, existing_content: str = "") -> str:
    """Format reply-to-message context for AI conversation.

    This adds context about which message the user is replying to,
    helping the AI understand the conversation thread context.
    """
    role_label = "their own" if reply_to_message.role == "user" else "your"

    context = f"""[The user is responding to {role_label} earlier message: "{reply_to_message.content}"]"""

    return f"{context}\n\n{existing_content}" if existing_content else context


# Must match the prefix the frontend's RevealTodos run-now demo sends.
_RUN_NOW_DEMO_PREFIX = "Execute this todo for me:"


async def get_onboarding_system_prompt_if_applicable(
    user_id: str,
    conversation_id: str,
    latest_user_message: str | None = None,
) -> str | None:
    """Return the onboarding system prompt for onboarding/demo turns, else ``None``."""
    try:
        probe = await conversation_repository.get_onboarding_probe(conversation_id)
        is_tagged_onboarding = bool(probe and probe.is_onboarding_conversation)
        is_run_now_demo = bool(
            latest_user_message and latest_user_message.lstrip().startswith(_RUN_NOW_DEMO_PREFIX)
        )

        if not is_tagged_onboarding and not is_run_now_demo:
            return None

        if is_tagged_onboarding:
            message_count = probe.message_count if probe else 0
            if message_count >= 7:
                await user_repository.set_onboarding_phase(user_id, OnboardingPhase.COMPLETED)
                log.info(
                    "[onboarding_prompt] Auto-completed onboarding for after messages",
                    user_id=user_id,
                    message_count=message_count,
                )
                return None

        user_doc = await user_repository.get(user_id)
        if not user_doc:
            return None

        onboarding = user_doc.onboarding or {}
        phase = onboarding.get("phase", "initial")
        if phase == OnboardingPhase.COMPLETED:
            return None

        name = user_doc.name or "there"
        profession = onboarding.get("preferences", {}).get("profession", "")
        triage_summary = onboarding.get("triage_summary", "")

        onboarding_context = (
            f"Profession: {profession}" if profession else "Profession: not specified"
        )
        if triage_summary:
            onboarding_context += f"\nInbox summary: {triage_summary}"

        return ONBOARDING_FIRST_CONVERSATION_SYSTEM_PROMPT.format(
            name=name,
            onboarding_context=onboarding_context,
        )

    except Exception as e:
        log.warning(
            "[onboarding_prompt] Failed to check onboarding conversation",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        return None


def format_files_list(
    files_data: list[FileData] | None,
    file_ids: list[str] | None = None,
    conversation_id: str | None = None,
    *,
    include_processing_guide: bool = True,
) -> str:
    """Surface uploaded files to an agent with path and summary.

    Each attachment is shown with its on-disk path and a truncated summary (so
    the reader knows what the file is without a tool call). The summary text is
    enriched server-side by the caller; this helper only formats. Pure — no
    DB/FS access.

    ``include_processing_guide`` controls the audience:
    - ``True`` (executor): adds the `full summary` sidecar pointer and the full
      read/bash/scratch/artifacts how-to — the executor holds those tools.
    - ``False`` (comms): a lean block — name, path, summary, and a single line
      telling it to delegate real file work. Comms has no file tools; the
      executor-voice how-to only baits it into over-delegating.
    """
    if not files_data or (file_ids is not None and not file_ids):
        return ""

    files = files_data if file_ids is None else [f for f in files_data if f.fileId in file_ids]
    if not files:
        return ""

    lines: list[str] = []
    any_on_disk = False
    for file in files:
        try:
            on_disk = safe_upload_filename(file.filename)
        except ValueError:
            continue
        if conversation_id:
            path = f"/workspace/sessions/{conversation_id}/user-uploaded/{on_disk}"
        else:
            path = f"./user-uploaded/{on_disk}"
        # Only advertise the path when the file really reached the workspace.
        # The mirror is best-effort (it needs JuiceFS), so on a native API — or
        # any deployment where it failed — this path does not exist, and naming
        # it anyway sends the executor into read/bash attempts that can only
        # fail. `search_uploaded_files` needs no mount and is the honest route.
        on_disk_available = file.sandbox_path is not None
        any_on_disk = any_on_disk or on_disk_available
        # The id is shown because `search_uploaded_files(file_id=...)` needs one;
        # without it an agent scoping to a single file can only guess the
        # filename, which matches nothing.
        if on_disk_available:
            lines.append(f"- {file.filename}  (id: {file.fileId})  →  `{path}`")
        else:
            lines.append(
                f"- {file.filename}  (id: {file.fileId}) — not on disk, use `search_uploaded_files`"
            )
        if file.description:
            summary = file.description.strip()
            if len(summary) > UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS:
                summary = summary[:UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS].rstrip() + "…"
            lines.append(f"    summary: {summary}")
            if conversation_id and include_processing_guide and on_disk_available:
                lines.append(f"    full summary: `{path}.summary.md`")

    if not lines:
        return ""

    file_block = "\n".join(lines)

    if not include_processing_guide:
        return (
            f"\n[Uploaded files]\n{file_block}\n\n"
            "Answer simple questions from these summaries directly; for the full "
            "contents or any work on the files, delegate to the executor.\n"
        )

    if not any_on_disk:
        # Nothing was mirrored into the workspace, so every read/bash instruction
        # below would send the agent at a path that does not exist.
        return (
            f"\n[Uploaded files]\n{file_block}\n\n"
            "These files are not present in the workspace, so read/bash cannot "
            "open them. Use `search_uploaded_files` to retrieve their extracted "
            "content, and answer from what it returns.\n"
        )

    return f"""
[Uploaded files]
{file_block}

How to work with these files:
- What is it? — the `summary` above already says; read the `full summary` file
  for the complete write-up.
- Need the raw content? — read the file at its path with read/bash. Files shown
  without a path are not on disk; use `search_uploaded_files` for those.
- Searching across several uploaded files? — use `search_uploaded_files`.
The files live in `./user-uploaded/` (read-only). To process them: copy into
`./scratch/`, do your work, and write user-visible output into `./artifacts/`
— files written there render as cards in the chat immediately.

See `/workspace/sessions/{conversation_id or "<conv>"}/GUIDE.md` for the
full layout and conventions, and `/workspace/INDEX.md` for the top level.
"""
