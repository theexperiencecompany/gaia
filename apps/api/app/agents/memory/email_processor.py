"""Process Gmail emails and extract user profiles for memory storage.

Flow:
1. Two independent parallel tracks start simultaneously:

   TRACK A - Email Scanning & Storage:
   - Fetch recent emails from Gmail API (in:inbox, up to 200 emails in batches of 100)
   - Clean email content: HTML → plain text, remove invisible chars
   - Queue emails for memory storage (background ARQ job)

   TRACK B - Profile Extraction (NEW APPROACH):
   - Parallel Gmail API searches for each platform domain (medium.com, twitter.com, etc.)
   - Extract usernames from platform emails using LLM in parallel
   - Validate usernames against platform-specific patterns
   - Build and crawl profile URLs in parallel
   - Store all profile content as memories in single batch

2. Wait for both tracks to complete
3. Mark user as processed to prevent re-processing

Key improvements:
- Profile extraction now uses targeted Gmail searches instead of filtering accumulated emails
- All platform searches happen in parallel for faster processing
- Profile filtering is completely independent of email scanning
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
import time
from typing import Any, TypedDict, cast

from app.agents.memory.profile_crawler import crawl_profile_url
from app.agents.memory.profile_extractor import (
    PLATFORM_CONFIG,
    build_profile_url,
    extract_username_with_llm,
    validate_username,
)
from app.constants.email import (
    BATCH_SIZE,
    EMAIL_QUERY,
    INBOX_OR_SENT_EMAIL_QUERY,
    MAX_RESULTS,
    ONBOARDING_EMAIL_SCAN_LIMIT,
)
from app.constants.log_tags import LogTag
from app.constants.memory import MemorySourceType
from app.db.repositories.users import user_repository
from app.helpers.email_helpers import (
    mark_email_processing_complete,
    process_email_content,
    store_emails_to_memory,
    store_single_profile,
)
from app.memory.engine import memory_engine
from app.models.user_models import UserDocument
from app.services.mail.mail_service import MessageFetchOptions, search_messages
from shared.py.wide_events import log


class ExtractedProfile(TypedDict):
    """One social profile the extraction track resolved and stored."""

    platform: str
    url: str


class PlatformProcessResult(TypedDict, total=False):
    """Outcome of processing one platform.

    ``total=False`` because the two outcomes are disjoint: success carries
    ``platform``/``url``/``discovery_task``, every skip carries only ``error``.
    """

    success: bool
    platform: str
    url: str
    #: Follow-up crawl of profiles linked from this one; resolves to the count stored.
    discovery_task: asyncio.Task[int]
    error: str


class ProfileExtractionResult(TypedDict, total=False):
    """Stats from the parallel profile-extraction track (TRACK B)."""

    profiles_stored: int
    extracted_profiles: list[ExtractedProfile]


class GmailProcessingStats(TypedDict, total=False):
    """Stats returned by :func:`process_gmail_to_memory`.

    ``total=False`` because the already-processed short-circuit returns only
    ``already_processed``/``processing_complete`` and the zeroed counters.
    """

    total: int
    successful: int
    failed: int
    profiles_stored: int
    processing_complete: bool
    already_processed: bool
    extracted_profiles: list[ExtractedProfile]


@dataclass
class _StepTimer:
    """Accumulates labeled step timings for a structured summary log."""

    _steps: list[tuple[str, float]] = field(default_factory=list)
    _start: float = field(default_factory=time.monotonic)

    def record(self, label: str, elapsed: float) -> None:
        self._steps.append((label, elapsed))

    def summary(self) -> str:
        total = time.monotonic() - self._start
        col = 52
        lines = [
            "",
            "=" * (col + 12),
            f"  {'ONBOARDING EMAIL PIPELINE — TIMING BREAKDOWN':<{col}}",
            "=" * (col + 12),
        ]
        for label, elapsed in self._steps:
            bar = "█" * min(int(elapsed / 2), 20)
            lines.append(f"  {label:<{col}} {elapsed:>6.1f}s  {bar}")
        lines += [
            "-" * (col + 12),
            f"  {'TOTAL':<{col}} {total:>6.1f}s",
            "=" * (col + 12),
            "",
        ]
        return "\n".join(lines)


async def _search_platform_emails_parallel(user_id: str) -> dict[str, list[dict[str, Any]]]:
    """
    Search Gmail API in parallel for emails from all platform domains.

    This is a separate track from the main email scanning - it specifically
    searches for emails from platform domains (medium.com, twitter.com, etc.)
    to extract profile information.

    Args:
        user_id: User ID to search emails for

    Returns:
        Dict mapping platform names to their email lists
    """
    search_start = time.time()

    # Create parallel search tasks for each platform
    search_tasks = []
    for platform, config in PLATFORM_CONFIG.items():
        # Build search query for this platform's domains
        # e.g., "from:twitter.com OR from:x.com OR from:notify.twitter.com"
        domain_queries = [f"from:{domain}" for domain in config["sender_domains"]]
        query = " OR ".join(domain_queries)

        # Create async task to search for this platform's emails
        task = _search_platform_emails(user_id, platform, query)
        search_tasks.append((platform, task))

    # Execute all searches in parallel
    results = await asyncio.gather(*[task for _, task in search_tasks], return_exceptions=True)

    # Build platform -> emails mapping
    platform_emails: dict[str, list[dict[str, Any]]] = {}
    for (platform, _), result in zip(search_tasks, results):
        if isinstance(result, Exception):
            log.error(
                f"{LogTag.MEMORY} Platform email search failed",
                platform=platform,
                error_type=type(result).__name__,
                error=str(result),
                user_id=user_id,
            )
            platform_emails[platform] = []
        elif isinstance(result, list):
            platform_emails[platform] = result
        else:
            platform_emails[platform] = []

    elapsed = time.time() - search_start
    total_found = sum(len(emails) for emails in platform_emails.values())
    log.info(
        f"{LogTag.MEMORY} Parallel Gmail searches completed",
        duration_s=round(elapsed, 2),
        email_count=total_found,
        platform_count=len(platform_emails),
        user_id=user_id,
    )

    return platform_emails


async def _search_platform_emails(
    user_id: str, platform: str, query: str, max_results: int = 10
) -> list[dict[str, Any]]:
    """
    Search Gmail for emails from a specific platform.

    Args:
        user_id: User ID
        platform: Platform name (for logging)
        query: Gmail search query (e.g., "from:twitter.com OR from:x.com")
        max_results: Maximum emails to retrieve

    Returns:
        List of email data from this platform
    """
    try:
        result = await search_messages(
            user_id=user_id,
            query=query,
            max_results=max_results,
        )

        return result.messages

    except Exception as e:
        log.error(
            f"{LogTag.MEMORY} Error searching platform emails",
            platform=platform,
            error_type=type(e).__name__,
            error=str(e),
            user_id=user_id,
        )
        return []


def _extract_display_name(raw_from: str) -> str:
    if not raw_from:
        return ""
    name = raw_from.split("<", 1)[0].strip().strip('"')
    if not name:
        return raw_from.split("@", 1)[0].strip("<>") or raw_from
    return name[:30]


@dataclass
class OnboardingFetchOptions:
    """Shape knobs for the onboarding email scan."""

    fmt: str = "metadata"
    include_sent: bool = False


async def fetch_emails_for_onboarding(
    user_id: str,
    months: int = 1,
    max_total: int = ONBOARDING_EMAIL_SCAN_LIMIT,
    on_batch: Callable[[int, str | None], Awaitable[None]] | None = None,
    into: list[dict[str, Any]] | None = None,
    options: OnboardingFetchOptions | None = None,
) -> list[dict[str, Any]]:
    """Fetch the last `months` months of emails for onboarding.

    Uses Gmail metadata format by default (no body) so batches can be 100 wide.
    Callers that need bodies (social profile regex) pass
    options=OnboardingFetchOptions(fmt="full").
    `include_sent` widens the scan to the sent mailbox as well, which is what
    makes each message's SENT label — and any ownership signal derived from it —
    observable at all. Inbox triage leaves it off so the user's own outgoing
    mail is not scored as something needing their attention.
    on_batch receives (running_count, latest_sender_display_name_or_None).
    If `into` is provided, batches are appended to it live so concurrent
    consumers can observe partial progress.
    """
    opts = options or OnboardingFetchOptions()
    scope = INBOX_OR_SENT_EMAIL_QUERY if opts.include_sent else EMAIL_QUERY
    query = f"{scope} newer_than:{months * 30}d"
    all_emails: list[dict[str, Any]] = into if into is not None else []
    page_token: str | None = None
    metadata_mode = opts.fmt == "metadata"

    try:
        while len(all_emails) < max_total:
            remaining = min(BATCH_SIZE, max_total - len(all_emails))
            result = await search_messages(
                user_id=user_id,
                query=query,
                max_results=remaining,
                page_token=page_token,
                options=MessageFetchOptions(
                    output_format=opts.fmt,
                    include_payload=not metadata_mode,
                    verbose=not metadata_mode,
                ),
            )
            batch = result.messages
            if not batch:
                break
            all_emails.extend(batch)
            if on_batch is not None:
                latest_sender = _extract_display_name(
                    batch[-1].get("from") or batch[-1].get("sender") or ""
                )
                await on_batch(len(all_emails), latest_sender or None)
            page_token = result.next_page_token
            if not page_token:
                break
    except Exception as e:
        log.error(
            f"{LogTag.MEMORY} fetch_emails_for_onboarding failed",
            user_id=user_id,
            fetched_count=len(all_emails),
            error_type=type(e).__name__,
            error=str(e),
            exc_info=True,
        )
        raise

    log.info(
        f"{LogTag.MEMORY} fetch_emails_for_onboarding finished",
        email_count=len(all_emails),
        user_id=user_id,
        fmt=opts.fmt,
    )
    return all_emails


def _latest_gmail_scan_timestamp(user: UserDocument | None) -> datetime | None:
    """Pull the previous Gmail scan timestamp out of a user's integration scan states."""
    if not user:
        return None
    scan_states = user.integration_scan_states or {}
    if isinstance(scan_states, dict):
        gmail_state = scan_states.get("gmail", {})
        if isinstance(gmail_state, dict):
            return cast(datetime | None, gmail_state.get("last_scan_timestamp"))
    return None


