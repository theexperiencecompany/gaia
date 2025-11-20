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
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List

import html2text
from app.agents.memory.profile_extractor import (
    PLATFORM_CONFIG,
    extract_username_with_llm,
    validate_username,
    build_profile_url,
)
from app.agents.memory.profile_crawler import crawl_profile_url
from app.config.loggers import memory_logger as logger
from app.config.settings import settings
from app.db.mongodb.collections import users_collection
from app.services.mail.mail_service import search_messages
from app.services.memory_service import memory_service
from arq import create_pool
from arq.connections import RedisSettings
from bson import ObjectId

# Constants
EMAIL_QUERY = "in:inbox"
MAX_RESULTS = 700
BATCH_SIZE = 50
UNKNOWN_SENDER = "[Unknown]"
NO_SUBJECT = "[No Subject]"
# Debug flag - set to True to write detailed logs to JSON files
DEBUG_EMAIL_PROCESSING = True
h = html2text.HTML2Text()
h.ignore_links = True
h.body_width = 0
h.ignore_images = True
h.skip_internal_links = True


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
    logger.info("Starting parallel Gmail searches for profile extraction...")
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
    logger.info(f"Launching {len(search_tasks)} parallel Gmail searches...")
    results = await asyncio.gather(
        *[task for _, task in search_tasks], return_exceptions=True
    )

    # Build platform -> emails mapping
    platform_emails = {}
    for (platform, _), result in zip(search_tasks, results):
        if isinstance(result, Exception):
            logger.error(f"Search failed for {platform}: {result}")
            platform_emails[platform] = []
        elif isinstance(result, list):
            platform_emails[platform] = result
            logger.info(f"Found {len(result)} emails from {platform}")
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
        logger.info(f"Searching {platform} emails with query: {query}")

        result = await search_messages(
            user_id=user_id,
            query=query,
            max_results=max_results,
        )

        emails = result.get("messages", [])
        logger.info(f"Retrieved {len(emails)} emails for {platform}")

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

    storage_tasks = []

    fetch_start_time = time.time()
    page_token = None
    batch_count = 0

    # START PARALLEL TRACK: Profile extraction via targeted Gmail searches
    logger.info("Starting parallel processing: email storage + profile extraction")
    profile_extraction_task = asyncio.create_task(
        _extract_profiles_from_parallel_searches(user_id)
    )

    try:
        while total_fetched < MAX_RESULTS:
            remaining = MAX_RESULTS - total_fetched
            batch_size = min(BATCH_SIZE, remaining)
            batch_count += 1

            logger.info(
                f"Fetching batch {batch_count}, requesting {batch_size} emails, page_token: {page_token}"
            )

            result = await search_messages(
                user_id=user_id,
                query=EMAIL_QUERY,
                max_results=batch_size,
                page_token=page_token,
            )

            batch_emails = result.get("messages", [])
            logger.info(f"Batch {batch_count} returned {len(batch_emails)} emails")

            if not batch_emails:
                logger.info("No more emails returned, breaking")
                break

            # Update page token for next iteration
            page_token = result.get("nextPageToken")

            # Update stats
            total_fetched += len(batch_emails)

            # Process content immediately (no platform filtering - that's handled separately)
            processed_batch, failed = _process_email_content(batch_emails)
            total_parsed += len(processed_batch)
            total_failed += failed

            # 4. Store batch (Async)
            if processed_batch:
                task = asyncio.create_task(
                    _store_memories_batch(
                        user_id, processed_batch, user_name, user_email
                    )
                )
                storage_tasks.append(task)

            if not page_token:
                logger.info("No next page token, breaking")
                break

        fetch_elapsed = time.time() - fetch_start_time
        logger.info(
            f"Fetched and processed {total_fetched} emails in {fetch_elapsed:.2f}s"
        )

    except Exception as e:
        logger.error(f"Error in email processing pipeline: {e}")

    # Wait for both parallel tracks to complete
    logger.info("Waiting for storage tasks and profile extraction to complete...")

    # Wait for all storage tasks (Track A: Email storage)
    logger.info(f"Waiting for {len(storage_tasks)} storage tasks...")
    storage_results = await asyncio.gather(*storage_tasks, return_exceptions=True)

    # Calculate successful storage (count emails queued, not memories created)
    # Note: ARQ tasks return int (emails queued) on success, Exception on failure
    successful_stored = sum(r for r in storage_results if isinstance(r, int))
    failed_batches = sum(1 for r in storage_results if isinstance(r, Exception))

    if failed_batches > 0:
        logger.error(f"{failed_batches} storage batches failed with exceptions")
        for i, r in enumerate(storage_results):
            if isinstance(r, Exception):
                logger.error(f"Batch {i + 1} error: {r}")

    # Wait for profile extraction task (Track B: Profile extraction)
    logger.info("Waiting for profile extraction task...")
    profiles_stored = 0
    try:
        profile_result = await profile_extraction_task
        profiles_stored = profile_result.get("profiles_stored", 0)
        logger.info(f"Profile extraction completed: {profiles_stored} profiles stored")
    except Exception as e:
        logger.error(f"Profile extraction task failed: {e}")

    total_elapsed = time.time() - fetch_start_time
    logger.info(
        f"Processing complete in {total_elapsed:.2f}s: "
        f"{successful_stored} emails stored, {profiles_stored} profiles stored"
    )

    processing_complete = successful_stored > 0
    if processing_complete:
        await _mark_processed(user_id, successful_stored + profiles_stored)

        # Trigger post-onboarding personalization
        try:
            from app.services.post_onboarding_service import (
                process_post_onboarding_personalization,
            )

            logger.info(
                f"Triggering post-onboarding personalization for user {user_id}"
            )
            await process_post_onboarding_personalization(user_id)
        except Exception as e:
            logger.error(f"Post-onboarding personalization failed: {e}", exc_info=True)
            # Don't fail the main process

    return {
        "total": total_fetched,
        "successful": successful_stored,
        "failed": total_failed + (total_parsed - successful_stored),
        "profiles_stored": profiles_stored,
        "processing_complete": processing_complete,
    }


