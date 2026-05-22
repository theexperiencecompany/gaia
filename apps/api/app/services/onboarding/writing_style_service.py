"""Service to learn and save user writing style."""

import time
from typing import Awaitable, Callable, Optional

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
    WritingStyleExampleBlocks,
    WritingStyleExampleOutput,
    WritingStyleOutput,
    WritingStyleProfile,
)
from app.services.mail.mail_service import search_messages

# Minimum usable sent-email count below which style learning is skipped.
_MIN_SENT_EMAILS = 5
_MAX_SAMPLES = 30


async def learn_writing_style(
    user_id: str,
    profession: str = "",
    on_status: Optional[Callable[[str], Awaitable[None]]] = None,
) -> Optional[WritingStyleProfile]:
    """Fetch the user's recent sent emails and analyze writing style."""
    t0 = time.monotonic()
    try:
        if on_status is not None:
            await on_status("Reading your sent folder")
        result = await search_messages(
            user_id=user_id,
            query="in:sent",
            max_results=50,
        )

        sent_emails = result.get("messages", [])
        sent_count = len(sent_emails)

        if on_status is not None:
            await on_status(
                f"Found {sent_count} sent email{'s' if sent_count != 1 else ''}"
            )

        if sent_count < _MIN_SENT_EMAILS:
            log.info(
                "[writing_style] skipped",
                user_id=user_id,
                outcome="skipped",
                skip_reason="insufficient_sent",
                sent_count=sent_count,
                duration_s=round(time.monotonic() - t0, 2),
            )
            return None

        samples: list[str] = []
        skipped_short = 0
        skipped_autoreply = 0
        for email in sent_emails:
            body = email.get("body", email.get("snippet", "")).strip()
            subject = email.get("subject", "")
            if len(body) < 20:
                skipped_short += 1
                continue
            if any(
                kw in subject.lower()
                for kw in ["out of office", "auto-reply", "automatic"]
            ):
                skipped_autoreply += 1
                continue
            samples.append(body)
            if len(samples) >= _MAX_SAMPLES:
                break

        if len(samples) < _MIN_SENT_EMAILS:
            log.info(
                "[writing_style] skipped",
                user_id=user_id,
                outcome="skipped",
                skip_reason="insufficient_samples",
                sent_count=sent_count,
                samples=len(samples),
                skipped_short=skipped_short,
                skipped_autoreply=skipped_autoreply,
                duration_s=round(time.monotonic() - t0, 2),
            )
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
        if on_status is not None:
            await on_status("Analyzing tone and phrasing")
        t_llm = time.monotonic()
        result_data: WritingStyleOutput = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )

        profile = WritingStyleProfile(
            summary=result_data.summary,
            example=result_data.example,
        )

        log.info(
            "[writing_style] learned",
            user_id=user_id,
            outcome="ok",
            sent_count=sent_count,
            samples=len(samples),
            skipped_short=skipped_short,
            skipped_autoreply=skipped_autoreply,
            summary_chars=len(profile.summary),
            llm_duration_s=round(time.monotonic() - t_llm, 2),
            duration_s=round(time.monotonic() - t0, 2),
        )
        return profile

    except Exception as e:
        log.error(
            "[writing_style] failed",
            user_id=user_id,
            outcome="failed",
            error=str(e)[:200],
            error_type=type(e).__name__,
            duration_s=round(time.monotonic() - t0, 2),
            exc_info=True,
        )
        return None


async def regenerate_example_for_style(
    summary: str,
    profession: str = "",
) -> Optional[WritingStyleExampleBlocks]:
    """Generate a new example email from an edited writing style summary."""
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
        return None


async def save_user_edited_summary(user_id: str, edited_summary: str) -> None:
    """Persist a user-edited writing style summary as the canonical style."""
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"onboarding.writing_style.user_edited_summary": edited_summary}},
    )
    log.info(f"[writing_style] Saved user-edited summary for {user_id}")


async def save_generated_example(
    user_id: str, example: WritingStyleExampleBlocks
) -> None:
    """Persist a regenerated example email to MongoDB as structured blocks."""
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"onboarding.writing_style.example": example.model_dump()}},
    )
    log.info(f"[writing_style] Saved regenerated example for {user_id}")