async def _fetch_and_process_batches(
    user_id: str,
    current_query: str,
    user_name: str | None,
    user_email: str | None,
    timer: _StepTimer,
) -> tuple[int, int, int, list[asyncio.Task[None]]]:
    """Fetch Gmail in batches, parse, and queue memory-storage tasks.

    Returns (total_fetched, total_parsed, total_failed, storage_tasks).
    """
    total_fetched = 0
    total_parsed = 0
    total_failed = 0
    page_token = None
    batch_count = 0
    email_storage_tasks: list[asyncio.Task[None]] = []

    try:
        while total_fetched < MAX_RESULTS:
            remaining = MAX_RESULTS - total_fetched
            batch_size = min(BATCH_SIZE, remaining)
            batch_count += 1

            t0_search = time.monotonic()
            result = await search_messages(
                user_id=user_id,
                query=current_query,
                max_results=batch_size,
                page_token=page_token,
            )
            fetch_elapsed = time.monotonic() - t0_search
            log.info(
                f"{LogTag.MEMORY} Gmail fetch batch completed",
                batch=batch_count,
                duration_s=round(fetch_elapsed, 1),
                fetched_so_far=total_fetched + len(result.messages),
                user_id=user_id,
            )
            timer.record(f"Gmail API fetch — batch {batch_count}", fetch_elapsed)

            batch_emails = result.messages

            if not batch_emails:
                break

            # Update page token for next iteration
            page_token = result.next_page_token

            # Update stats
            total_fetched += len(batch_emails)

            # Process content (platform emails automatically excluded)
            t0_parse = time.monotonic()
            processed_batch, failed = process_email_content(batch_emails)
            parse_elapsed = time.monotonic() - t0_parse
            total_parsed += len(processed_batch)
            total_failed += failed
            log.info(
                f"{LogTag.MEMORY} Email content parsing batch completed",
                batch=batch_count,
                duration_s=round(parse_elapsed, 3),
                parsed_count=len(processed_batch),
                failed_count=failed,
            )
            timer.record(
                f"Email parse (HTML→text) — batch {batch_count} ({len(processed_batch)} emails)",
                parse_elapsed,
            )

            # Store batch to memory in the background during onboarding
            if processed_batch:
                task = asyncio.create_task(
                    store_emails_to_memory(
                        user_id,
                        processed_batch,
                        user_name,
                        user_email,
                    )
                )
                email_storage_tasks.append(task)

            if not page_token:
                break

    except Exception as e:
        log.error(
            f"{LogTag.MEMORY} Error in email processing pipeline",
            error_type=type(e).__name__,
            error=str(e),
            user_id=user_id,
        )

    return total_fetched, total_parsed, total_failed, email_storage_tasks


