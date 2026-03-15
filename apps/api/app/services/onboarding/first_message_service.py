"""Generate GAIA's first message to a new user after onboarding intelligence."""

from typing import Optional

from langchain_core.messages import HumanMessage
from shared.py.wide_events import log

from app.agents.prompts.onboarding_prompts import FIRST_MESSAGE_GENERATION_PROMPT
from app.core.lazy_loader import providers
from app.models.onboarding_models import (
    CompanyProfile,
    InboxTriage,
    WritingStyleProfile,
)


async def generate_first_message(
    user_id: str,
    name: str,
    profession: str,
    company_profile: Optional[CompanyProfile],
    triage: Optional[InboxTriage],
    created_todos: list[dict],
    created_workflows: list[dict],
    social_profiles: list[dict],
    writing_style: Optional[WritingStyleProfile],
) -> str:
    """
    Generate GAIA's first message to a new user.
    Single LLM call with all Phase 1+2 context.
    """
    try:
        company_description = (
            f"{company_profile.name}: {company_profile.description}"
            if company_profile
            else "not provided"
        )

        writing_style_summary = (
            writing_style.summary if writing_style else "not yet analyzed"
        )

        social_profiles_text = (
            ", ".join(
                f"{p.get('platform', '')}: {p.get('url', '')}"
                for p in social_profiles[:5]
            )
            if social_profiles
            else "none found"
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
            company_description=company_description,
            writing_style_summary=writing_style_summary,
            social_profiles_text=social_profiles_text,
            total_scanned=total_scanned,
            total_unread=total_unread,
            patterns=patterns_text or "no notable patterns",
            important_emails=important_emails_text or "no emails analyzed",
            todos_created=todos_text,
            workflows_created=workflows_text,
        )

        llm = await providers.aget("llm_gemini_flash")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        message = response.content.strip()

        log.info(f"[first_message] Generated for {user_id}: {message[:80]}...")
        return message

    except Exception as e:
        log.error(f"[first_message] Failed for {user_id}: {e}", exc_info=True)
        # Fallback message
        return (
            f"Hey {name}. I've set up your GAIA and created a couple of automations "
            f"based on your profile. What are you most focused on right now?"
        )