def remove_invisible_chars(s):
    """Remove invisible Unicode characters."""
    return "".join(c for c in s if unicodedata.category(c) not in ("Cf", "Cc"))


def _process_email_content(emails: List[Dict]) -> tuple[List[Dict], int]:
    """Process email content converting HTML to clean text."""
    processed = []
    failed_count = 0

    for email_data in emails:
        try:
            message_text = email_data.get("messageText", "")
            if not message_text.strip():
                failed_count += 1
                continue

            # Convert HTML to clean text
            clean_text = h.handle(message_text).strip()
            clean_text = remove_invisible_chars(clean_text)

            if not clean_text:
                failed_count += 1
                continue

            processed.append(
                {
                    "content": clean_text,
                    "metadata": {
                        "type": "email",
                        "source": "gmail",
                        "message_id": email_data.get("messageId")
                        or email_data.get("id"),
                        "sender": email_data.get("sender")
                        or email_data.get("from", UNKNOWN_SENDER),
                        "subject": email_data.get("subject", NO_SUBJECT),
                    },
                }
            )
        except Exception:
            failed_count += 1

    return processed, failed_count


async def _store_memories_batch(
    user_id: str,
    processed_emails: List[Dict],
    user_name: str | None = None,
    user_email: str | None = None,
) -> int:
    """Store memories in batches using ARQ background task."""
    if not processed_emails:
        return 0

    storage_start_time = time.time()

    try:
        redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
        pool = await create_pool(redis_settings)

        # Enqueue the batch memory storage task with user context
        job = await pool.enqueue_job(
            "store_memories_batch",
            user_id,
            processed_emails,
            user_name,
            user_email,
        )

        await pool.close()

        if job:
            storage_elapsed = time.time() - storage_start_time
            logger.info(
                f"Email storage: queued {len(processed_emails)} emails in "
                f"{storage_elapsed:.2f}s (job ID: {job.job_id})"
            )
            return len(processed_emails)
        else:
            logger.error("Failed to queue memory storage task")
            return 0

    except Exception as e:
        storage_elapsed = time.time() - storage_start_time
        logger.error(
            f"Error queuing memory storage task after {storage_elapsed:.2f}s: {e}"
        )
        return 0


