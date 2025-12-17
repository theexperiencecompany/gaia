"""Process Gmail emails and extract user profiles for memory storage.

Flow:
1. Two independent parallel tracks start simultaneously:

   TRACK A - Email Scanning & Storage:
   - Fetch recent emails from Gmail API (in:inbox, up to 700 emails in batches of 50)
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
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from bson import ObjectId

from app.helpers.email_helpers import (
    mark_email_processing_complete,
    process_email_content,
    store_emails_to_mem0,
    store_single_profile,
)
from app.agents.memory.profile_crawler import crawl_profile_url
from app.agents.memory.profile_extractor import (
    PLATFORM_CONFIG,
    build_profile_url,
    extract_username_with_llm,
    validate_username,
)
from app.config.loggers import memory_logger as logger
from app.db.mongodb.collections import users_collection
from app.services.mail.mail_service import search_messages
from app.services.memory_service import memory_service
from app.services.post_onboarding_service import (
    emit_progress,
    process_post_onboarding_personalization,
)

# Constants
EMAIL_QUERY = "in:inbox"
MAX_RESULTS = 100
BATCH_SIZE = 50


async def _search_platform_emails_parallel(user_id: str) -> Dict[str, List[Dict]]:
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
    results = await asyncio.gather(
        *[task for _, task in search_tasks], return_exceptions=True
    )

    # Build platform -> emails mapping
    platform_emails: Dict[str, List[Dict]] = {}
    for (platform, _), result in zip(search_tasks, results):
        if isinstance(result, Exception):
            logger.error(f"Search failed for {platform}: {result}")
            platform_emails[platform] = []
        elif isinstance(result, list):
            platform_emails[platform] = result
        else:
            platform_emails[platform] = []

    elapsed = time.time() - search_start
    total_found = sum(len(emails) for emails in platform_emails.values())
    logger.info(
        f"Parallel Gmail searches completed in {elapsed:.2f}s: "
        f"found {total_found} platform emails across {len(platform_emails)} platforms"
    )

    return platform_emails


async def _search_platform_emails(
    user_id: str, platform: str, query: str, max_results: int = 50
) -> List[Dict]:
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

        emails = result.get("messages", [])
        return emails

    except Exception as e:
        logger.error(f"Error searching {platform} emails: {e}")
        return []


async def process_gmail_to_memory(user_id: str) -> Dict:
    """
    Process user's Gmail emails into Mem0 memories.

    Flow:
    1. TWO PARALLEL TRACKS:
       A) Email scanning: Fetch all emails -> Store in memory (existing flow)
       B) Profile extraction: Parallel Gmail searches for platform emails -> LLM extraction -> Crawl -> Store
    2. Wait for both tracks to complete
    3. Mark user as processed

    Returns dict with processing stats.
    """
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if user and user.get("email_memory_processed", False):
        logger.info(f"User {user_id} emails already processed, skipping")
        return {
            "total": 0,
            "successful": 0,
            "already_processed": True,
            "processing_complete": True,
        }

    # Extract user name for consistent memory attribution
    user_name = user.get("name") if user else None
    user_email = user.get("email") if user else None

    # State tracking
    total_fetched = 0
    total_parsed = 0
    total_failed = 0

    fetch_start_time = time.time()
    page_token = None
    batch_count = 0

    # Track memory storage tasks to await completion
    email_storage_tasks = []

    # START PARALLEL TRACK: Profile extraction via targeted Gmail searches
    profile_extraction_task = asyncio.create_task(
        _extract_profiles_from_parallel_searches(user_id)
    )

    # Emit initial progress
    try:
        await emit_progress(
            user_id,
            "exploring",
            "🌌 Exploring your universe...",
            15,
            {"current": 0, "total": MAX_RESULTS},
        )
    except Exception as e:
        logger.warning(f"Failed to emit initial progress: {e}")

    # Check for last scan timestamp
    last_scan_timestamp = None
    if user:
        scan_states = user.get("integration_scan_states", {})
        if isinstance(scan_states, dict):
            gmail_state = scan_states.get("gmail", {})
            if isinstance(gmail_state, dict):
                last_scan_timestamp = gmail_state.get("last_scan_timestamp")

    # Build query with timestamp if available
    current_query = EMAIL_QUERY
    if last_scan_timestamp:
        if isinstance(last_scan_timestamp, datetime):
            timestamp_seconds = int(last_scan_timestamp.timestamp())
            current_query = f"{EMAIL_QUERY} after:{timestamp_seconds}"

    try:
        while total_fetched < MAX_RESULTS:
            remaining = MAX_RESULTS - total_fetched
            batch_size = min(BATCH_SIZE, remaining)
            batch_count += 1

            result = await search_messages(
                user_id=user_id,
                query=current_query,
                max_results=batch_size,
                page_token=page_token,
            )

            batch_emails = result.get("messages", [])

            if not batch_emails:
                break

            # Update page token for next iteration
            page_token = result.get("nextPageToken")

            # Update stats
            total_fetched += len(batch_emails)

            # Emit progress update
            try:
                progress_percent = min(15 + int((total_fetched / MAX_RESULTS) * 40), 55)
                await emit_progress(
                    user_id,
                    "exploring",
                    "🌌 Exploring your universe...",
                    progress_percent,
                    {"current": total_fetched, "total": MAX_RESULTS},
                )
            except Exception as e:
                logger.warning(f"Failed to emit progress update: {e}")

            # Process content (platform emails automatically excluded)
            processed_batch, failed = process_email_content(batch_emails)
            total_parsed += len(processed_batch)
            total_failed += failed

            # Store batch to Mem0 with sync mode during onboarding (ensures completion)
            if processed_batch:
                task = asyncio.create_task(
                    store_emails_to_mem0(
                        user_id,
                        processed_batch,
                        user_name,
                        user_email,
                        async_mode=False,
                    )
                )
                email_storage_tasks.append(task)

            if not page_token:
                break

    except Exception as e:
        logger.error(f"Error in email processing pipeline: {e}")

    # Await all email storage tasks in parallel with error handling
    logger.info(
        f"Awaiting {len(email_storage_tasks)} email storage tasks to complete in parallel..."
    )
    storage_results: list[Any] = []
    storage_errors = 0
    if email_storage_tasks:
        try:
            # Gather all results, including exceptions
            storage_results = await asyncio.gather(
                *email_storage_tasks, return_exceptions=True
            )

            # Count successes and errors
            for idx, result in enumerate(storage_results):
                if isinstance(result, Exception):
                    storage_errors += 1
                    logger.warning(f"Email storage task {idx + 1} failed: {result}")

            successful_batches = len(storage_results) - storage_errors
            logger.info(
                f"Email storage complete: {successful_batches}/{len(storage_results)} batches succeeded, "
                f"{storage_errors} failed (continuing anyway)"
            )
        except Exception as e:
            logger.error(f"Critical error in email storage tasks: {e}")
            storage_errors = len(email_storage_tasks)

    # Wait for profile extraction task (also with error handling)
    profiles_stored = 0
    try:
        profile_result: Dict[str, int] = await profile_extraction_task
        profiles_stored = profile_result.get("profiles_stored", 0)
    except Exception as e:
        logger.error(f"Profile extraction task failed: {e}")
        # Continue anyway - don't let profile failures block completion

    total_elapsed = time.time() - fetch_start_time
    logger.info(
        f"Processing complete in {total_elapsed:.2f}s: "
        f"{total_parsed} emails processed, {profiles_stored} profiles stored, "
        f"{storage_errors} storage errors"
    )

    # Mark as complete if we processed ANY emails, even if some storage failed
    processing_complete = total_parsed > 0

    # ALWAYS mark as complete and trigger completion events
    # This ensures the frontend gets the "show me around" button
    try:
        if processing_complete:
            await mark_email_processing_complete(
                user_id, total_parsed + profiles_stored
            )
            logger.info(f"✓ Marked email processing as complete for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to mark email processing complete: {e}")
        # Continue anyway - we still want to trigger post-onboarding

    # Trigger post-onboarding personalization (always run, even if storage had errors)
    try:
        await process_post_onboarding_personalization(user_id)
        logger.info(f"✓ Post-onboarding personalization triggered for user {user_id}")
    except Exception as e:
        logger.error(f"Post-onboarding personalization failed: {e}", exc_info=True)
        # Don't fail the entire process - user still gets onboarded

    # Update the scan timestamp after processing (regardless of success/failure)
    # This prevents re-scanning the same emails
    try:
        current_time = datetime.now(timezone.utc)
        await users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "integration_scan_states.gmail.last_scan_timestamp": current_time
                }
            },
        )
    except Exception as e:
        logger.error(f"Failed to update Gmail scan timestamp: {e}")

    return {
        "total": total_fetched,
        "successful": total_parsed,
        "failed": total_failed,
        "profiles_stored": profiles_stored,
        "processing_complete": processing_complete,
    }


async def _extract_profiles_from_parallel_searches(user_id: str) -> Dict:
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
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        user_name = user.get("name") if user else None

        # Step 1: Parallel Gmail searches for all platforms
        platform_emails = await _search_platform_emails_parallel(user_id)

        # Filter out platforms with no emails
        platforms_with_emails = {
            platform: emails for platform, emails in platform_emails.items() if emails
        }

        if not platforms_with_emails:
            return {"profiles_stored": 0}

        # Step 2: Extract usernames and crawl profiles in parallel
        crawl_semaphore = asyncio.Semaphore(20)  # Limit concurrent crawls
        platform_tasks = []
        discovered_profile_tasks = []  # Track discovery tasks
        crawled_urls: set[str] = (
            set()
        )  # Global deduplication: track all URLs already crawled

        for platform, emails in platforms_with_emails.items():
            task = asyncio.create_task(
                _process_single_platform(
                    user_id,
                    platform,
                    emails,
                    crawl_semaphore,
                    user_name,
                    crawled_urls,
                    async_mode=False,
                )
            )
            platform_tasks.append((platform, task))

        # Wait for all platform processing
        results = await asyncio.gather(
            *[task for _, task in platform_tasks], return_exceptions=True
        )

        # Step 3: Count successful profiles and collect discovery tasks
        profiles_stored = 0
        for (platform, _), result in zip(platform_tasks, results):
            if isinstance(result, Exception):
                logger.error(f"Platform {platform} extraction failed: {result}")
            elif isinstance(result, dict) and result.get("success"):
                if "discovery_task" in result:
                    discovered_profile_tasks.append(result["discovery_task"])
                profiles_stored += 1

        # Step 4: Wait for discovered profiles and add to count
        discovered_count = 0
        if discovered_profile_tasks:
            discovery_results = await asyncio.gather(
                *discovered_profile_tasks, return_exceptions=True
            )
            for result in discovery_results:
                if isinstance(
                    result, int
                ):  # Discovery task returns count of profiles stored
                    discovered_count += result
                elif isinstance(result, Exception):
                    logger.error(f"Discovery task failed: {result}")

        elapsed = time.time() - extraction_start
        logger.info(
            f"Profile extraction completed in {elapsed:.2f}s: "
            f"{profiles_stored}/{len(platforms_with_emails)} profiles stored (including {discovered_count} discovered)"
        )

        return {"profiles_stored": profiles_stored}

    except Exception as e:
        logger.error(f"Error in profile extraction from parallel searches: {e}")
        return {"profiles_stored": 0}


async def _process_single_platform(
    user_id: str,
    platform: str,
    emails: List[Dict],
    semaphore: asyncio.Semaphore,
    user_name: str | None = None,
    crawled_urls: set | None = None,
    async_mode: bool = False,
) -> Dict:
    """
    Process a single platform: Extract -> Crawl -> Return content.
    Returns dict with profile content or error.

    Args:
        crawled_urls: Shared set to track already-crawled URLs for deduplication
        async_mode: Memory storage mode (False for onboarding to ensure completion)
    """
    try:
        # 1. Extract username
        username = await extract_username_with_llm(platform, emails, user_name)

        if not validate_username(username, platform):
            logger.warning(
                f"Username validation failed for {platform}: '{username}' "
                f"(expected pattern: {PLATFORM_CONFIG[platform]['regex_pattern']})"
            )
            return {"error": f"Invalid username '{username}' for {platform}"}

        profile_url = build_profile_url(username, platform)
        if not profile_url:
            logger.warning(
                f"Could not build profile URL for {platform} with username: {username}"
            )
            return {"error": f"Could not build URL for {platform}"}

        # Check if already crawled (deduplication)
        if crawled_urls is not None and profile_url in crawled_urls:
            return {"error": "duplicate", "url": profile_url}

        # Mark as crawled before actually crawling (prevent race conditions)
        if crawled_urls is not None:
            crawled_urls.add(profile_url)

        # 2. Crawl profile
        crawl_result = await crawl_profile_url(profile_url, platform, semaphore)

        if not crawl_result["content"] or crawl_result["error"]:
            logger.warning(
                f"Failed to crawl {platform} profile: {crawl_result.get('error')}"
            )
            return {"error": crawl_result.get("error", "Crawl failed")}

        # 3. Store profile with configured mode
        await store_single_profile(
            user_id,
            platform,
            profile_url,
            crawl_result["content"],
            user_name,
            async_mode=async_mode,
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
        logger.error(f"Error processing {platform} profile: {e}")
        return {"error": str(e)}


async def _discover_and_store_linked_profiles(
    user_id: str,
    profile_content: str,
    source_platform: str,
    semaphore: asyncio.Semaphore,
    crawled_urls: set | None = None,
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
        discovered_profiles = {}

        # Extract source domain to avoid crawling same domain
        source_domain = None
        for platform, config in PLATFORM_CONFIG.items():
            if platform == source_platform:
                source_domain = str(config["url_template"]).split("/")[2]
                break

        # Extract links from content using platform config
        for platform, config in PLATFORM_CONFIG.items():
            if platform == source_platform:
                continue  # Skip same platform

            # Build regex pattern from URL template
            url_template: str = config["url_template"]  # type: ignore[assignment]
            regex_pattern: str = config["regex_pattern"]  # type: ignore[assignment]

            # Skip if same domain (e.g., github.com profile linking to github.com)
            platform_domain = url_template.split("/")[2]
            if source_domain and platform_domain == source_domain:
                continue

            # Convert URL template to regex pattern
            # e.g., "https://github.com/{username}" -> r"github\.com/([a-zA-Z0-9...]+)"
            username_capture = regex_pattern.replace("^", "").replace("$", "")

            # Build pattern to match URLs
            pattern = rf"(?:https?://)?(?:www\.)?{re.escape(platform_domain)}/(?:in/|@)?({username_capture})"

            matches = re.findall(pattern, profile_content, re.IGNORECASE)
            if matches:
                # Validate all found usernames and store them
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

        if not discovered_profiles:
            return 0

        # Crawl and store discovered profiles in background
        crawl_tasks = []
        for key, profile_info in discovered_profiles.items():
            platform = profile_info["platform"]
            url = profile_info["url"]
            task = crawl_profile_url(url, platform, semaphore)
            crawl_tasks.append((platform, url, task))

        # Wait for all crawls
        results = await asyncio.gather(
            *[task for _, _, task in crawl_tasks], return_exceptions=True
        )

        # Store successful profiles
        profile_messages = []
        for (platform, url, _), result in zip(crawl_tasks, results):
            if (
                isinstance(result, dict)
                and result.get("content")
                and not result.get("error")
            ):
                memory_content = f"""User's {platform} profile: {url}

{result["content"]}
"""
                profile_messages.append({"role": "user", "content": memory_content})

        # Store in batch if we have any (sync mode for onboarding)
        if profile_messages:
            success = await memory_service.store_memory_batch(
                messages=profile_messages,
                user_id=user_id,
                metadata={
                    "type": "social_profile",
                    "source": f"discovered_from_{source_platform}",
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "batch_size": len(profile_messages),
                },
                async_mode=False,
            )
            if success:
                logger.info(
                    f"✓ Stored {len(profile_messages)} discovered profiles from {source_platform}"
                )
                return len(profile_messages)
            else:
                logger.error(
                    f"Failed to store discovered profiles from {source_platform}"
                )
                return 0

        return 0

    except Exception as e:
        logger.error(f"Error discovering linked profiles from {source_platform}: {e}")
        return 0
