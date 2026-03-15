"""Service to learn user writing style from their sent emails."""

import json
import re
from typing import Optional

from langchain_core.messages import HumanMessage
from shared.py.wide_events import log

from app.core.lazy_loader import providers
from app.models.onboarding_models import WritingStyleProfile
from app.services.mail.mail_service import search_messages


WRITING_STYLE_ANALYSIS_PROMPT = """Analyze these email excerpts written by the same person.
Describe their writing style in a short paragraph (2-4 sentences) that could be used to
instruct an AI to write emails that sound exactly like them.

Focus on:
- Length preference (short and direct vs detailed)
- Formality level (casual, professional, or mixed)
- Greeting and sign-off patterns (if any)
- Tone (warm, direct, formal, humorous, etc.)
- Any distinctive verbal patterns or habits

Then provide 3-5 short direct quotes from the emails that best exemplify their style.
Only include the style-relevant parts — no sensitive content, names, or details.

Emails:
{email_samples}

Respond as JSON:
{{
  "summary": "...",
  "sample_snippets": ["...", "...", "..."]
}}
"""


async def learn_writing_style(
    user_id: str,
) -> Optional[WritingStyleProfile]:
    """
    Fetch last 100 sent emails and analyze writing style.

    Args:
        user_id: The user's ID

    Returns:
        WritingStyleProfile or None if insufficient sent emails
    """
    try:
        result = await search_messages(
            user_id=user_id,
            query="in:sent",
            max_results=100,
        )

        sent_emails = result.get("messages", [])

        if len(sent_emails) < 5:
            log.info(
                f"[writing_style] Insufficient sent emails for user {user_id}: {len(sent_emails)}"
            )
            return None

        # Extract body text, skip very short emails and auto-replies
        samples: list[str] = []
        for email in sent_emails:
            body = email.get("body", email.get("snippet", "")).strip()
            subject = email.get("subject", "")
            if len(body) < 20:
                continue
            if any(
                kw in subject.lower()
                for kw in ["out of office", "auto-reply", "automatic"]
            ):
                continue
            # Truncate long emails to first 300 chars for style analysis
            samples.append(body[:300])
            if len(samples) >= 30:
                break

        if len(samples) < 5:
            return None

        email_samples_text = "\n---\n".join(samples)

        llm = await providers.aget("llm_gemini_flash")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        prompt = WRITING_STYLE_ANALYSIS_PROMPT.format(email_samples=email_samples_text)
        response = await llm.ainvoke([HumanMessage(content=prompt)])

        # Parse JSON from response - strip markdown fences if present
        content = response.content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        result_data = json.loads(content)

        profile = WritingStyleProfile(
            summary=result_data["summary"],
            sample_snippets=result_data.get("sample_snippets", [])[:5],
        )

        log.info(
            f"[writing_style] Learned style for user {user_id}: {profile.summary[:80]}..."
        )
        return profile

    except Exception as e:
        log.error(
            f"[writing_style] Failed to learn writing style for {user_id}: {e}",
            exc_info=True,
        )
        return None
