"""Triage inbox emails for onboarding — find what matters and interesting patterns."""

import time

from langchain_core.messages import HumanMessage

from app.agents.prompts.onboarding_prompts import INBOX_TRIAGE_PROMPT
from app.core.lazy_loader import providers
from app.models.onboarding_models import InboxTriage, InboxTriageOutput
from shared.py.wide_events import log

_NOISE_SENDERS = (
    "noreply@",
    "no-reply@",
    "mailer-daemon@",
    "notifications@",
    "donotreply@",
)

_MEANINGFUL_LABELS = {
    "IMPORTANT",
    "STARRED",
    "CATEGORY_PERSONAL",
    "CATEGORY_SOCIAL",
    "CATEGORY_PROMOTIONS",
    "CATEGORY_UPDATES",
    "CATEGORY_FORUMS",
}


def _is_noise_email(email: dict) -> bool:
    sender = email.get("sender", "").lower()
    snippet = email.get("snippet", "").lower()[:200]
    return any(sender.startswith(prefix) for prefix in _NOISE_SENDERS) or ("unsubscribe" in snippet)


def _format_labels(email: dict) -> str:
    labels = email.get("labelIds") or email.get("label_ids") or []
    kept = [lbl for lbl in labels if lbl in _MEANINGFUL_LABELS]
    if not kept:
        return ""
    pretty = [lbl.replace("CATEGORY_", "").lower() for lbl in kept]
    return f"[{', '.join(pretty)}] "


async def triage_inbox(
    user_id: str,
    emails: list[dict],
    profession: str = "",
    focus: str = "",
) -> InboxTriage | None:
    """Triage a list of emails to surface what's important."""
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
        filtered = [e for e in emails if not _is_noise_email(e)]
        unread = [e for e in filtered if e.get("is_unread", False)]
        read = [e for e in filtered if not e.get("is_unread", False)]
        noise_dropped = len(emails) - len(filtered)
        sampled = (unread[:60] + read[:40])[:100]

        email_lines = []
        for e in sampled:
            sender = e.get("sender", "Unknown")
            subject = e.get("subject", "(no subject)")
            snippet = e.get("snippet", "")
            labels = _format_labels(e)
            email_lines.append(f"- {labels}{sender} | {subject} | {snippet}")

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
        result: InboxTriageOutput = await structured_llm.ainvoke([HumanMessage(content=prompt)])
        llm_duration_s = round(time.monotonic() - t_llm, 2)

        total_unread = len(unread)

        triage = InboxTriage(
            total_scanned=len(emails),
            total_unread=total_unread,
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
            total_unread=total_unread,
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