async def _collect_storage_results(
    user_id: str, email_storage_tasks: list[asyncio.Task[None]], timer: _StepTimer
) -> int:
    """Await queued storage tasks; returns how many batches failed."""
    storage_errors = 0
    if not email_storage_tasks:
        return storage_errors
    try:
        t0_storage = time.monotonic()
        storage_results = await asyncio.gather(*email_storage_tasks, return_exceptions=True)
        storage_elapsed = time.monotonic() - t0_storage
        timer.record(
            f"Memory email storage await ({len(email_storage_tasks)} batches queued)",
            storage_elapsed,
        )
        log.info(
            f"{LogTag.MEMORY} Memory email storage tasks dispatched",
            duration_s=round(storage_elapsed, 1),
        )

        for idx, storage_result in enumerate(storage_results):
            if isinstance(storage_result, Exception):
                storage_errors += 1
                log.warning(
                    f"{LogTag.MEMORY} Email storage task failed",
                    task_index=idx + 1,
                    error_type=type(storage_result).__name__,
                    error=str(storage_result),
                )

        successful_batches = len(storage_results) - storage_errors
        log.info(
            f"{LogTag.MEMORY} Email storage complete",
            successful_batches=successful_batches,
            total_batches=len(storage_results),
            failed_batches=storage_errors,
        )
    except Exception as e:
        log.error(
            f"{LogTag.MEMORY} Critical error in email storage tasks",
            error_type=type(e).__name__,
            error=str(e),
            user_id=user_id,
        )
        storage_errors = len(email_storage_tasks)
    return storage_errors


