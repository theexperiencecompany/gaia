"""Generate GAIA's first message to a new user after onboarding intelligence."""

import time

from langchain_core.messages import HumanMessage

from app.agents.prompts.onboarding_prompts import (
    FIRST_MESSAGE_GENERATION_PROMPT_GMAIL,
    FIRST_MESSAGE_GENERATION_PROMPT_NO_GMAIL,
)
from app.core.lazy_loader import providers
from app.models.onboarding_models import (
    InboxTriage,
    WritingStyleProfile,
)
from app.services.onboarding.clarify_service import format_clarify_context
from shared.py.wide_events import log


async def generate_first_message(
    user_id: str,
    name: str,
    profession: str,
    triage: InboxTriage | None,
    created_todos: list[dict],
    created_workflows: list[dict],
    writing_style: WritingStyleProfile | None,
    has_gmail: bool,
    focus: str = "",
    executed_todos: list[dict] | None = None,
    clarify_answers: list[dict] | None = None,
) -> str:
    """Generate GAIA's first message to a new user."""
    t0 = time.monotonic()
    try:
        executed_ids = {t["id"] for t in (executed_todos or []) if t.get("id")}
        queued_todos = [t for t in created_todos if t.get("id") not in executed_ids]
        todos_text = ", ".join(t["title"] for t in queued_todos) if queued_todos else "none"
        workflows_text = (
            ", ".join(w["title"] for w in created_workflows) if created_workflows else "none"
        )
        todos_executed_text = (
            ", ".join(t["title"] for t in executed_todos) if executed_todos else "none"
        )

        if has_gmail:
            writing_style_summary = writing_style.summary if writing_style else "not yet analyzed"

            important_emails_text = ""
            total_scanned = 0
            total_unread = 0
            patterns_text = ""

            if triage:
                total_scanned = triage.total_scanned
                total_unread = triage.total_unread
                patterns_text = "\n".join(f"- {p}" for p in triage.patterns)
                for e in triage.important_emails[:8]:
                    important_emails_text += f"- {e.sender} | {e.subject} | {e.why_important}\n"

            prompt = FIRST_MESSAGE_GENERATION_PROMPT_GMAIL.format(
                name=name,
                profession=profession,
                focus=focus or "not stated",
                writing_style_summary=writing_style_summary,
                total_scanned=total_scanned,
                total_unread=total_unread,
                patterns=patterns_text or "no notable patterns",
                important_emails=important_emails_text or "no emails analyzed",
                todos_created=todos_text,
                workflows_created=workflows_text,
                todos_executed=todos_executed_text,
            )
        else:
            clarify_context = format_clarify_context(clarify_answers) or "none shared"
            prompt = FIRST_MESSAGE_GENERATION_PROMPT_NO_GMAIL.format(
                name=name,
                profession=profession,
                focus=focus or "not stated",
                clarify_context=clarify_context,
                todos_created=todos_text,
                workflows_created=workflows_text,
                todos_executed=todos_executed_text,
            )

        llm = await providers.aget("gemini_llm")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        t_llm = time.monotonic()
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        llm_duration_s = round(time.monotonic() - t_llm, 2)
        content = response.content
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        message = content.strip()

        log.info(
            "[first_message] generated",
            user_id=user_id,
            step="first_message",
            outcome="ok",
            message_chars=len(message),
            prompt_chars=len(prompt),
            has_triage=triage is not None,
            has_writing_style=writing_style is not None,
            todos_count=len(created_todos),
            workflows_count=len(created_workflows),
            llm_duration_s=llm_duration_s,
            duration_s=round(time.monotonic() - t0, 2),
        )
        return message

    except Exception as e:
        log.error(
            "[first_message] failed",
            user_id=user_id,
            step="first_message",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
        return (
            f"Hey {name}, ok, you're all set up.<NEW_MESSAGE_BREAK>"
            "Lined up a few action items and set up some automations from what I found."
            "<NEW_MESSAGE_BREAK>Oh, and I made you something."
        )
