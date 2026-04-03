"""Service to learn and save user writing style."""

from typing import Optional

from bson import ObjectId
from langchain_core.messages import HumanMessage
from shared.py.wide_events import log

from app.agents.prompts.onboarding_prompts import WRITING_STYLE_PROMPT
from app.core.lazy_loader import providers
from app.db.mongodb.collections import users_collection
from app.models.onboarding_models import WritingStyleOutput, WritingStyleProfile
from app.services.mail.mail_service import search_messages


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

        llm = await providers.aget("gemini_llm")
        if llm is None:
            raise RuntimeError("LLM provider not available")

        structured_llm = llm.with_structured_output(WritingStyleOutput)
        prompt = WRITING_STYLE_PROMPT.format(email_samples=email_samples_text)
        result_data: WritingStyleOutput = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )

        profile = WritingStyleProfile(
            summary=result_data.summary,
            sample_snippets=result_data.sample_snippets[:5],
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


async def save_user_edited_sample(user_id: str, edited_sample: str) -> None:
    """
    Persist a user-edited writing style sample to MongoDB.
    This becomes the canonical reference used when composing emails on behalf of the user.
    """
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"onboarding.writing_style.user_edited_sample": edited_sample}},
    )
    log.info(f"[writing_style] Saved user-edited sample for {user_id}")