async def _collect_profile_extraction(
    user_id: str,
    profile_extraction_task: "asyncio.Task[ProfileExtractionResult]",
    timer: _StepTimer,
) -> tuple[int, list[ExtractedProfile]]:
    """Wait for the parallel profile-extraction track; failures never block completion."""
    profiles_stored = 0
    extracted_profiles: list[ExtractedProfile] = []
    try:
        t0_profile = time.monotonic()
        profile_result = await profile_extraction_task
        profile_elapsed = time.monotonic() - t0_profile
        timer.record("Profile extraction track (wait for completion)", profile_elapsed)
        log.info(
            f"{LogTag.MEMORY} Profile extraction track finished",
            duration_s=round(profile_elapsed, 1),
        )
        profiles_stored = profile_result.get("profiles_stored", 0)
        extracted_profiles = profile_result.get("extracted_profiles", [])
    except Exception as e:
        log.error(
            f"{LogTag.MEMORY} Profile extraction task failed",
            error_type=type(e).__name__,
            error=str(e),
            user_id=user_id,
        )
        # Continue anyway - don't let profile failures block completion
    return profiles_stored, extracted_profiles


async def _mark_processing_complete(
    user_id: str,
    processing_complete: bool,
    processed_total: int,
    timer: _StepTimer,
    advance_watermark: bool = True,
) -> None:
    """Mark onboarding complete and refresh the scan timestamp; both best-effort.

    The Gmail scan watermark is only advanced when every storage task
    succeeded — advancing it after a failed write would permanently skip the
    emails that were parsed but never durably stored.
    """
    # ALWAYS mark as complete and trigger completion events
    # This ensures the frontend gets the "show me around" button
    try:
        if processing_complete:
            t0_mark = time.monotonic()
            await mark_email_processing_complete(user_id, processed_total)
            mark_elapsed = time.monotonic() - t0_mark
            timer.record("DB mark-complete write", mark_elapsed)
            log.info(
                f"{LogTag.MEMORY} mark_email_processing_complete finished",
                duration_s=round(mark_elapsed, 1),
            )
            log.info(f"{LogTag.MEMORY} Marked email processing as complete", user_id=user_id)
    except Exception as e:
        log.error(
            f"{LogTag.MEMORY} Failed to mark email processing complete",
            error_type=type(e).__name__,
            error=str(e),
            user_id=user_id,
        )

    # Update the scan timestamp only after durable storage succeeded, so a
    # later run re-fetches anything that failed to persist.
    if not advance_watermark:
        log.warning(
            f"{LogTag.MEMORY} Gmail scan watermark not advanced due to storage failures",
            user_id=user_id,
        )
        return
    try:
        current_time = datetime.now(UTC)
        await user_repository.set_gmail_scan_timestamp(user_id, current_time)
    except Exception as e:
        log.error(
            f"{LogTag.MEMORY} Failed to update Gmail scan timestamp",
            error_type=type(e).__name__,
            error=str(e),
            user_id=user_id,
        )


