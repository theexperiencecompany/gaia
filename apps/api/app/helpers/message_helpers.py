import asyncio
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from bson import ObjectId
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
from app.agents.workspace.paths import safe_upload_filename
from app.config.oauth_config import get_integration_by_id
from app.db.mongodb.collections import (
    conversations_collection,
    todos_collection,
    users_collection,
)
from app.db.redis import get_cache, set_cache
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.models.user_models import OnboardingPhase
from app.services.gaia_knowledge_service import gaia_knowledge_service
from app.services.integrations.user_integrations import get_user_connected_integrations
from app.services.memory_service import memory_service
from app.services.tracked_todo_service import tracked_todo_service
from app.services.workflow import WorkflowService
from app.utils.user_preferences_utils import (
    format_user_preferences_for_agent,
)
from shared.py.wide_events import log

# Sentinel marker on dynamic-context SystemMessages so
# manage_system_prompts_node can keep only the latest one.
DYNAMIC_CONTEXT_MARKER = "dynamic_context"


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
    message produced by ``build_dynamic_context_message`` and does NOT live
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
            local_now = datetime.now(ZoneInfo(user_timezone)).strftime("%A, %B %d, %Y, %H:%M")
            parts.append(f"[User Local Time ({user_timezone}): {local_now}]")
        except Exception as e:
            log.warning(f"Error formatting user local time: {e}")
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
        results = await memory_service.search_memories(query=query, user_id=user_id, limit=5)
        if results and (memories := getattr(results, "memories", None)):
            log.info(f"Added {len(memories)} memories to context")
            return "\n\nBased on our previous conversations:\n" + "\n".join(
                f"- {mem.content}" for mem in memories
            )
    except Exception as e:
        log.warning(f"Error retrieving memories: {e}")

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
            log.info(f"Added {len(results)} knowledge items to context")
            return "\n\nAbout Gaia (your identity and capabilities):\n" + "\n".join(
                f"- {result.content}" for result in results
            )
    except Exception as e:
        log.warning(f"Error retrieving GAIA knowledge: {e}")

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


