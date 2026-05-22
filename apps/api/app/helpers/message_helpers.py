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
    WORKFLOW_EXECUTION_PROMPT,
)
from app.agents.templates.agent_template import (
    EXECUTOR_PROMPT_TEMPLATE,
    get_comms_static_prompt,
)
from app.db.mongodb.collections import conversations_collection, users_collection
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.models.user_models import OnboardingPhase
from app.services.gaia_knowledge_service import gaia_knowledge_service
from app.services.memory_service import memory_service
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
) -> SystemMessage:
    """Build the single dynamic-context system message.

    This message is placed AFTER the static main prompt. It carries the
    per-user, per-turn content: user name, timezone, preferences, memories,
    GAIA knowledge, and installable skills. OpenUI / platform restrictions
    and the clock are NOT here any more:

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


# --- Back-compat shims -----------------------------------------------------
# Kept so existing call sites (subagents, workflows) keep working while they
# migrate to build_dynamic_context_message. New code MUST use the unified
# builder above.


async def get_memory_message(
    user_id: str,
    query: str,
    user_name: str | None = None,
    user_timezone: str | None = None,
    user_preferences: dict | None = None,
) -> SystemMessage:
    """Deprecated: thin wrapper over build_dynamic_context_message."""
    return await build_dynamic_context_message(
        user_id=user_id,
        query=query,
        user_name=user_name,
        user_timezone=user_timezone,
        user_preferences=user_preferences,
    )


def get_platform_context_message(
    source: str | None = None,
) -> SystemMessage | None:
    """Deprecated. Platform restrictions now live in the static per-channel
    comms prompt selected by ``create_system_message(source=...)``. This
    shim is kept only so older call sites don't break during migration;
    new code should pass ``source`` to ``create_system_message``.
    """
    del source
    return None


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

    common_args = {
        "workflow_title": workflow_title,
        "workflow_description": workflow_description,
        "workflow_steps": steps_text,
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


def format_files_list(files_data: list[FileData] | None, file_ids: list[str] | None = None) -> str:
    """Format file information for agent context with usage instructions."""
    if not files_data or (file_ids is not None and not file_ids):
        return "No files uploaded."

    # Filter to specific files if IDs provided, otherwise use all
    files = files_data if file_ids is None else [f for f in files_data if f.fileId in file_ids]
    if not files:
        return "No files uploaded."

    file_list = "\n".join(f"- Name: {file.filename} Id: {file.fileId}" for file in files)

    return f"""
Uploaded Files:
{file_list}

You can use these files in your conversation. If you need to refer to them, use the file IDs provided.
You must use query_files to retrieve file content or metadata.
"""
