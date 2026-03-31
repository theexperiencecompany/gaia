"""Triage inbox emails for onboarding — find what matters and interesting patterns."""

from typing import Optional

from langchain_core.messages import HumanMessage
from shared.py.wide_events import log

from app.agents.prompts.onboarding_prompts import INBOX_TRIAGE_PROMPT
from app.core.lazy_loader import providers
from app.models.onboarding_models import InboxTriage, InboxTriageOutput


async def triage_inbox(
    user_id: str,
    emails: list[dict],
) -> Optional[InboxTriage]:
    """
    Triage a list of emails to surface what's important.

    Args:
        user_id: The user's ID
        emails: List of email dicts with sender, subject, snippet, is_unread

    Returns:
        InboxTriage or None if triage fails
    """
    if not emails:
        return InboxTriage(
            total_scanned=0,
            total_unread=0,
            important_emails=[],
            patterns=[],
        )

    try:
        unread = [e for e in emails if e.get("is_unread", False)]

        # Build compact email list for LLM (sender, subject, snippet only)
        # Prioritize unread emails, then fill with recent read emails
        read = [e for e in emails if not e.get("is_unread", False)]
        # Take up to 30 unread + 20 most recent read, capped at 50
        sampled = (unread[:30] + read[:20])[:50]

        email_lines = []
        for e in sampled:
            sender = e.get("sender", "Unknown")
            subject = e.get("subject", "(no subject)")
            snippet = e.get("snippet", "")[:100]
            email_lines.append(f"- {sender} | {subject} | {snippet}")

        email_list_text = "\n".join(email_lines)

        llm = await providers.aget("gemini_llm")
        if llm is None:
            raise RuntimeError("LLM provider not available")

        structured_llm = llm.with_structured_output(InboxTriageOutput)
        prompt = INBOX_TRIAGE_PROMPT.format(email_list=email_list_text)
        result: InboxTriageOutput = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )

        triage = InboxTriage(
            total_scanned=len(emails),
            total_unread=len(unread),
            important_emails=result.important_emails,
            patterns=result.patterns,
        )

        log.info(
            f"[inbox_triage] Triaged {len(emails)} emails for user {user_id}. "
            f"Important: {len(triage.important_emails)}, patterns: {len(triage.patterns)}"
        )
        return triage

    except Exception as e:
        log.error(f"[inbox_triage] Failed to triage for {user_id}: {e}", exc_info=True)
        return None