def _format_active_todo_banner(todo: dict) -> str:
    vfs_path = todo.get("vfs_path") or "(no vfs)"
    title = todo.get("title", "Untitled")
    todo_id = str(todo.get("_id") or todo.get("id") or "")
    return (
        "🎯 ACTIVE TODO (this run is bound to this todo)\n"
        f"   id: {todo_id}\n"
        f"   title: {title}\n"
        f"   canvas: {vfs_path}/canvas.md\n"
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
        doc = await todos_collection.find_one({"_id": ObjectId(active_todo_id), "user_id": user_id})
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


async def _get_connected_integrations_manifest(user_id: str) -> str:
    """One line per connected integration so the agent knows what it can reach.

    Capability awareness only — the agent learns Slack/Linear/GitHub/etc. are
    available without first running tool retrieval. Detailed tool schemas still
    come from ``retrieve_tools`` at inference time. Names resolve from the
    in-memory OAuth config (no extra DB calls); unknown ids fall back to the id.
    """
    try:
        docs = await get_user_connected_integrations(user_id)
    except Exception as e:
        log.warning(f"Error building connected-integrations manifest: {e}")
        return ""
    connected = sorted(
        str(d["integration_id"])
        for d in docs
        if d.get("status") == "connected" and d.get("integration_id")
    )
    if not connected:
        return ""
    lines = ["Connected integrations (hand off to the matching subagent to use them):"]
    for iid in connected:
        integration = get_integration_by_id(iid)
        lines.append(f"- {integration.name} ({iid})" if integration else f"- {iid}")
    return "\n".join(lines)


async def build_dynamic_context_message(
    user_id: str | None,
    query: str | None,
    user_name: str | None = None,
    user_timezone: str | None = None,
    user_preferences: dict | None = None,
    writing_style: dict | None = None,
    source: str | None = None,
    include_openui: bool = False,
    memories_text: str | None = None,
    skills_text: str | None = None,
    active_todo_id: str | None = None,
    execution_mode: Literal["interactive", "background"] = "interactive",
) -> SystemMessage:
    """Build the single dynamic-context system message.

    This message is placed AFTER the static main prompt. It carries the
    per-user, per-turn content: user name, timezone, preferences, memories,
    GAIA knowledge, installable skills, the tracked-todos summary, and — on
    bound / headless runs — the run-binding banners. OpenUI / platform
    restrictions and the clock are NOT here any more:

    - Output-format addendums (OpenUI or text-only) are part of the static
      per-channel prompt so they cache across every user on that channel.
    - Current time lives in a HumanMessage so minute ticks never invalidate
      the ``system_instruction`` prefix.

    Within this message, content is ordered so the byte-identical-across-
    turns sections come first (user name → timezone → preferences), then
    the per-turn fetches (memories, GAIA knowledge, skills). The provider
    caches bytes 0..N where byte N is the first to differ between turns —
    so stable content up front maximises the cache hit length.

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
            active-todo banner (canvas write-target directive) LAST, so the
            cached stable prefix is untouched and the directive gets recency.
        execution_mode: When "background" (headless scheduled run), appends the
            background-execution banner so the agent stays terse and action-only.

    Returns:
        A SystemMessage marked with ``dynamic_context=True`` in
        ``additional_kwargs``.
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
        # Connected-integrations manifest sits with the stable prefix: it only
        # changes when the user connects/disconnects an integration, not per turn.
        if user_id:
            if manifest := await _get_connected_integrations_manifest(user_id):
                user_stable_parts.append(manifest)

        # --- Fetches (may change turn-to-turn) -----------------------------
        if memories_text is not None:
            memories_section = memories_text
            gaia_knowledge_section = ""
            if user_id and query:
                gaia_knowledge_section = await _get_gaia_knowledge_section(query)
        elif user_id and query:
            memories_section, gaia_knowledge_section = await asyncio.gather(
                _get_user_memories_section(query, user_id),
                _get_gaia_knowledge_section(query),
            )
        else:
            memories_section = ""
            gaia_knowledge_section = ""

        if memories_section:
            variable_parts.append(memories_section.lstrip("\n"))
        if gaia_knowledge_section:
            variable_parts.append(gaia_knowledge_section.lstrip("\n"))
        if skills_text:
            variable_parts.append(skills_text)

        # Tracked-todos summary + run-binding banners — appended LAST so the
        # cached stable prefix above is never disturbed, and so these directives
        # land with recency right before the user's turn. The active-todo banner
        # and background banner only appear on bound / headless runs.
        active_todo_banner = ""
        if user_id:
            tracked_todos_section, active_todo_banner = await asyncio.gather(
                _get_tracked_todos_section(user_id, active_todo_id),
                _build_active_todo_banner(user_id, active_todo_id),
            )
            if tracked_todos_section:
                variable_parts.append(tracked_todos_section.lstrip("\n"))
        if execution_mode == "background":
            variable_parts.append(BACKGROUND_EXECUTION_BANNER)
        if active_todo_banner:
            variable_parts.append(active_todo_banner)

        content_sections = [
            "\n".join(user_stable_parts),
            "\n\n".join(variable_parts),
        ]
        content = "\n\n".join(s for s in content_sections if s)

        log.set(
            dynamic_context={
                "source": source or "web",
                "has_memories": bool(memories_section),
                "has_gaia_knowledge": bool(gaia_knowledge_section),
                "has_skills": bool(skills_text),
                "used_pinned_memories": memories_text is not None,
                "has_active_todo": bool(active_todo_id),
                "execution_mode": execution_mode,
                "char_count": len(content),
                "user_stable_chars": sum(len(p) for p in user_stable_parts),
                "variable_chars": sum(len(p) for p in variable_parts),
            }
        )

        return _mark_dynamic_context(SystemMessage(content=content))

    except Exception as e:
        log.error(f"Error creating dynamic context message: {e}")
        # Return a byte-stable empty message so a persistent failure here
        # doesn't change the prompt prefix every minute and silently
        # invalidate the implicit prompt cache. The clock lives in a
        # HumanMessage built by build_current_time_message, so omitting
        # time here is safe.
        return _mark_dynamic_context(SystemMessage(content=""))


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
    trigger_context: dict | None = None,
    existing_content: str = "",
) -> str:
    """Format workflow execution message, handling both manual and automated triggers."""
    # Fetch the latest workflow data from database
    workflow = None
    if user_id:
        try:
            workflow = await WorkflowService.get_workflow(selected_workflow.id, user_id)
        except Exception as e:
            log.error(f"Failed to fetch workflow {selected_workflow.id}: {e}")

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
        conv = await conversations_collection.find_one(
            {"conversation_id": conversation_id},
            {"is_onboarding_conversation": 1, "messages": 1},
        )
        is_tagged_onboarding = bool(conv and conv.get("is_onboarding_conversation"))
        is_run_now_demo = bool(
            latest_user_message and latest_user_message.lstrip().startswith(_RUN_NOW_DEMO_PREFIX)
        )

        if not is_tagged_onboarding and not is_run_now_demo:
            return None

        if is_tagged_onboarding:
            message_count = len(conv.get("messages", [])) if conv else 0
            if message_count >= 7:
                await users_collection.update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": {"onboarding.phase": OnboardingPhase.COMPLETED}},
                )
                log.info(
                    f"[onboarding_prompt] Auto-completed onboarding for {user_id} after {message_count} messages"
                )
                return None

        user_doc = await users_collection.find_one(
            {"_id": ObjectId(user_id)},
            {"onboarding.phase": 1, "name": 1, "onboarding.preferences": 1},
        )
        if not user_doc:
            return None

        phase = user_doc.get("onboarding", {}).get("phase", "initial")
        if phase == OnboardingPhase.COMPLETED:
            return None

        name = user_doc.get("name", "there")
        onboarding = user_doc.get("onboarding", {})
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
        log.warning(f"[onboarding_prompt] Failed to check onboarding conversation: {e}")
        return None


def format_files_list(
    files_data: list[FileData] | None,
    file_ids: list[str] | None = None,
    conversation_id: str | None = None,
) -> str:
    """Surface uploaded files to the agent as concrete FS paths.

    The agent reads/writes files via bash/read/write/edit; the upload
    pipeline mirrors every attachment into the session's read-only
    `user-uploaded/` dir. Tell the agent the on-disk path explicitly and
    point at the session GUIDE for the action conventions — no
    `query_files` tool indirection, no path guessing.
    """
    if not files_data or (file_ids is not None and not file_ids):
        return ""

    files = files_data if file_ids is None else [f for f in files_data if f.fileId in file_ids]
    if not files:
        return ""

    lines: list[str] = []
    for file in files:
        try:
            on_disk = safe_upload_filename(file.filename)
        except ValueError:
            continue
        if conversation_id:
            path = f"/workspace/sessions/{conversation_id}/user-uploaded/{on_disk}"
        else:
            path = f"./user-uploaded/{on_disk}"
        lines.append(f"- {file.filename}  →  `{path}`")

    if not lines:
        return ""

    file_block = "\n".join(lines)
    return f"""
[Attached files for this turn]
{file_block}

These files are on the conversation filesystem in `./user-uploaded/`
(read-only). To process them: copy into `./scratch/`, do your work,
and write any user-visible output into `./artifacts/` — files written
there render as cards in the chat immediately.

See `/workspace/sessions/{conversation_id or "<conv>"}/GUIDE.md` for the
full layout and conventions, and `/workspace/INDEX.md` for the top level.
"""
