"""Helper functions for email processing."""

from dataclasses import dataclass
import time
import unicodedata

import html2text
from pydantic import BaseModel, ConfigDict

from app.agents.memory.profile_extractor import PLATFORM_CONFIG
from app.agents.prompts.email_filter_prompts import EMAIL_MEMORY_EXTRACTION_PROMPT
from app.constants.email import NO_SUBJECT, UNKNOWN_SENDER
from app.constants.memory import MemorySourceType
from app.db.repositories.users import user_repository
from app.memory.engine import memory_engine
from app.models.mail_models import GmailMessageSummary
from shared.py.wide_events import log


class _PlatformSenderDomains(BaseModel):
    """The one ``PlatformConfig`` key this module reads (ideal home: profile_extractor)."""

    model_config = ConfigDict(extra="ignore")

    sender_domains: list[str]


_PLATFORM_SENDER_DOMAINS: tuple[str, ...] = tuple(
    domain
    for platform_config in PLATFORM_CONFIG.values()
    for domain in _PlatformSenderDomains.model_validate(platform_config).sender_domains
)

# HTML to text converter
_html_converter = html2text.HTML2Text()
_html_converter.ignore_links = True
_html_converter.body_width = 0
_html_converter.ignore_images = True
_html_converter.skip_internal_links = True


def _build_user_context(user_name: str | None, user_email: str | None) -> str:
    """Build a user context string for memory extraction."""
    if not user_name:
        return ""

    context = f"The user's name is {user_name}."
    if user_email:
        context += f" Their email is {user_email}."

    return context


def remove_invisible_chars(s: str) -> str:
    """Remove invisible Unicode characters."""
    return "".join(c for c in s if unicodedata.category(c) not in ("Cf", "Cc"))


@dataclass(slots=True, frozen=True)
class ProcessedEmail:
    """One email's clean text plus the metadata its memory entry cites."""

    content: str
    message_id: str
    sender: str
    subject: str


def process_email_content(emails: list[GmailMessageSummary]) -> tuple[list[ProcessedEmail], int]:
    """Convert HTML email content to clean text, skipping platform emails (profile-discovery only)."""
    processed: list[ProcessedEmail] = []
    failed_count = 0

    for email_data in emails:
        try:
            # Skip platform emails - only used for profile discovery
            sender = email_data.sender.lower()

            # Check against all platform sender domains from config
            if any(domain in sender for domain in _PLATFORM_SENDER_DOMAINS):
                continue

            message_text = email_data.body
            if not message_text.strip():
                failed_count += 1
                continue

            # Convert HTML to clean text
            clean_text = _html_converter.handle(message_text).strip()
            clean_text = remove_invisible_chars(clean_text)

            if not clean_text:
                failed_count += 1
                continue

            processed.append(
                ProcessedEmail(
                    content=clean_text,
                    message_id=email_data.id,
                    sender=email_data.sender or UNKNOWN_SENDER,
                    subject=email_data.subject or NO_SUBJECT,
                )
            )
        except Exception:
            failed_count += 1

    return processed, failed_count


async def store_emails_to_memory(
    user_id: str,
    processed_emails: list[ProcessedEmail],
    user_name: str | None = None,
    user_email: str | None = None,
) -> None:
    """Ingest an email batch into the memory engine."""
    if not processed_emails:
        return

    try:
        messages = [
            {
                "role": "user",
                "content": f"""The user RECEIVED this email (not sent by the user).

From: {email_data.sender}
Subject: {email_data.subject}

{email_data.content}""",
            }
            for email_data in processed_emails
            if email_data.content.strip()
        ]

        if not messages:
            return

        user_context = _build_user_context(user_name, user_email)

        t0_store = time.monotonic()
        result = await memory_engine.retain(
            user_id,
            messages,
            source_type=MemorySourceType.EMAIL,
            extraction_hints=f"{user_context}\n\n{EMAIL_MEMORY_EXTRACTION_PROMPT}",
            user_name=user_name,
        )
        store_elapsed = time.monotonic() - t0_store

        log.info(
            "[timing] Memory retain ( emails): s — facts extracted",
            messages_count=len(messages),
            store_elapsed=store_elapsed,
            facts_extracted=result.facts_extracted,
        )

    except Exception as e:
        log.error(
            "Error storing email batch to memory",
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        # Don't re-raise - we want to continue processing other batches


async def mark_email_processing_complete(user_id: str, memory_count: int) -> None:
    """Mark the user's email processing as complete in the database."""
    await user_repository.mark_email_processing_complete(user_id, memory_count)


async def store_single_profile(
    user_id: str,
    platform: str,
    profile_url: str,
    content: str,
    user_name: str | None = None,
) -> None:
    """Store a single social profile to memory."""
    try:
        memory_content = f"User's {platform} profile: {profile_url} {content}"

        await memory_engine.retain(
            user_id,
            [{"role": "user", "content": memory_content}],
            source_type=MemorySourceType.EMAIL,
            source_id=profile_url,
            extraction_hints=(
                f"This is the user's own {platform} profile, discovered during email "
                "onboarding. Extract durable facts about the user: their handle, bio, "
                "role, projects, interests, and location."
            ),
            user_name=user_name,
        )
        log.info("Stored profile to memory", platform=platform, profile_url=profile_url)
    except Exception as e:
        log.error(
            "Failed to store profile",
            platform=platform,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
