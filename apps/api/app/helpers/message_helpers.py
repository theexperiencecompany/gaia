from datetime import UTC, datetime
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.context.slots import TIME_CONTEXT_MARKER
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
from app.constants.chat import UPLOADED_FILE_INLINE_SUMMARY_MAX_CHARS
from app.db.repositories.conversations import conversation_repository
from app.db.repositories.users import user_repository
from app.models.message_models import (
    FileData,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.models.user_models import OnboardingPhase
from app.services.workflow import WorkflowService
from app.utils.timezone import Timezone
from shared.py.wide_events import log


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

    All user, time, and memory context is assembled by ``app.agents.context``
    and delivered in its own messages — never in this static prefix.
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
        additional_kwargs={TIME_CONTEXT_MARKER: True},
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