async def process_gmail_to_memory(user_id: str) -> GmailProcessingStats:
    """
    Process user's Gmail emails into memories.

    Flow:
    1. TWO PARALLEL TRACKS:
       A) Email scanning: Fetch all emails -> Store in memory (existing flow)
       B) Profile extraction: Parallel Gmail searches for platform emails -> LLM extraction -> Crawl -> Store
    2. Wait for both tracks to complete
    3. Mark user as processed

    Returns dict with processing stats.
    """
    timer = _StepTimer()
    user = await user_repository.get(user_id)
    if user and user.email_memory_processed:
        log.info(f"{LogTag.MEMORY} User emails already processed, skipping", user_id=user_id)
        return {
            "total": 0,
            "successful": 0,
            "already_processed": True,
            "processing_complete": True,
        }

    # Extract user name for consistent memory attribution
    user_name = user.name if user else None
    user_email = user.email if user else None

    fetch_start_time = time.time()

    # START PARALLEL TRACK: Profile extraction via targeted Gmail searches
    profile_extraction_task = asyncio.create_task(_extract_profiles_from_parallel_searches(user_id))

    # Build query with timestamp if available
    current_query = EMAIL_QUERY
    last_scan_timestamp = _latest_gmail_scan_timestamp(user)
    if isinstance(last_scan_timestamp, datetime):
        timestamp_seconds = int(last_scan_timestamp.timestamp())
        current_query = f"{EMAIL_QUERY} after:{timestamp_seconds}"

    t0_fetch_phase = time.monotonic()
    (
        total_fetched,
        total_parsed,
        total_failed,
        email_storage_tasks,
    ) = await _fetch_and_process_batches(user_id, current_query, user_name, user_email, timer)
    timer.record("Gmail fetch + parse phase (total)", time.monotonic() - t0_fetch_phase)

    # Await all email storage tasks in parallel with error handling
    log.info(
        f"{LogTag.MEMORY} Awaiting memory storage tasks",
        task_count=len(email_storage_tasks),
        email_count=total_parsed,
    )
    storage_errors = await _collect_storage_results(user_id, email_storage_tasks, timer)
    profiles_stored, extracted_profiles = await _collect_profile_extraction(
        user_id, profile_extraction_task, timer
    )

    total_elapsed = time.time() - fetch_start_time
    log.info(
        f"{LogTag.MEMORY} Processing complete",
        duration_s=round(total_elapsed, 2),
        parsed_count=total_parsed,
        profiles_stored=profiles_stored,
        storage_errors=storage_errors,
        user_id=user_id,
    )

    # Mark as complete if we processed ANY emails, even if some storage failed
    processing_complete = total_parsed > 0
    await _mark_processing_complete(
        user_id,
        processing_complete,
        total_parsed + profiles_stored,
        timer,
        advance_watermark=storage_errors == 0,
    )

    log.info(f"{LogTag.MEMORY} Onboarding email pipeline timing breakdown", summary=timer.summary())

    return {
        "total": total_fetched,
        "successful": total_parsed,
        "failed": total_failed,
        "profiles_stored": profiles_stored,
        "processing_complete": processing_complete,
        "extracted_profiles": extracted_profiles,
    }


def _collect_platform_results(
    user_id: str,
    platform_tasks: list[tuple[str, "asyncio.Task[PlatformProcessResult]"]],
    results: list[Any],
) -> tuple[int, list[ExtractedProfile], list["asyncio.Task[int]"]]:
    """Tally per-platform outcomes into (profiles_stored, profiles, discovery tasks)."""
    profiles_stored = 0
    extracted_profiles: list[ExtractedProfile] = []
    discovered_profile_tasks: list[asyncio.Task[int]] = []
    for (platform, _), result in zip(platform_tasks, results):
        if isinstance(result, Exception):
            log.error(
                f"{LogTag.MEMORY} Platform extraction failed",
                platform=platform,
                error_type=type(result).__name__,
                error=str(result),
                user_id=user_id,
            )
        elif isinstance(result, dict) and result.get("success"):
            if "discovery_task" in result:
                discovered_profile_tasks.append(result["discovery_task"])
            profiles_stored += 1
            extracted_profiles.append({"platform": result["platform"], "url": result["url"]})
    return profiles_stored, extracted_profiles, discovered_profile_tasks


