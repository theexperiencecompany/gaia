"""Service to learn and save user writing style."""

from typing import Optional

from bson import ObjectId
from langchain_core.messages import HumanMessage
from shared.py.wide_events import log

from app.agents.prompts.onboarding_prompts import (
    WRITING_STYLE_EXAMPLE_PROMPT,
    WRITING_STYLE_PROMPT,
)
from app.core.lazy_loader import providers
from app.db.mongodb.collections import users_collection
from app.models.onboarding_models import (
    WritingStyleExampleOutput,
    WritingStyleOutput,
    WritingStyleProfile,
)
from app.services.mail.mail_service import search_messages


async def learn_writing_style(
    user_id: str,
    profession: str = "",
) -> Optional[WritingStyleProfile]:
    """
    Fetch the user's 50 most recent sent emails and analyze writing style.
    No truncation — full email bodies are passed to the LLM so greetings,
    sign-offs, and sentence patterns are all visible.

    Args:
        user_id: The user's ID
        profession: The user's profession (used to generate a relevant example)

    Returns:
        WritingStyleProfile or None if insufficient sent emails
    """
    try:
        result = await search_messages(
            user_id=user_id,
            query="in:sent",
            max_results=50,
        )

        sent_emails = result.get("messages", [])

        if len(sent_emails) < 5:
            log.info(
                f"[writing_style] Insufficient sent emails for user {user_id}: {len(sent_emails)}"
            )
            return None

        # Collect full bodies — skip auto-replies and near-empty emails
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
            samples.append(body)
            if len(samples) >= 30:
                break

        if len(samples) < 5:
            return None

        email_samples_text = "\n---\n".join(samples)

        llm = await providers.aget("gemini_llm")
        if llm is None:
            raise RuntimeError("LLM provider not available")

        structured_llm = llm.with_structured_output(WritingStyleOutput)
        prompt = WRITING_STYLE_PROMPT.format(
            profession=profession or "professional",
            email_samples=email_samples_text,
        )
        result_data: WritingStyleOutput = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )

        profile = WritingStyleProfile(
            summary=result_data.summary,
            example=result_data.example,
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


async def regenerate_example_for_style(
    summary: str,
    profession: str = "",
) -> str:
    """
    Generate a new example email from an edited writing style summary.
    Called after the user edits their style description on the reveal card.

    Args:
        summary: The (possibly edited) writing style description
        profession: The user's profession for scenario relevance

    Returns:
        A new example email string, or empty string on failure
    """
    try:
        llm = await providers.aget("gemini_llm")
        if llm is None:
            raise RuntimeError("LLM provider not available")

        structured_llm = llm.with_structured_output(WritingStyleExampleOutput)
        prompt = WRITING_STYLE_EXAMPLE_PROMPT.format(
            summary=summary,
            profession=profession or "professional",
        )
        result_data: WritingStyleExampleOutput = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )
        return result_data.example

    except Exception as e:
        log.error(
            f"[writing_style] Failed to regenerate example: {e}",
            exc_info=True,
        )
        return ""


async def save_user_edited_summary(user_id: str, edited_summary: str) -> None:
    """
    Persist a user-edited writing style summary to MongoDB.
    This becomes the canonical style used when composing emails on behalf of the user.
    """
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"onboarding.writing_style.user_edited_summary": edited_summary}},
    )
    log.info(f"[writing_style] Saved user-edited summary for {user_id}")


async def save_generated_example(user_id: str, example: str) -> None:
    """Persist a regenerated example email to MongoDB."""
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"onboarding.writing_style.example": example}},
    )
    log.info(f"[writing_style] Saved regenerated example for {user_id}")
