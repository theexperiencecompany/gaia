"""Generate GAIA's first message to a new user after onboarding intelligence."""

import time
from typing import Optional

from langchain_core.messages import HumanMessage
from shared.py.wide_events import log

from app.agents.prompts.onboarding_prompts import FIRST_MESSAGE_GENERATION_PROMPT
from app.core.lazy_loader import providers
from app.models.onboarding_models import (
    InboxTriage,
    WritingStyleProfile,
)


async def generate_first_message(
    user_id: str,
    name: str,
    profession: str,
    triage: Optional[InboxTriage],
    created_todos: list[dict],
    created_workflows: list[dict],
    writing_style: Optional[WritingStyleProfile],
    focus: str = "",
) -> str:
    """
    Generate GAIA's first message to a new user.
    Single LLM call with all Phase 1+2 context.
    """
    t0 = time.monotonic()
    try:
        writing_style_summary = (
            writing_style.summary if writing_style else "not yet analyzed"
        )

        important_emails_text = ""
        total_scanned = 0
        total_unread = 0
        patterns_text = ""

        if triage:
            total_scanned = triage.total_scanned
            total_unread = triage.total_unread
            patterns_text = "\n".join(f"- {p}" for p in triage.patterns)
            for e in triage.important_emails[:8]:
                important_emails_text += (
                    f"- {e.sender} | {e.subject} | {e.why_important}\n"
                )

        todos_text = (
            ", ".join(t["title"] for t in created_todos) if created_todos else "none"
        )
        workflows_text = (
            ", ".join(w["title"] for w in created_workflows)
            if created_workflows
            else "none"
        )

        prompt = FIRST_MESSAGE_GENERATION_PROMPT.format(
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
        # Fallback message
        return (
            f"Hey {name}. I've set up your GAIA and created a couple of automations "
            f"based on your profile. What are you most focused on right now?"
        )