async def _await_discovery_tasks(
    user_id: str, discovered_profile_tasks: list["asyncio.Task[int]"]
) -> int:
    """Wait for discovered-profile tasks; returns how many profiles they stored."""
    discovered_count = 0
    if not discovered_profile_tasks:
        return discovered_count
    t0_discovery = time.monotonic()
    discovery_results = await asyncio.gather(*discovered_profile_tasks, return_exceptions=True)
    log.info(
        f"{LogTag.MEMORY} Discovered profile tasks gather finished",
        duration_s=round(time.monotonic() - t0_discovery, 1),
    )
    for discovery_result in discovery_results:
        if isinstance(discovery_result, int):  # Discovery task returns count of profiles stored
            discovered_count += discovery_result
        elif isinstance(discovery_result, Exception):
            log.error(
                f"{LogTag.MEMORY} Discovery task failed",
                error_type=type(discovery_result).__name__,
                error=str(discovery_result),
                user_id=user_id,
            )
    return discovered_count


async def _extract_profiles_from_parallel_searches(user_id: str) -> ProfileExtractionResult:
    """
    Extract and store profiles using parallel Gmail searches for each platform.

    This is the new approach:
    1. Search Gmail API in parallel for emails from each platform
    2. Extract usernames from those emails using LLM in parallel
    3. Validate and crawl profiles in parallel
    4. Store all profiles in a single batch

    Args:
        user_id: User ID

    Returns:
        Dict with stats about profile extraction
    """
    try:
        extraction_start = time.time()

        # Get user context for memory storage
        user = await user_repository.get(user_id)
        user_name = user.name if user else None

        # Step 1: Parallel Gmail searches for all platforms
        t0_platform_search = time.monotonic()
        platform_emails = await _search_platform_emails_parallel(user_id)
        log.info(
            f"{LogTag.MEMORY} _search_platform_emails_parallel finished",
            duration_s=round(time.monotonic() - t0_platform_search, 1),
        )

        # Filter out platforms with no emails
        platforms_with_emails = {
            platform: emails for platform, emails in platform_emails.items() if emails
        }

        if not platforms_with_emails:
            return {"profiles_stored": 0}

        # Step 2: Extract usernames and crawl profiles in parallel
        crawl_semaphore = asyncio.Semaphore(20)
        platform_tasks = []
        # Discovered-profile tasks arrive from _collect_platform_results below.
        crawled_urls: set[str] = set()  # Global deduplication: track all URLs already crawled

        for platform, emails in platforms_with_emails.items():
            task = asyncio.create_task(
                _process_single_platform(
                    user_id,
                    platform,
                    emails,
                    crawl_semaphore,
                    user_name,
                    crawled_urls,
                )
            )
            platform_tasks.append((platform, task))

        # Wait for all platform processing
        t0_platform_gather = time.monotonic()
        results = await asyncio.gather(
            *[task for _, task in platform_tasks], return_exceptions=True
        )
        log.info(
            f"{LogTag.MEMORY} Platform tasks gather finished",
            duration_s=round(time.monotonic() - t0_platform_gather, 1),
        )

        # Step 3: Count successful profiles, collect pairs and discovery tasks
        profiles_stored, extracted_profiles, discovered_profile_tasks = _collect_platform_results(
            user_id, platform_tasks, results
        )

        # Step 4: Wait for discovered profiles and add to count
        discovered_count = await _await_discovery_tasks(user_id, discovered_profile_tasks)

        profiles_stored += discovered_count

        elapsed = time.time() - extraction_start
        log.info(
            f"{LogTag.MEMORY} Profile extraction completed",
            duration_s=round(elapsed, 2),
            profiles_stored=profiles_stored,
            platform_count=len(platforms_with_emails),
            discovered_count=discovered_count,
            user_id=user_id,
        )

        return {
            "profiles_stored": profiles_stored,
            "extracted_profiles": extracted_profiles,
        }

    except Exception as e:
        log.error(
            f"{LogTag.MEMORY} Error in profile extraction from parallel searches",
            error_type=type(e).__name__,
            error=str(e),
            user_id=user_id,
        )
        return {"profiles_stored": 0, "extracted_profiles": []}