async def _mark_processed(user_id: str, memory_count: int) -> None:
    """Mark user's email processing as complete."""
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "email_memory_processed": True,
                "email_memory_processed_at": datetime.now(timezone.utc),
                "email_memory_count": memory_count,
            }
        },
    )


async def _write_debug_log(filename: str, data: dict) -> None:
    """Write debug data to JSON file."""
    if not DEBUG_EMAIL_PROCESSING:
        return

    filepath = os.path.join(os.path.dirname(__file__), "debug_logs", filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Debug log written: {filepath}")
    except Exception as e:
        logger.error(f"Failed to write debug log {filename}: {e}")


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
        user_email = user.get("email") if user else None

        # Step 1: Parallel Gmail searches for all platforms
        platform_emails = await _search_platform_emails_parallel(user_id)

        # Filter out platforms with no emails
        platforms_with_emails = {
            platform: emails for platform, emails in platform_emails.items() if emails
        }

        if not platforms_with_emails:
            logger.info("No platform emails found for profile extraction")
            return {"profiles_stored": 0}

        logger.info(
            f"Processing {len(platforms_with_emails)} platforms with emails: "
            f"{list(platforms_with_emails.keys())}"
        )

        # Step 2: Extract usernames and crawl profiles in parallel
        crawl_semaphore = asyncio.Semaphore(20)  # Limit concurrent crawls
        platform_tasks = []
        discovered_profile_tasks = []  # Track discovery tasks
        crawled_urls = set()  # Global deduplication: track all URLs already crawled

        for platform, emails in platforms_with_emails.items():
            task = asyncio.create_task(
                _process_single_platform(
                    user_id, platform, emails, crawl_semaphore, user_name, crawled_urls
                )
            )
            platform_tasks.append((platform, task))

        # Wait for all platform processing
        logger.info(f"Waiting for {len(platform_tasks)} platform extraction tasks...")
        results = await asyncio.gather(
            *[task for _, task in platform_tasks], return_exceptions=True
        )

        # Step 3: Filter successful profiles and collect discovery tasks
        successful_profiles = []
        for (platform, _), result in zip(platform_tasks, results):
            if isinstance(result, Exception):
                logger.error(f"Platform {platform} extraction failed: {result}")
            elif (
                isinstance(result, dict)
                and "content" in result
                and "error" not in result
            ):
                # Collect discovery task if present
                if "discovery_task" in result:
                    discovered_profile_tasks.append(result["discovery_task"])
                    # Remove it from profile dict before storing
                    result = {k: v for k, v in result.items() if k != "discovery_task"}

                successful_profiles.append(result)
                logger.info(f"✓ Successfully extracted profile for {platform}")
            elif isinstance(result, dict):
                logger.warning(
                    f"✗ Failed to extract profile for {platform}: "
                    f"{result.get('error', 'Unknown error')}"
                )
            else:
                logger.warning(
                    f"✗ Failed to extract profile for {platform}: Unknown error"
                )

        # Step 4: Store all profiles in a single batch
        profiles_stored = 0
        if successful_profiles:
            logger.info(
                f"Storing {len(successful_profiles)} profiles in a single API call..."
            )

            # Build messages for batch storage
            profile_messages = []
            user_context = ""
            if user_name:
                user_context = f"The user's name is {user_name}."
                if user_email:
                    user_context += f" Their email is {user_email}."

            for profile in successful_profiles:
                memory_content = f"""User's {profile["platform"]} profile: {profile["url"]} {profile["content"]} """
                profile_messages.append({"role": "user", "content": memory_content})

            # Single API call to store all profiles
            batch_success = await memory_service.store_memory_batch(
                messages=profile_messages,
                user_id=user_id,
                metadata={
                    "type": "social_profile",
                    "source": "parallel_gmail_search_extraction",
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                    "batch_size": len(profile_messages),
                    "user_name": user_name,
                    "user_email": user_email,
                },
            )

            if batch_success:
                profiles_stored = len(successful_profiles)
                logger.info(f"Successfully stored {profiles_stored} profiles")
            else:
                logger.error("Failed to store profile batch")

        # Step 5: Wait for discovered profiles and add to count
        discovered_count = 0
        if discovered_profile_tasks:
            logger.info(
                f"Waiting for {len(discovered_profile_tasks)} discovery tasks to complete..."
            )
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

            logger.info(f"Discovered and stored {discovered_count} additional profiles")
            profiles_stored += discovered_count

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
) -> Dict:
    """
    Process a single platform: Extract -> Crawl -> Return content.
    Returns dict with profile content or error.

    Args:
        crawled_urls: Shared set to track already-crawled URLs for deduplication
    """
    try:
        # Debug: Log emails being processed for this platform
        if DEBUG_EMAIL_PROCESSING:
            debug_data = {
                "platform": platform,
                "user_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "num_emails": len(emails),
                "emails": [
                    {
                        "subject": e.get("subject", ""),
                        "sender": e.get("sender", ""),
                        "messageText": e.get("messageText", ""),
                    }
                    for e in emails
                ],
            }
            await _write_debug_log(f"{platform}_emails_input.json", debug_data)

        # 1. Extract username
        username = await extract_username_with_llm(platform, emails, user_name)

        # Debug: Log extraction result
        if DEBUG_EMAIL_PROCESSING:
            await _write_debug_log(
                f"{platform}_username_extracted.json",
                {
                    "platform": platform,
                    "extracted_username": username,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        if not validate_username(username, platform):
            logger.warning(
                f"Username validation failed for {platform}: '{username}' "
                f"(expected pattern: {PLATFORM_CONFIG[platform]['regex_pattern']})"
            )

            # Debug: Log validation failure
            if DEBUG_EMAIL_PROCESSING:
                await _write_debug_log(
                    f"{platform}_validation_failed.json",
                    {
                        "platform": platform,
                        "extracted_username": username,
                        "expected_pattern": PLATFORM_CONFIG[platform]["regex_pattern"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
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
            logger.info(f"Skipping already crawled profile: {profile_url}")
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

        # 3. Extract additional social links from profile content and return task
        discovery_task = asyncio.create_task(
            _discover_and_store_linked_profiles(
                user_id, crawl_result["content"], platform, semaphore, crawled_urls
            )
        )

        # Return profile data for batch storage
        return {
            "platform": platform,
            "url": profile_url,
            "content": crawl_result["content"],
            "discovery_task": discovery_task,  # Include task for tracking
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
                source_domain = config["url_template"].split("/")[2]
                break

        # Extract links from content using platform config
        for platform, config in PLATFORM_CONFIG.items():
            if platform == source_platform:
                continue  # Skip same platform

            # Build regex pattern from URL template
            url_template = config["url_template"]
            regex_pattern = config["regex_pattern"]

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
                        logger.info(
                            f"Discovered {platform} profile from {source_platform}: {profile_url}"
                        )

        if not discovered_profiles:
            logger.info(f"No additional profiles discovered from {source_platform}")
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
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        user_name = user.get("name") if user else None
        user_email = user.get("email") if user else None
        user_context = ""
        if user_name:
            user_context = f"The user's name is {user_name}."
            if user_email:
                user_context += f" Their email is {user_email}."

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
                logger.info(f"✓ Discovered profile ready for storage: {platform}")

        # Store in batch if we have any
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
