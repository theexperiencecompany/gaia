"""Unit tests for app.agents.memory.email_processor.

Behavior specs (what's expected / mechanism / must-catch) for every targeted unit.

UNIT: _search_platform_emails(user_id, platform, query, max_results=10)
EXPECTED: Call Gmail search with the exact query/max_results, return result["messages"];
          on any exception return [] (swallowed, logged).
MECHANISM: search_messages(user_id=, query=, max_results=); return result.get("messages", []).
MUST-CATCH:
  - search_messages is called with the given query (not a constant) and the given user_id
  - default max_results is 10 (mutating the literal must fail a test)
  - missing "messages" key -> [] (not KeyError)
  - exception -> [] (error path swallowed)

UNIT: _search_platform_emails_parallel(user_id)
EXPECTED: For every platform in PLATFORM_CONFIG, OR-join its sender_domains into a
          "from:" query, search in parallel, return {platform: emails}. A failed
          platform search yields [] for that platform; non-list results yield [].
MECHANISM: build "from:d1 OR from:d2" per platform; asyncio.gather(..., return_exceptions=True);
           classify each result (Exception/list/other) into platform_emails.
MUST-CATCH:
  - the per-platform query joins ALL sender_domains with " OR " and "from:" prefix
  - results map to the right platform (zip order preserved)
  - empty PLATFORM_CONFIG -> {}
  - an exception for one platform -> that platform maps to []

UNIT: _process_single_platform(user_id, platform, emails, semaphore, user_name, crawled_urls, async_mode)
EXPECTED: Extract username via LLM, validate it, build URL, dedupe against crawled_urls,
          crawl, store, and return a success dict carrying platform+url+a discovery_task.
          Each guard returns a distinct {"error": ...} shape.
MECHANISM: extract_username_with_llm -> validate_username -> build_profile_url ->
           crawled_urls membership check -> crawled_urls.add -> crawl_profile_url ->
           store_single_profile -> create discovery task.
MUST-CATCH:
  - invalid username short-circuits with "Invalid username" before crawling
  - unbuildable URL short-circuits with "Could not build URL"
  - URL already in crawled_urls -> {"error": "duplicate", "url": ...}, no crawl
  - the URL is added to crawled_urls BEFORE crawling
  - crawl failure (no content / error set) returns the crawl error, no store
  - success path stores the crawled content and returns success/platform/url/discovery_task
  - store_single_profile receives the real crawled content and async_mode flag
  - any exception -> {"error": <str(exc)>}

UNIT: process_gmail_to_memory(user_id)
EXPECTED: Skip already-processed users. Otherwise fetch emails in batches, parse+store
          each batch, await the parallel profile-extraction track, mark complete only when
          something parsed, persist a fresh scan timestamp, and return aggregate stats.
MECHANISM: users_collection.find_one; early-return if email_memory_processed; launch
           _extract_profiles_from_parallel_searches task; loop search_messages/process_email_content/
           store_emails_to_mem0; await profile task; mark_email_processing_complete(total_parsed+profiles_stored)
           only when total_parsed>0; users_collection.update_one(scan timestamp); return stats dict.
MUST-CATCH:
  - already-processed user returns early with total=0, already_processed=True, no search
  - timestamp in scan state appends "after:<epoch>" to the query
  - processing_complete is True only when emails were parsed, False when none parsed
  - profile-extraction failure does not block completion (profiles_stored=0, still returns)
  - mark_email_processing_complete failure is swallowed; result still returned
  - mark_email_processing_complete is called with total_parsed+profiles_stored
  - the scan timestamp is always persisted via update_one

UNIT: _extract_profiles_from_parallel_searches(user_id)
EXPECTED: Run parallel platform searches, drop empty platforms, process each platform,
          count stored profiles, await discovery tasks, return stats. Empty -> {profiles_stored:0}.
MECHANISM: users_collection.find_one; _search_platform_emails_parallel; filter empties;
           per-platform _process_single_platform tasks; count success dicts; gather discovery tasks.
MUST-CATCH:
  - no platforms with emails -> {"profiles_stored": 0}
  - a successful platform increments profiles_stored and records {platform,url}
  - top-level exception -> {"profiles_stored": 0, "extracted_profiles": []}

UNIT: _discover_and_store_linked_profiles(user_id, profile_content, source_platform, semaphore, crawled_urls)
EXPECTED: Find foreign-platform profile links in content, validate, dedupe, crawl, and
          batch-store them; return the count stored. Same-platform / same-domain links and
          already-crawled URLs are skipped. No links -> 0. Failed store -> 0.
MECHANISM: build per-platform regex from url_template domain; re.findall on content;
           validate_username; build_profile_url; crawled_urls dedupe; crawl_profile_url;
           memory_service.store_memory_batch.
MUST-CATCH:
  - a foreign-platform link is discovered, crawled, stored, and counted
  - the source platform is skipped (no self-discovery)
  - already-crawled URLs are skipped (count 0)
  - crawl yielding no content -> not stored (count 0)
  - store_memory_batch returning False -> count 0
  - any exception -> 0

EQUIVALENT MUTANTS (allowed survivors, justified): documented per-run below; primarily
log-only string mutations and timing/`time.monotonic()` arithmetic that never affect
return values or control flow.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import pytest

from app.agents.memory.email_processor import (
    _discover_and_store_linked_profiles,
    _extract_profiles_from_parallel_searches,
    _process_single_platform,
    _search_platform_emails,
    _search_platform_emails_parallel,
    process_gmail_to_memory,
)

pytestmark = pytest.mark.asyncio

# Valid 24-char hex string so ObjectId(user_id) does not raise.
USER_ID = "507f1f77bcf86cd799439011"

# Patch targets resolved in the module-under-test's namespace (I/O boundaries only).
_PATCH_USERS = "app.agents.memory.email_processor.users_collection"
_PATCH_SEARCH = "app.agents.memory.email_processor.search_messages"
_PATCH_PROCESS = "app.agents.memory.email_processor.process_email_content"
_PATCH_STORE_EMAILS = "app.agents.memory.email_processor.store_emails_to_mem0"
_PATCH_MARK_COMPLETE = "app.agents.memory.email_processor.mark_email_processing_complete"
_PATCH_EXTRACT_PROFILES = (
    "app.agents.memory.email_processor._extract_profiles_from_parallel_searches"
)
_PATCH_PLATFORM_CONFIG = "app.agents.memory.email_processor.PLATFORM_CONFIG"
_PATCH_EXTRACT_USER = "app.agents.memory.email_processor.extract_username_with_llm"
_PATCH_VALIDATE = "app.agents.memory.email_processor.validate_username"
_PATCH_BUILD_URL = "app.agents.memory.email_processor.build_profile_url"
_PATCH_CRAWL = "app.agents.memory.email_processor.crawl_profile_url"
_PATCH_STORE_PROFILE = "app.agents.memory.email_processor.store_single_profile"
_PATCH_MEMORY_SERVICE = "app.agents.memory.email_processor.memory_service"
_PATCH_SEARCH_PARALLEL = "app.agents.memory.email_processor._search_platform_emails_parallel"


def _semaphore() -> asyncio.Semaphore:
    return asyncio.Semaphore(20)


async def _drain(task: object) -> None:
    """Cancel-and-await a fire-and-forget asyncio task so no warnings leak."""
    if isinstance(task, asyncio.Task):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - cleanup only
            pass


# ---------------------------------------------------------------------------
# _search_platform_emails
# ---------------------------------------------------------------------------


class TestSearchPlatformEmails:
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_messages_and_passes_query_through(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = {"messages": [{"id": "1"}, {"id": "2"}]}

        result = await _search_platform_emails(USER_ID, "github", "from:github.com")

        assert result == [{"id": "1"}, {"id": "2"}]
        # Default max_results is 10 — kills a mutation of that literal.
        mock_search.assert_awaited_once_with(
            user_id=USER_ID, query="from:github.com", max_results=10
        )

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_explicit_max_results_is_forwarded(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = {"messages": [{"id": "1"}]}

        await _search_platform_emails(USER_ID, "github", "q", max_results=25)

        assert mock_search.await_args.kwargs["max_results"] == 25

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_missing_messages_key_returns_empty(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = {}

        result = await _search_platform_emails(USER_ID, "twitter", "from:twitter.com")

        assert result == []

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_exception_is_swallowed_to_empty_list(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = RuntimeError("API error")

        result = await _search_platform_emails(USER_ID, "github", "from:github.com")

        assert result == []


# ---------------------------------------------------------------------------
# _search_platform_emails_parallel
# ---------------------------------------------------------------------------


class TestSearchPlatformEmailsParallel:
    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "github": {"sender_domains": ["github.com", "notifications.github.com"]},
            "twitter": {"sender_domains": ["twitter.com", "x.com"]},
        },
    )
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_builds_or_query_per_platform_and_maps_results(
        self, mock_search: AsyncMock
    ) -> None:
        # Map by query so assertions do not depend on gather scheduling order.
        responses = {
            "from:github.com OR from:notifications.github.com": {"messages": [{"id": "g1"}]},
            "from:twitter.com OR from:x.com": {"messages": [{"id": "t1"}, {"id": "t2"}]},
        }

        async def fake_search(**kwargs: Any) -> dict:
            return responses[kwargs["query"]]

        mock_search.side_effect = fake_search

        result = await _search_platform_emails_parallel(USER_ID)

        assert result == {"github": [{"id": "g1"}], "twitter": [{"id": "t1"}, {"id": "t2"}]}

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"sender_domains": ["github.com"]}},
    )
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_platform_exception_maps_to_empty_list(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = RuntimeError("fail")

        result = await _search_platform_emails_parallel(USER_ID)

        assert result == {"github": []}

    @patch(_PATCH_PLATFORM_CONFIG, {})
    async def test_empty_config_returns_empty_mapping(self) -> None:
        result = await _search_platform_emails_parallel(USER_ID)

        assert result == {}


# ---------------------------------------------------------------------------
# _process_single_platform
# ---------------------------------------------------------------------------


class TestProcessSinglePlatform:
    @patch(_PATCH_STORE_PROFILE, new_callable=AsyncMock)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_success_stores_content_and_returns_profile(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_store: AsyncMock,
    ) -> None:
        mock_crawl.return_value = {"content": "Profile content", "error": None}
        crawled: set[str] = set()

        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], _semaphore(), "Test User", crawled, async_mode=True
        )

        assert result["success"] is True
        assert result["platform"] == "github"
        assert result["url"] == "https://github.com/testuser"
        assert isinstance(result["discovery_task"], asyncio.Task)

        # store receives the real crawled content + URL + async_mode flag.
        store_kwargs = mock_store.await_args
        assert store_kwargs.args[2] == "https://github.com/testuser"
        assert store_kwargs.args[3] == "Profile content"
        assert store_kwargs.kwargs["async_mode"] is True

        await _drain(result["discovery_task"])

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"regex_pattern": r"^[a-zA-Z0-9]+$"}},
    )
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_VALIDATE, return_value=False)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="bad!")
    async def test_invalid_username_short_circuits_before_crawl(
        self, mock_extract: AsyncMock, mock_validate: MagicMock, mock_crawl: AsyncMock
    ) -> None:
        result = await _process_single_platform(USER_ID, "github", [{"id": "1"}], _semaphore())

        assert result == {"error": "Invalid username 'bad!' for github"}
        mock_crawl.assert_not_awaited()

    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value=None)
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_unbuildable_url_short_circuits_before_crawl(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        result = await _process_single_platform(USER_ID, "github", [{"id": "1"}], _semaphore())

        assert result == {"error": "Could not build URL for github"}
        mock_crawl.assert_not_awaited()

    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_duplicate_url_returns_duplicate_without_crawling(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        crawled: set[str] = {"https://github.com/testuser"}

        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], _semaphore(), crawled_urls=crawled
        )

        assert result == {"error": "duplicate", "url": "https://github.com/testuser"}
        mock_crawl.assert_not_awaited()

    @patch(_PATCH_STORE_PROFILE, new_callable=AsyncMock)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_url_marked_crawled_before_crawl(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_store: AsyncMock,
    ) -> None:
        seen: list[set[str]] = []

        async def record_then_fail(*_a: Any, **_k: Any) -> dict:
            # The set must already contain the URL by the time crawl runs.
            seen.append(set(crawled))
            return {"content": None, "error": "fail"}

        mock_crawl.side_effect = record_then_fail
        crawled: set[str] = set()

        await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], _semaphore(), crawled_urls=crawled
        )

        assert seen == [{"https://github.com/testuser"}]
        assert "https://github.com/testuser" in crawled

    @patch(_PATCH_STORE_PROFILE, new_callable=AsyncMock)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_empty_content_without_error_skips_store(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_store: AsyncMock,
    ) -> None:
        # content falsy triggers the failure branch (left side of the `or`). The error key
        # is present-but-None, so `.get("error", "Crawl failed")` returns None, not the default.
        mock_crawl.return_value = {"content": None, "error": None}

        result = await _process_single_platform(USER_ID, "github", [{"id": "1"}], _semaphore())

        assert result == {"error": None}
        mock_store.assert_not_awaited()

    @patch(_PATCH_STORE_PROFILE, new_callable=AsyncMock)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_missing_error_key_uses_crawl_failed_default(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_store: AsyncMock,
    ) -> None:
        # No "error" key at all + falsy content -> the "Crawl failed" default is returned.
        mock_crawl.return_value = {"content": None}

        result = await _process_single_platform(USER_ID, "github", [{"id": "1"}], _semaphore())

        assert result == {"error": "Crawl failed"}
        mock_store.assert_not_awaited()

    @patch(_PATCH_STORE_PROFILE, new_callable=AsyncMock)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_error_set_with_content_still_fails(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_store: AsyncMock,
    ) -> None:
        # content present but error set -> still a failure (right side of the `or`).
        mock_crawl.return_value = {"content": "data", "error": "timeout"}

        result = await _process_single_platform(USER_ID, "github", [{"id": "1"}], _semaphore())

        assert result == {"error": "timeout"}
        mock_store.assert_not_awaited()

    @patch(_PATCH_STORE_PROFILE, new_callable=AsyncMock)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_async_mode_defaults_to_false(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_store: AsyncMock,
    ) -> None:
        mock_crawl.return_value = {"content": "Profile content", "error": None}

        # async_mode omitted -> store must receive the default False (sync onboarding store).
        result = await _process_single_platform(USER_ID, "github", [{"id": "1"}], _semaphore())

        assert mock_store.await_args.kwargs["async_mode"] is False
        await _drain(result.get("discovery_task"))

    @patch(
        _PATCH_EXTRACT_USER,
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM down"),
    )
    async def test_exception_returns_error_string(self, mock_extract: AsyncMock) -> None:
        result = await _process_single_platform(USER_ID, "github", [{"id": "1"}], _semaphore())

        assert result == {"error": "LLM down"}


# ---------------------------------------------------------------------------
# process_gmail_to_memory
# ---------------------------------------------------------------------------


def _user_doc(**overrides: Any) -> dict:
    doc = {
        "_id": USER_ID,
        "email_memory_processed": False,
        "name": "Test User",
        "email": "test@test.com",
    }
    doc.update(overrides)
    return doc


class TestProcessGmailToMemory:
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_already_processed_returns_early_without_searching(
        self, mock_users: MagicMock, mock_search: AsyncMock
    ) -> None:
        mock_users.find_one = AsyncMock(return_value=_user_doc(email_memory_processed=True))

        result = await process_gmail_to_memory(USER_ID)

        assert result == {
            "total": 0,
            "successful": 0,
            "already_processed": True,
            "processing_complete": True,
        }
        mock_search.assert_not_awaited()

    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_successful_run_returns_aggregate_stats(
        self,
        mock_users: MagicMock,
        mock_search: AsyncMock,
        mock_process: MagicMock,
        mock_store: AsyncMock,
        mock_mark: AsyncMock,
        mock_profiles: AsyncMock,
    ) -> None:
        mock_users.find_one = AsyncMock(return_value=_user_doc())
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {"messages": [{"id": "1"}, {"id": "2"}], "nextPageToken": None}
        # 1 parsed, 3 reported failed/skipped by the parser.
        mock_process.return_value = ([{"role": "user", "content": "email1"}], 3)
        mock_profiles.return_value = {
            "profiles_stored": 2,
            "extracted_profiles": [{"platform": "github", "url": "u"}],
        }

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 2
        assert result["successful"] == 1
        assert result["failed"] == 3
        assert result["profiles_stored"] == 2
        assert result["processing_complete"] is True
        assert result["extracted_profiles"] == [{"platform": "github", "url": "u"}]
        # marked with parsed (1) + profiles_stored (2) = 3
        assert mock_mark.await_args.args == (USER_ID, 3)
        # The user is looked up and the scan timestamp persisted by _id.
        assert mock_users.find_one.await_args.args[0] == {"_id": ObjectId(USER_ID)}
        update_filter, update_doc = mock_users.update_one.await_args.args
        assert update_filter == {"_id": ObjectId(USER_ID)}
        assert "integration_scan_states.gmail.last_scan_timestamp" in update_doc["$set"]
        # Storage is attributed with the user's real name + email from the doc,
        # and dispatched in async mode during onboarding.
        store_args = mock_store.await_args.args
        assert store_args[0] == USER_ID
        assert store_args[2] == "Test User"
        assert store_args[3] == "test@test.com"
        assert mock_store.await_args.kwargs["async_mode"] is True
        # The first batch requests exactly BATCH_SIZE (50) results, not MAX_RESULTS.
        assert mock_search.await_args_list[0].kwargs["max_results"] == 50

    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_user_doc_without_processed_flag_is_processed(
        self,
        mock_users: MagicMock,
        mock_search: AsyncMock,
        mock_process: MagicMock,
        mock_store: AsyncMock,
        mock_mark: AsyncMock,
        mock_profiles: AsyncMock,
    ) -> None:
        # No "email_memory_processed" key at all -> treated as not processed (default False).
        mock_users.find_one = AsyncMock(
            return_value={"_id": USER_ID, "name": "Test User", "email": "test@test.com"}
        )
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {"messages": [{"id": "1"}], "nextPageToken": None}
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_profiles.return_value = {"profiles_stored": 0, "extracted_profiles": []}

        result = await process_gmail_to_memory(USER_ID)

        assert "already_processed" not in result
        assert result["successful"] == 1
        mock_search.assert_awaited()

    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_pagination_follows_next_page_token(
        self,
        mock_users: MagicMock,
        mock_search: AsyncMock,
        mock_process: MagicMock,
        mock_store: AsyncMock,
        mock_mark: AsyncMock,
        mock_profiles: AsyncMock,
    ) -> None:
        mock_users.find_one = AsyncMock(return_value=_user_doc())
        mock_users.update_one = AsyncMock()
        # First batch carries a page token; second batch terminates the loop.
        mock_search.side_effect = [
            {"messages": [{"id": "1"}], "nextPageToken": "PAGE2"},
            {"messages": [{"id": "2"}], "nextPageToken": None},
        ]
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_profiles.return_value = {"profiles_stored": 0, "extracted_profiles": []}

        result = await process_gmail_to_memory(USER_ID)

        # Both batches fetched (2 messages total) -> two search calls, second paginated.
        assert result["total"] == 2
        assert mock_search.await_count == 2
        assert mock_search.await_args_list[1].kwargs["page_token"] == "PAGE2"

    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_no_emails_marks_incomplete_and_skips_mark_complete(
        self,
        mock_users: MagicMock,
        mock_search: AsyncMock,
        mock_process: MagicMock,
        mock_mark: AsyncMock,
        mock_profiles: AsyncMock,
    ) -> None:
        mock_users.find_one = AsyncMock(return_value=_user_doc())
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {"messages": []}
        mock_profiles.return_value = {"profiles_stored": 0, "extracted_profiles": []}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 0
        assert result["successful"] == 0
        assert result["processing_complete"] is False
        # mark-complete is gated on processing_complete (parsed > 0)
        mock_mark.assert_not_awaited()
        # timestamp is still persisted even with no emails
        mock_users.update_one.assert_awaited_once()

    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_scan_timestamp_appends_after_clause_to_query(
        self,
        mock_users: MagicMock,
        mock_search: AsyncMock,
        mock_process: MagicMock,
        mock_store: AsyncMock,
        mock_mark: AsyncMock,
        mock_profiles: AsyncMock,
    ) -> None:
        ts = datetime(2025, 1, 1, tzinfo=UTC)
        epoch = int(ts.timestamp())
        mock_users.find_one = AsyncMock(
            return_value=_user_doc(integration_scan_states={"gmail": {"last_scan_timestamp": ts}})
        )
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {"messages": []}
        mock_profiles.return_value = {"profiles_stored": 0, "extracted_profiles": []}

        await process_gmail_to_memory(USER_ID)

        # EMAIL_QUERY is "in:inbox"; timestamp appends "after:<epoch>".
        assert mock_search.await_args.kwargs["query"] == f"in:inbox after:{epoch}"

    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_no_timestamp_uses_plain_query(
        self,
        mock_users: MagicMock,
        mock_search: AsyncMock,
        mock_process: MagicMock,
        mock_store: AsyncMock,
        mock_mark: AsyncMock,
        mock_profiles: AsyncMock,
    ) -> None:
        mock_users.find_one = AsyncMock(return_value=_user_doc())
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {"messages": []}
        mock_profiles.return_value = {"profiles_stored": 0, "extracted_profiles": []}

        await process_gmail_to_memory(USER_ID)

        assert mock_search.await_args.kwargs["query"] == "in:inbox"

    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_profile_track_failure_does_not_block_completion(
        self,
        mock_users: MagicMock,
        mock_search: AsyncMock,
        mock_process: MagicMock,
        mock_store: AsyncMock,
        mock_mark: AsyncMock,
        mock_profiles: AsyncMock,
    ) -> None:
        mock_users.find_one = AsyncMock(return_value=_user_doc())
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {"messages": [{"id": "1"}], "nextPageToken": None}
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_profiles.side_effect = RuntimeError("profile crash")

        result = await process_gmail_to_memory(USER_ID)

        assert result["successful"] == 1
        assert result["profiles_stored"] == 0
        assert result["processing_complete"] is True
        # parsed(1) + profiles_stored(0) = 1
        assert mock_mark.await_args.args == (USER_ID, 1)

    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock, side_effect=RuntimeError("mark fail"))
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_mark_complete_failure_is_swallowed(
        self,
        mock_users: MagicMock,
        mock_search: AsyncMock,
        mock_process: MagicMock,
        mock_store: AsyncMock,
        mock_mark: AsyncMock,
        mock_profiles: AsyncMock,
    ) -> None:
        mock_users.find_one = AsyncMock(return_value=_user_doc())
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {"messages": [{"id": "1"}], "nextPageToken": None}
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_profiles.return_value = {"profiles_stored": 0, "extracted_profiles": []}

        result = await process_gmail_to_memory(USER_ID)

        # Exception in mark-complete must not propagate; timestamp write still happens.
        assert result["processing_complete"] is True
        mock_users.update_one.assert_awaited_once()

    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_profile_result_without_count_defaults_to_zero(
        self,
        mock_users: MagicMock,
        mock_search: AsyncMock,
        mock_process: MagicMock,
        mock_store: AsyncMock,
        mock_mark: AsyncMock,
        mock_profiles: AsyncMock,
    ) -> None:
        mock_users.find_one = AsyncMock(return_value=_user_doc())
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {"messages": [{"id": "1"}], "nextPageToken": None}
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        # Profile track returns a dict missing "profiles_stored" -> defaults to 0.
        mock_profiles.return_value = {}

        result = await process_gmail_to_memory(USER_ID)

        assert result["profiles_stored"] == 0
        assert result["extracted_profiles"] == []
        # mark called with parsed(1) + profiles_stored(0) = 1
        assert mock_mark.await_args.args == (USER_ID, 1)


# ---------------------------------------------------------------------------
# _extract_profiles_from_parallel_searches
# ---------------------------------------------------------------------------


class TestExtractProfilesFromParallelSearches:
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_no_platform_emails_returns_zero(
        self, mock_users: MagicMock, mock_parallel: AsyncMock
    ) -> None:
        mock_users.find_one = AsyncMock(return_value={"name": "Test"})
        mock_parallel.return_value = {"github": [], "twitter": []}

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {"profiles_stored": 0}

    @patch(
        "app.agents.memory.email_processor._process_single_platform",
        new_callable=AsyncMock,
    )
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_successful_platform_is_counted_and_recorded(
        self,
        mock_users: MagicMock,
        mock_parallel: AsyncMock,
        mock_single: AsyncMock,
    ) -> None:
        mock_users.find_one = AsyncMock(return_value={"name": "Alice"})
        mock_parallel.return_value = {"github": [{"id": "1"}]}
        # No discovery_task key -> no discovery gather; success counts.
        mock_single.return_value = {
            "success": True,
            "platform": "github",
            "url": "https://github.com/testuser",
        }

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result["profiles_stored"] == 1
        assert result["extracted_profiles"] == [
            {"platform": "github", "url": "https://github.com/testuser"}
        ]
        # platform, emails, the resolved user_name, and async_mode are all forwarded.
        call = mock_single.await_args
        assert call.args[1] == "github"
        assert call.args[2] == [{"id": "1"}]
        assert call.args[4] == "Alice"
        assert call.kwargs["async_mode"] is True

    @patch(
        "app.agents.memory.email_processor._process_single_platform",
        new_callable=AsyncMock,
    )
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_platform_task_exception_is_isolated(
        self,
        mock_users: MagicMock,
        mock_parallel: AsyncMock,
        mock_single: AsyncMock,
    ) -> None:
        mock_users.find_one = AsyncMock(return_value={"name": "Test"})
        mock_parallel.return_value = {"github": [{"id": "1"}], "twitter": [{"id": "2"}]}
        # First platform raises (must be caught per-task), second succeeds.
        mock_single.side_effect = [
            RuntimeError("platform boom"),
            {"success": True, "platform": "twitter", "url": "https://x.com/u"},
        ]

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        # The raised task is isolated; only the successful platform is counted.
        assert result["profiles_stored"] == 1
        assert result["extracted_profiles"] == [{"platform": "twitter", "url": "https://x.com/u"}]

    @patch(
        "app.agents.memory.email_processor._process_single_platform",
        new_callable=AsyncMock,
    )
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_error_result_is_not_counted(
        self,
        mock_users: MagicMock,
        mock_parallel: AsyncMock,
        mock_single: AsyncMock,
    ) -> None:
        mock_users.find_one = AsyncMock(return_value={"name": "Test"})
        # Two platforms: one succeeds, one returns an error dict. Only the success counts.
        # An `and -> or` mutation would (mis)count the error dict too.
        mock_parallel.return_value = {"github": [{"id": "1"}], "twitter": [{"id": "2"}]}
        mock_single.side_effect = [
            {"success": True, "platform": "github", "url": "https://github.com/u"},
            {"error": "Invalid username"},
        ]

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result["profiles_stored"] == 1
        assert result["extracted_profiles"] == [
            {"platform": "github", "url": "https://github.com/u"}
        ]

    @patch(_PATCH_USERS)
    async def test_top_level_exception_returns_zero(self, mock_users: MagicMock) -> None:
        mock_users.find_one = AsyncMock(side_effect=RuntimeError("db down"))

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {"profiles_stored": 0, "extracted_profiles": []}


# ---------------------------------------------------------------------------
# _discover_and_store_linked_profiles
# ---------------------------------------------------------------------------

_DISCOVERY_CONFIG = {
    "twitter": {
        "sender_domains": ["twitter.com"],
        "url_template": "https://x.com/{username}",
        "regex_pattern": r"[a-zA-Z0-9_]{1,15}",
    },
    "github": {
        "sender_domains": ["github.com"],
        "url_template": "https://github.com/{username}",
        "regex_pattern": r"[a-zA-Z0-9-]{1,39}",
    },
}


class TestDiscoverAndStoreLinkedProfiles:
    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_SERVICE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/johndoe")
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_foreign_link_is_crawled_stored_and_counted(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        mock_crawl.return_value = {"content": "profile data", "error": None}
        mock_memory.store_memory_batch = AsyncMock(return_value=True)

        content = "Check out my github: https://github.com/johndoe"
        count = await _discover_and_store_linked_profiles(USER_ID, content, "twitter", _semaphore())

        assert count == 1
        store_call = mock_memory.store_memory_batch.await_args.kwargs
        # The stored message is the exact template: header line with platform+url, then content.
        stored_messages = store_call["messages"]
        assert stored_messages == [
            {
                "role": "user",
                "content": ("User's github profile: https://github.com/johndoe\n\nprofile data\n"),
            }
        ]
        # Metadata records source platform, type, batch size, and a discovery timestamp.
        assert store_call["metadata"]["type"] == "social_profile"
        assert store_call["metadata"]["source"] == "discovered_from_twitter"
        assert store_call["metadata"]["batch_size"] == 1
        assert "discovered_at" in store_call["metadata"]
        assert store_call["user_id"] == USER_ID
        assert store_call["async_mode"] is True

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_SERVICE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/johndoe")
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_discovered_crawl_with_error_is_not_stored(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        # content present but error set -> excluded by `not result.get("error")`.
        mock_crawl.return_value = {"content": "data", "error": "blocked"}
        mock_memory.store_memory_batch = AsyncMock(return_value=True)

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", _semaphore()
        )

        assert count == 0
        mock_memory.store_memory_batch.assert_not_awaited()

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_SERVICE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/johndoe")
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_discovered_crawl_raising_is_isolated(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        # A raising crawl must be caught per-task (return_exceptions=True) and excluded,
        # not propagate out of the gather.
        mock_crawl.side_effect = RuntimeError("crawl exploded")
        mock_memory.store_memory_batch = AsyncMock(return_value=True)

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", _semaphore()
        )

        assert count == 0
        mock_memory.store_memory_batch.assert_not_awaited()

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    async def test_no_links_found_returns_zero(self) -> None:
        count = await _discover_and_store_linked_profiles(
            USER_ID, "No social links here.", "twitter", _semaphore()
        )

        assert count == 0

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    async def test_same_platform_link_is_skipped(self, mock_crawl: AsyncMock) -> None:
        # x.com is the twitter url_template domain; a twitter link in twitter content
        # must be skipped (source platform), so nothing is crawled.
        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://x.com/otheruser", "twitter", _semaphore()
        )

        assert count == 0
        mock_crawl.assert_not_awaited()

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "github": {
                "sender_domains": ["github.com"],
                "url_template": "https://github.com/{username}",
                "regex_pattern": r"[a-zA-Z0-9-]{1,39}",
            },
            # Shares the github.com domain with the source platform.
            "gist": {
                "sender_domains": ["gist.github.com"],
                "url_template": "https://github.com/{username}",
                "regex_pattern": r"[a-zA-Z0-9-]{1,39}",
            },
        },
    )
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/johndoe")
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_same_domain_different_platform_is_skipped(
        self, mock_validate: MagicMock, mock_build: MagicMock, mock_crawl: AsyncMock
    ) -> None:
        # source=github (domain github.com); "gist" shares github.com -> must be skipped
        # via the source-domain comparison, so nothing is crawled.
        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "github", _semaphore()
        )

        assert count == 0
        mock_crawl.assert_not_awaited()

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/johndoe")
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_already_crawled_url_is_skipped(
        self, mock_validate: MagicMock, mock_build: MagicMock, mock_crawl: AsyncMock
    ) -> None:
        crawled: set[str] = {"https://github.com/johndoe"}

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", _semaphore(), crawled_urls=crawled
        )

        assert count == 0
        mock_crawl.assert_not_awaited()

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_SERVICE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/johndoe")
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_crawl_without_content_is_not_stored(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        mock_crawl.return_value = {"content": None, "error": "timeout"}
        mock_memory.store_memory_batch = AsyncMock(return_value=True)

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", _semaphore()
        )

        assert count == 0
        mock_memory.store_memory_batch.assert_not_awaited()

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_SERVICE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/johndoe")
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_store_batch_failure_returns_zero(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.store_memory_batch = AsyncMock(return_value=False)

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", _semaphore()
        )

        # store reached but reported failure -> 0
        assert count == 0
        mock_memory.store_memory_batch.assert_awaited_once()

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_exception_returns_zero(self, mock_validate: MagicMock) -> None:
        # build_profile_url raising mid-scan must be swallowed into a 0 count.
        with patch(_PATCH_BUILD_URL, side_effect=RuntimeError("boom")):
            count = await _discover_and_store_linked_profiles(
                USER_ID, "https://github.com/johndoe", "twitter", _semaphore()
            )

        assert count == 0