async def _process_single_platform(
    user_id: str,
    platform: str,
    emails: list[dict[str, Any]],
    semaphore: asyncio.Semaphore,
    user_name: str | None = None,
    crawled_urls: set[str] | None = None,
) -> PlatformProcessResult:
    """
    Process a single platform: Extract -> Crawl -> Return content.
    Returns dict with profile content or error.

    Args:
        crawled_urls: Shared set to track already-crawled URLs for deduplication
    """
    try:
        t0_platform = time.monotonic()

        # 1. Extract username via LLM
        t0_llm = time.monotonic()
        username = await extract_username_with_llm(platform, emails, user_name, user_id=user_id)
        llm_elapsed = time.monotonic() - t0_llm
        log.info(
            f"{LogTag.MEMORY} LLM username extraction completed",
            platform=platform,
            duration_s=round(llm_elapsed, 1),
            username=username,
        )

        if not validate_username(username, platform):
            log.warning(
                f"{LogTag.MEMORY} Username validation failed",
                platform=platform,
                username=username,
                expected_pattern=PLATFORM_CONFIG[platform]["regex_pattern"],
            )
            return {"error": f"Invalid username '{username}' for {platform}"}

        profile_url = build_profile_url(username, platform)
        if not profile_url:
            log.warning(
                f"{LogTag.MEMORY} Could not build profile URL",
                platform=platform,
                username=username,
            )
            return {"error": f"Could not build URL for {platform}"}

        # Check if already crawled (deduplication)
        if crawled_urls is not None and profile_url in crawled_urls:
            return {"error": "duplicate", "url": profile_url}

        # Mark as crawled before actually crawling (prevent race conditions)
        if crawled_urls is not None:
            crawled_urls.add(profile_url)

        # 2. Crawl profile
        t0_crawl = time.monotonic()
        crawl_result = await crawl_profile_url(profile_url, platform, semaphore)
        crawl_elapsed = time.monotonic() - t0_crawl
        log.info(
            f"{LogTag.MEMORY} Profile crawl finished",
            platform=platform,
            duration_s=round(crawl_elapsed, 1),
            success=bool(crawl_result["content"]),
        )

        if not crawl_result["content"] or crawl_result["error"]:
            log.warning(
                f"{LogTag.MEMORY} Failed to crawl profile",
                platform=platform,
                error=crawl_result.get("error"),
            )
            return {"error": crawl_result.get("error", "Crawl failed")}

        # 3. Store profile
        t0_store = time.monotonic()
        await store_single_profile(
            user_id,
            platform,
            profile_url,
            crawl_result["content"],
            user_name,
        )
        store_elapsed = time.monotonic() - t0_store
        log.info(
            f"{LogTag.MEMORY} Memory profile store finished",
            platform=platform,
            duration_s=round(store_elapsed, 1),
        )
        log.info(
            f"{LogTag.MEMORY} Platform profile processing finished",
            platform=platform,
            total_s=round(time.monotonic() - t0_platform, 1),
            llm_s=round(llm_elapsed, 1),
            crawl_s=round(crawl_elapsed, 1),
            store_s=round(store_elapsed, 1),
        )

        # 4. Extract additional social links from profile content
        discovery_task = asyncio.create_task(
            _discover_and_store_linked_profiles(
                user_id, crawl_result["content"], platform, semaphore, crawled_urls
            )
        )

        # Return success indicator and discovery task
        return {
            "success": True,
            "platform": platform,
            "url": profile_url,
            "discovery_task": discovery_task,
        }

    except Exception as e:
        log.error(
            f"{LogTag.MEMORY} Error processing platform profile",
            platform=platform,
            error_type=type(e).__name__,
            error=str(e),
            user_id=user_id,
        )
        return {"error": str(e)}


def _source_domain_for(source_platform: str) -> str | None:
    """Resolve the source platform's domain so same-domain links are skipped."""
    for platform, config in PLATFORM_CONFIG.items():
        if platform == source_platform:
            return str(config["url_template"]).split("/")[2]
    return None


