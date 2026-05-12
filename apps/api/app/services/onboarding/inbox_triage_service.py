"""Triage inbox emails for onboarding — find what matters and interesting patterns."""

import time
from typing import Optional

from langchain_core.messages import HumanMessage
from shared.py.wide_events import log

from app.agents.prompts.onboarding_prompts import INBOX_TRIAGE_PROMPT
from app.core.lazy_loader import providers
from app.models.onboarding_models import InboxTriage, InboxTriageOutput
from app.services.mail.mail_service import search_messages

_NOISE_SENDERS = (
    "noreply@",
    "no-reply@",
    "mailer-daemon@",
    "notifications@",
    "donotreply@",
)


def _is_noise_email(email: dict) -> bool:
    """Return True if the email is automated noise unlikely to need user action."""
    sender = email.get("sender", "").lower()
    snippet = email.get("snippet", "").lower()[:200]
    return any(sender.startswith(prefix) for prefix in _NOISE_SENDERS) or (
        "unsubscribe" in snippet
    )


async def triage_inbox(
    user_id: str,
    emails: list[dict],
    profession: str = "",
    focus: str = "",
) -> Optional[InboxTriage]:
    """
    Triage a list of emails to surface what's important.

    Args:
        user_id: The user's ID
        emails: List of email dicts with sender, subject, snippet, is_unread
        profession: User's profession for context-aware triaging
        focus: User's current focus for context-aware triaging

    Returns:
        InboxTriage or None if triage fails
    """
    if not emails:
        return InboxTriage(
            total_scanned=0,
            total_unread=0,
            summary="",
            important_emails=[],
            patterns=[],
        )

    t0 = time.monotonic()
    try:
        # Filter noise before prioritizing
        filtered = [e for e in emails if not _is_noise_email(e)]
        unread = [e for e in filtered if e.get("is_unread", False)]
        noise_dropped = len(emails) - len(filtered)

        # Build compact email list for LLM (sender, subject, snippet only)
        # Prioritize unread emails, then fill with recent read emails
        read = [e for e in filtered if not e.get("is_unread", False)]
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
        prompt = INBOX_TRIAGE_PROMPT.format(
            email_list=email_list_text,
            profession=profession or "not specified",
            focus=focus or "not specified",
        )
        t_llm = time.monotonic()
        result: InboxTriageOutput = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )
        llm_duration_s = round(time.monotonic() - t_llm, 2)

        # Fetch true unread count from Gmail (not limited to scan window)
        true_unread = 0
        unread_fetch_outcome = "ok"
        t_unread = time.monotonic()
        try:
            unread_result = await search_messages(
                user_id=user_id,
                query="is:unread in:inbox",
                max_results=500,
            )
            true_unread = len(unread_result.get("messages", []))
        except Exception as unread_err:
            unread_fetch_outcome = "failed"
            log.warning(
                "[inbox_triage] true unread fetch failed",
                user_id=user_id,
                step="triage_unread_fetch",
                error=str(unread_err)[:200],
                error_type=type(unread_err).__name__,
            )
            true_unread = len([e for e in emails if e.get("is_unread", False)])

        triage = InboxTriage(
            total_scanned=len(emails),
            total_unread=true_unread,
            summary=result.summary,
            important_emails=result.important_emails,
            patterns=result.patterns,
        )

        log.info(
            "[inbox_triage] done",
            user_id=user_id,
            step="triage_llm",
            outcome="ok",
            emails_in=len(emails),
            emails_filtered=len(filtered),
            noise_dropped=noise_dropped,
            sampled=len(sampled),
            prompt_chars=len(prompt),
            important_count=len(triage.important_emails),
            patterns_count=len(triage.patterns),
            true_unread=true_unread,
            unread_fetch_outcome=unread_fetch_outcome,
            unread_fetch_duration_s=round(time.monotonic() - t_unread, 2),
            llm_duration_s=llm_duration_s,
            duration_s=round(time.monotonic() - t0, 2),
        )
        return triage

    except Exception as e:
        log.error(
            "[inbox_triage] failed",
            user_id=user_id,
            step="triage_llm",
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
        return None
