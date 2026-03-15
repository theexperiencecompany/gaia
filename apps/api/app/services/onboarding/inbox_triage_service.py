"""Triage inbox emails for onboarding — find what matters and interesting patterns."""

import json
import re
from typing import Optional

from langchain_core.messages import HumanMessage
from shared.py.wide_events import log

from app.core.lazy_loader import providers
from app.models.onboarding_models import EmailSummary, InboxTriage


TRIAGE_PROMPT = """You are analyzing a user's inbox to surface what's most important.

Here are their recent emails (sender, subject, snippet):
{email_list}

Your job:
1. Identify the 5-10 most important emails that need attention or represent significant work
2. For each, explain in one short sentence why it matters (e.g. "investor follow-up", "deadline Thursday", "team needs decision")
3. Identify 2-5 interesting patterns across the full inbox (e.g. "Multiple emails from investor-type senders", "Recurring project X thread", "3 emails about upcoming deadline next week")

Respond as JSON:
{{
  "important_emails": [
    {{
      "sender": "...",
      "subject": "...",
      "snippet": "...",
      "why_important": "..."
    }}
  ],
  "patterns": ["...", "..."]
}}
"""


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
        email_lines = []
        for e in emails[:200]:  # Cap at 200 for prompt size
            sender = e.get("sender", "Unknown")
            subject = e.get("subject", "(no subject)")
            snippet = e.get("snippet", "")[:100]
            email_lines.append(f"- {sender} | {subject} | {snippet}")

        email_list_text = "\n".join(email_lines)

        llm = await providers.aget("llm_gemini_flash")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        prompt = TRIAGE_PROMPT.format(email_list=email_list_text)
        response = await llm.ainvoke([HumanMessage(content=prompt)])

        # Parse JSON from response - strip markdown fences if present
        content = response.content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        result_data = json.loads(content)

        important = [
            EmailSummary(
                sender=e["sender"],
                subject=e["subject"],
                snippet=e.get("snippet", ""),
                why_important=e["why_important"],
            )
            for e in result_data.get("important_emails", [])
        ]

        triage = InboxTriage(
            total_scanned=len(emails),
            total_unread=len(unread),
            important_emails=important,
            patterns=result_data.get("patterns", []),
        )

        log.info(
            f"[inbox_triage] Triaged {len(emails)} emails for user {user_id}. "
            f"Important: {len(important)}, patterns: {len(triage.patterns)}"
        )
        return triage

    except Exception as e:
        log.error(f"[inbox_triage] Failed to triage for {user_id}: {e}", exc_info=True)
        return None