def _extract_linked_profile_links(
    profile_content: str,
    source_platform: str,
    crawled_urls: set[str] | None,
) -> dict[str, dict[str, str]]:
    """Scan profile content for other platforms' profile links, deduplicated."""
    discovered_profiles: dict[str, dict[str, str]] = {}
    source_domain = _source_domain_for(source_platform)

    for platform, config in PLATFORM_CONFIG.items():
        if platform == source_platform:
            continue  # Skip same platform

        # Build regex pattern from URL template
        url_template: str = config["url_template"]
        regex_pattern: str = config["regex_pattern"]

        # Skip if same domain (e.g., github.com profile linking to github.com)
        platform_domain = url_template.split("/")[2]
        if source_domain and platform_domain == source_domain:
            continue

        # Convert URL template to regex pattern
        # e.g., "https://github.com/{username}" -> r"github\.com/([a-zA-Z0-9...]+)"
        username_capture = regex_pattern.replace("^", "").replace("$", "")

        # Build pattern to match URLs
        pattern = (
            rf"(?:https?://)?(?:www\.)?{re.escape(platform_domain)}/(?:in/|@)?({username_capture})"
        )

        matches = re.findall(pattern, profile_content, re.IGNORECASE)
        for username in matches:
            if validate_username(username, platform):
                profile_url = build_profile_url(username, platform)

                # Skip if already crawled
                if crawled_urls is not None and profile_url in crawled_urls:
                    continue

                # Mark as crawled
                if crawled_urls is not None:
                    crawled_urls.add(profile_url)

                # Use username as key to deduplicate multiple mentions of same profile
                discovered_profiles[f"{platform}_{username}"] = {
                    "platform": platform,
                    "url": profile_url,
                    "username": username,
                }
    return discovered_profiles


async def _crawl_and_store_discovered(
    user_id: str,
    discovered_profiles: dict[str, dict[str, str]],
    source_platform: str,
    semaphore: asyncio.Semaphore,
) -> int:
    """Crawl discovered profile URLs and retain their content as memories."""
    crawl_tasks = []
    for profile_info in discovered_profiles.values():
        platform = profile_info["platform"]
        url = profile_info["url"]
        task = crawl_profile_url(url, platform, semaphore)
        crawl_tasks.append((platform, url, task))

    # Wait for all crawls
    results = await asyncio.gather(*[task for _, _, task in crawl_tasks], return_exceptions=True)

    # Store successful profiles
    profile_messages = []
    for (platform, url, _), result in zip(crawl_tasks, results):
        if isinstance(result, dict) and result.get("content") and not result.get("error"):
            memory_content = f"""User's {platform} profile: {url}

{result["content"]}
"""
            profile_messages.append({"role": "user", "content": memory_content})

    # Store in batch if we have any
    if not profile_messages:
        return 0

    retain_result = await memory_engine.retain(
        user_id,
        profile_messages,
        source_type=MemorySourceType.EMAIL,
        extraction_hints=(
            f"These are the user's own social profiles, discovered from their "
            f"{source_platform} emails. Extract durable facts about the user: "
            "handles, bio, role, projects, interests, and location."
        ),
    )
    if retain_result.facts_extracted > 0:
        log.info(
            f"{LogTag.MEMORY} Stored discovered profiles",
            profile_count=len(profile_messages),
            source_platform=source_platform,
            user_id=user_id,
        )
        return len(profile_messages)
    log.warning(
        f"{LogTag.MEMORY} No facts extracted from discovered profiles",
        source_platform=source_platform,
        user_id=user_id,
    )
    return 0


async def _discover_and_store_linked_profiles(
    user_id: str,
    profile_content: str,
    source_platform: str,
    semaphore: asyncio.Semaphore,
    crawled_urls: set[str] | None = None,
) -> int:
    """
    Parse profile content for other social media links and store them.

    Args:
        user_id: User ID
        profile_content: Crawled profile HTML/text content
        source_platform: Platform this content came from
        semaphore: Semaphore for rate limiting crawls

    Returns:
        Number of discovered profiles successfully stored
    """
    try:
        discovered_profiles = _extract_linked_profile_links(
            profile_content, source_platform, crawled_urls
        )

        if not discovered_profiles:
            return 0

        # Crawl and store discovered profiles in background
        return await _crawl_and_store_discovered(
            user_id, discovered_profiles, source_platform, semaphore
        )

    except Exception as e:
        log.error(
            f"{LogTag.MEMORY} Error discovering linked profiles",
            source_platform=source_platform,
            error_type=type(e).__name__,
            error=str(e),
            user_id=user_id,
        )
        return 0
