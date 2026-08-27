"""Unit tests for app.agents.memory.email_processor."""

import asyncio
import contextlib
from datetime import UTC, datetime
import itertools
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.agents.llm.exceptions import LLMNotConfiguredError
from app.agents.memory.email_processor import (
    OnboardingFetchOptions,
    _await_discovery_tasks,
    _collect_platform_results,
    _collect_storage_results,
    _crawl_and_store_discovered,
    _discover_and_store_linked_profiles,
    _extract_linked_profile_links,
    _extract_profiles_from_parallel_searches,
    _latest_gmail_scan_timestamp,
    _mark_processing_complete,
    _process_single_platform,
    _search_platform_emails,
    _search_platform_emails_parallel,
    _source_domain_for,
    _StepTimer,
    fetch_emails_for_onboarding,
    process_gmail_to_memory,
)
from app.constants.log_tags import LogTag
from app.constants.memory import MemorySourceType
from app.models.mail_models import GmailMessagesResponse, GmailToolResult
from app.models.user_models import UserDocument
from app.services.onboarding.social_profile_service import (
    extract_social_profiles_from_emails,
)

# Valid 24-char hex string for ObjectId compatibility
USER_ID = "507f1f77bcf86cd799439011"

# ---------------------------------------------------------------------------
# Shared patch targets
# ---------------------------------------------------------------------------
_EMAIL_PROCESSOR_MODULE = "app.agents.memory.email_processor"
_PATCH_USERS = "app.agents.memory.email_processor.user_repository"
_PATCH_SEARCH = "app.agents.memory.email_processor.search_messages"
_PATCH_EMIT = "app.agents.memory.email_processor.emit_progress"
_PATCH_PROCESS = "app.agents.memory.email_processor.process_email_content"
_PATCH_STORE_EMAILS = "app.agents.memory.email_processor.store_emails_to_memory"
_PATCH_MARK_COMPLETE = "app.agents.memory.email_processor.mark_email_processing_complete"
_PATCH_POST_ONBOARD = "app.agents.memory.email_processor.process_post_onboarding_personalization"
_PATCH_EXTRACT_PROFILES = (
    "app.agents.memory.email_processor._extract_profiles_from_parallel_searches"
)
_PATCH_PLATFORM_CONFIG = "app.agents.memory.email_processor.PLATFORM_CONFIG"
_PATCH_EXTRACT_USER = "app.agents.memory.email_processor.extract_username_with_llm"
_PATCH_VALIDATE = "app.agents.memory.email_processor.validate_username"
_PATCH_BUILD_URL = "app.agents.memory.email_processor.build_profile_url"
_PATCH_CRAWL = "app.agents.memory.email_processor.crawl_profile_url"
_PATCH_CRAWL_BATCH = "app.agents.memory.email_processor.crawl_profile_urls_batch"
_PATCH_STORE_PROFILE = "app.agents.memory.email_processor.store_single_profile"
_PATCH_MEMORY_ENGINE = "app.agents.memory.email_processor.memory_engine"
_PATCH_SEARCH_PARALLEL = "app.agents.memory.email_processor._search_platform_emails_parallel"
_PATCH_PROCESS_SINGLE = "app.agents.memory.email_processor._process_single_platform"
_PATCH_AWAIT_DISCOVERY = "app.agents.memory.email_processor._await_discovery_tasks"
_PATCH_COLLECT_STORAGE = "app.agents.memory.email_processor._collect_storage_results"
_PATCH_PROFILE_COLLECTION = "app.agents.memory.email_processor._collect_profile_extraction"
_PATCH_MARK_PROC = "app.agents.memory.email_processor._mark_processing_complete"
_PATCH_EXTRACT_LINKS = "app.agents.memory.email_processor._extract_linked_profile_links"
_PATCH_CRAWL_DISCOVERED = "app.agents.memory.email_processor._crawl_and_store_discovered"
_PATCH_LOG = "app.agents.memory.email_processor.log"

_EXTRACTION_HINTS_TWITTER = (
    "These are the user's own social profiles, discovered from their "
    "twitter emails. Extract durable facts about the user: "
    "handles, bio, role, projects, interests, and location."
)


# ---------------------------------------------------------------------------
# _search_platform_emails
# ---------------------------------------------------------------------------


class TestSearchPlatformEmails:
    """Tests for _search_platform_emails."""

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_messages(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}, {"id": "2"}])
        result = await _search_platform_emails(USER_ID, "github", "from:github.com")
        assert len(result) == 2
        mock_search.assert_awaited_once_with(
            user_id=USER_ID, query="from:github.com", max_results=10
        )

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_empty_on_no_messages(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[])
        result = await _search_platform_emails(USER_ID, "github", "from:github.com")
        assert result == []

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_empty_on_missing_messages_key(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[])
        result = await _search_platform_emails(USER_ID, "twitter", "from:twitter.com")
        assert result == []

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_empty_on_exception(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = RuntimeError("API error")
        result = await _search_platform_emails(USER_ID, "github", "from:github.com")
        assert result == []

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_respects_max_results(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        await _search_platform_emails(USER_ID, "github", "q", max_results=10)
        mock_search.assert_awaited_once_with(user_id=USER_ID, query="q", max_results=10)


# ---------------------------------------------------------------------------
# _search_platform_emails_parallel
# ---------------------------------------------------------------------------


class TestSearchPlatformEmailsParallel:
    """Tests for _search_platform_emails_parallel."""

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "github": {"sender_domains": ["github.com", "notifications.github.com"]},
            "twitter": {"sender_domains": ["twitter.com", "x.com"]},
        },
    )
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_parallel_search_aggregates_results(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = [
            GmailMessagesResponse(messages=[{"id": "g1"}]),
            GmailMessagesResponse(messages=[{"id": "t1"}, {"id": "t2"}]),
        ]
        result = await _search_platform_emails_parallel(USER_ID)
        assert "github" in result
        assert "twitter" in result
        assert len(result["github"]) == 1
        assert len(result["twitter"]) == 2

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"sender_domains": ["github.com"]}},
    )
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_parallel_search_handles_exception(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = RuntimeError("fail")
        result = await _search_platform_emails_parallel(USER_ID)
        # Exception results in empty list for that platform
        assert result["github"] == []

    @patch(_PATCH_PLATFORM_CONFIG, {})
    async def test_parallel_search_empty_config(self) -> None:
        result = await _search_platform_emails_parallel(USER_ID)
        assert result == {}


# ---------------------------------------------------------------------------
# _process_single_platform
# ---------------------------------------------------------------------------


class TestProcessSinglePlatform:
    """Tests for _process_single_platform."""

    @patch(_PATCH_STORE_PROFILE, new_callable=AsyncMock)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_success_path(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_store: AsyncMock,
    ) -> None:
        mock_crawl.return_value = {"content": "Profile content", "error": None}
        emails: list[dict[str, Any]] = [{"id": "1"}]

        result = await _process_single_platform(
            USER_ID, "github", emails, asyncio.Semaphore(), "Test User"
        )

        assert result["success"] is True
        assert result["platform"] == "github"
        assert result["url"] == "https://github.com/testuser"
        assert "discovery_task" in result
        mock_store.assert_awaited_once()

        # Clean up the discovery task
        if "discovery_task" in result:
            result["discovery_task"].cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await result["discovery_task"]

    @patch(_PATCH_VALIDATE, return_value=False)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="bad!")
    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"regex_pattern": r"^[a-zA-Z0-9]+$"}},
    )
    async def test_invalid_username(
        self, mock_extract: AsyncMock, mock_validate: MagicMock
    ) -> None:
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert "error" in result
        assert "Invalid username" in result["error"]

    @patch(_PATCH_BUILD_URL, return_value=None)
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_no_profile_url(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert "error" in result
        assert "Could not build URL" in result["error"]

    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_duplicate_url_skipped(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        crawled_urls: set[str] = {"https://github.com/testuser"}
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore(), crawled_urls=crawled_urls
        )
        assert result["error"] == "duplicate"

    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_crawl_failure(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_crawl.return_value = {"content": None, "error": "timeout"}
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert "error" in result
        assert result["error"] == "timeout"

    @patch(
        _PATCH_EXTRACT_USER,
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM down"),
    )
    async def test_exception_returns_error(self, mock_extract: AsyncMock) -> None:
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert "error" in result
        assert "LLM down" in result["error"]

    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_adds_url_to_crawled_set(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        """URL should be added to crawled_urls before crawling."""
        crawled_urls: set[str] = set()

        with patch(_PATCH_CRAWL, new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = {"content": None, "error": "fail"}
            await _process_single_platform(
                USER_ID, "github", [{"id": "1"}], asyncio.Semaphore(), crawled_urls=crawled_urls
            )

        assert "https://github.com/testuser" in crawled_urls


# ---------------------------------------------------------------------------
# process_gmail_to_memory
# ---------------------------------------------------------------------------


class TestProcessGmailToMemory:
    """Tests for the main orchestrator function."""

    @patch(_PATCH_USERS)
    async def test_already_processed_user_returns_early(self, mock_users: MagicMock) -> None:
        mock_users.get = AsyncMock(
            return_value=UserDocument(id=USER_ID, email_memory_processed=True, name="Test")
        )
        result = await process_gmail_to_memory(USER_ID)
        assert result["already_processed"] is True
        assert result["total"] == 0

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_processes_emails_successfully(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(
            return_value=UserDocument(
                id=USER_ID,
                email_memory_processed=False,
                name="Test User",
                email="test@test.com",
            )
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()

        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}, {"id": "2"}])
        mock_process.return_value = ([{"role": "user", "content": "email1"}], 0)
        mock_store.return_value = None
        mock_profiles.return_value = {"profiles_stored": 2}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 2
        assert result["successful"] == 1
        assert result["profiles_stored"] == 2
        assert result["processing_complete"] is True
        mock_mark.assert_awaited_once()

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_handles_no_emails(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(
            return_value=UserDocument(
                id=USER_ID, email_memory_processed=False, name="Test", email="t@t.com"
            )
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[])
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 0
        assert result["successful"] == 0
        assert result["processing_complete"] is False

    @patch(_PATCH_USERS)
    async def test_handles_null_user(self, mock_users: MagicMock) -> None:
        """If user not found in DB, should proceed without crashing."""
        mock_users.get = AsyncMock(return_value=None)
        mock_users.set_gmail_scan_timestamp = AsyncMock()

        with (
            patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search,
            patch(_PATCH_PROCESS, return_value=([], 0)),
            patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock),
            patch(
                _PATCH_EXTRACT_PROFILES,
                new_callable=AsyncMock,
                return_value={"profiles_stored": 0},
            ),
        ):
            mock_search.return_value = GmailMessagesResponse(messages=[])
            result = await process_gmail_to_memory(USER_ID)
            assert result["total"] == 0

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_appends_timestamp_query_when_available(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        ts = datetime(2025, 1, 1, tzinfo=UTC)
        mock_users.get = AsyncMock(
            return_value=UserDocument(
                id=USER_ID,
                email_memory_processed=False,
                name="Test",
                email="t@t.com",
                integration_scan_states={"gmail": {"last_scan_timestamp": ts}},
            )
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[])
        mock_profiles.return_value = {"profiles_stored": 0}

        await process_gmail_to_memory(USER_ID)

        # Should have called with after: timestamp
        call_args = mock_search.call_args
        assert "after:" in call_args.kwargs.get("query", call_args[1].get("query", ""))

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_profile_extraction_failure_does_not_block(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        """Profile extraction failure should not block completion."""
        mock_users.get = AsyncMock(
            return_value=UserDocument(
                id=USER_ID, email_memory_processed=False, name="Test", email="t@t.com"
            )
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_store.return_value = None
        mock_profiles.side_effect = RuntimeError("profile crash")

        result = await process_gmail_to_memory(USER_ID)

        assert result["successful"] == 1
        assert result["profiles_stored"] == 0

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(
        _PATCH_MARK_COMPLETE,
        new_callable=AsyncMock,
        side_effect=RuntimeError("mark fail"),
    )
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_mark_complete_failure_continues(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(
            return_value=UserDocument(
                id=USER_ID, email_memory_processed=False, name="Test", email="t@t.com"
            )
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_store.return_value = None
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        # mark_email_processing_complete raised, but the function should
        # continue and still return a complete result
        assert result["processing_complete"] is True


# ---------------------------------------------------------------------------
# _extract_profiles_from_parallel_searches
# ---------------------------------------------------------------------------


class TestExtractProfilesFromParallelSearches:
    """Tests for _extract_profiles_from_parallel_searches."""

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    async def test_returns_zero_when_no_platform_emails(
        self, mock_parallel: AsyncMock, mock_users: MagicMock
    ) -> None:
        mock_users.get = AsyncMock(return_value=UserDocument(name="Test"))
        mock_parallel.return_value = {"github": [], "twitter": []}

        result = await _extract_profiles_from_parallel_searches(USER_ID)
        assert result["profiles_stored"] == 0

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    async def test_handles_exception_gracefully(
        self, mock_parallel: AsyncMock, mock_users: MagicMock
    ) -> None:
        mock_users.get = AsyncMock(side_effect=RuntimeError("db down"))

        result = await _extract_profiles_from_parallel_searches(USER_ID)
        assert result["profiles_stored"] == 0


# ---------------------------------------------------------------------------
# _discover_and_store_linked_profiles
# ---------------------------------------------------------------------------


class TestDiscoverAndStoreLinkedProfiles:
    """Tests for _discover_and_store_linked_profiles."""

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
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
        },
    )
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_discovers_linked_profile(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        # crawl_profile_url returns a single dict (not a list)
        mock_crawl.return_value = {"content": "profile data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        content = "Check out my github: https://github.com/johndoe"

        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", asyncio.Semaphore()
        )
        assert count >= 1

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "twitter": {
                "sender_domains": ["twitter.com"],
                "url_template": "https://x.com/{username}",
                "regex_pattern": r"[a-zA-Z0-9_]{1,15}",
            },
        },
    )
    async def test_no_links_found(self) -> None:
        content = "No social links here."
        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", asyncio.Semaphore()
        )
        assert count == 0

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
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
        },
    )
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/johndoe")
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_skips_already_crawled_urls(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        content = "https://github.com/johndoe"
        crawled_urls: set[str] = {"https://github.com/johndoe"}

        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", asyncio.Semaphore(), crawled_urls=crawled_urls
        )
        assert count == 0

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "twitter": {
                "sender_domains": ["twitter.com"],
                "url_template": "https://x.com/{username}",
                "regex_pattern": r"[a-zA-Z0-9_]{1,15}",
            },
        },
    )
    async def test_skips_same_platform(self) -> None:
        """Profiles from the same platform as source should be skipped."""
        content = "https://x.com/otheruser"
        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", asyncio.Semaphore()
        )
        assert count == 0

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
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
        },
    )
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/johndoe")
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_crawl_failure_yields_zero(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        # crawl_profile_url returns a single dict with error set
        mock_crawl.return_value = {"content": None, "error": "timeout"}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        content = "https://github.com/johndoe"
        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", asyncio.Semaphore()
        )
        assert count == 0

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
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
        },
    )
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/johndoe")
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_zero_facts_extracted_returns_zero(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        # crawl_profile_url returns a single dict with content
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=0))

        content = "https://github.com/johndoe"
        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", asyncio.Semaphore()
        )
        assert count == 0


# ---------------------------------------------------------------------------
# fetch_emails_for_onboarding — mailbox scope
# ---------------------------------------------------------------------------


class TestFetchEmailsForOnboardingScope:
    """The Gmail scope each onboarding consumer scans."""

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_defaults_to_inbox_only(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[])
        await fetch_emails_for_onboarding(USER_ID)
        query = mock_search.await_args.kwargs["query"]
        assert query == "in:inbox newer_than:30d"

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_include_sent_spans_both_mailboxes(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[])
        await fetch_emails_for_onboarding(
            USER_ID, options=OnboardingFetchOptions(include_sent=True)
        )
        query = mock_search.await_args.kwargs["query"]
        assert query == "(in:inbox OR in:sent) newer_than:30d"

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_months_scales_the_recency_window(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[])
        await fetch_emails_for_onboarding(
            USER_ID,
            months=3,
            options=OnboardingFetchOptions(include_sent=True),
        )
        assert mock_search.await_args.kwargs["query"] == "(in:inbox OR in:sent) newer_than:90d"


class TestFetchEmailsForOnboardingSentLabelSurvives:
    """A SENT message fetched for social profiles must stay recognisably sent
    all the way to the ownership signal — query, transform, and extraction."""

    @staticmethod
    def _composio_message(message_id: str, label_ids: list[str], text: str) -> dict:
        return {
            "messageId": message_id,
            "threadId": f"t-{message_id}",
            "messageText": text,
            "labelIds": label_ids,
            "sender": "me@example.com",
            "subject": "my links",
        }

    async def _fetch_through_real_transform(self, raw_messages: list[dict]) -> list[dict]:
        """Run the real search_messages + transform_gmail_message pipeline,
        stubbing only the Composio network call."""
        with patch(
            "app.services.mail.mail_service.invoke_gmail_tool",
            new_callable=AsyncMock,
        ) as mock_invoke:
            mock_invoke.side_effect = [
                GmailToolResult.model_validate(
                    {
                        "successful": True,
                        "data": {"messages": raw_messages, "nextPageToken": None},
                    }
                ),
            ]
            return await fetch_emails_for_onboarding(
                USER_ID, options=OnboardingFetchOptions(fmt="full", include_sent=True), max_total=10
            )

    async def test_sent_label_reaches_ownership_signal(self) -> None:
        emails = await self._fetch_through_real_transform(
            [
                self._composio_message(
                    "m1", ["SENT"], "here is my profile https://github.com/octocat"
                ),
                self._composio_message(
                    "m2", ["INBOX"], "someone else linked https://github.com/strangerdev"
                ),
            ]
        )
        assert [e["labelIds"] for e in emails] == [["SENT"], ["INBOX"]]

        with patch(
            "app.services.onboarding.social_profile_service.get_helper_llm",
            side_effect=LLMNotConfiguredError("no llm"),
        ):
            profiles = await extract_social_profiles_from_emails(emails, "Octo Cat", None)

        # Without the LLM the service falls back to sent-mail ownership only,
        # so this is empty unless is_sent actually became True.
        assert [p.url for p in profiles] == ["https://github.com/octocat"]

    async def test_inbox_only_scan_yields_no_sent_ownership(self) -> None:
        """Guards the regression: an inbox-scoped fetch can never produce the signal."""
        emails = await self._fetch_through_real_transform(
            [self._composio_message("m1", ["INBOX"], "link https://github.com/octocat")]
        )
        with patch(
            "app.services.onboarding.social_profile_service.get_helper_llm",
            side_effect=LLMNotConfiguredError("no llm"),
        ):
            profiles = await extract_social_profiles_from_emails(emails, "Octo Cat", None)
        assert profiles == []


# ---------------------------------------------------------------------------
# Exact-behavior pins for the onboarding fetch pipeline helpers
# ---------------------------------------------------------------------------


class TestLatestGmailScanTimestamp:
    def test_none_user_returns_none(self) -> None:
        assert _latest_gmail_scan_timestamp(None) is None

    def test_user_without_scan_states_returns_none(self) -> None:
        user = UserDocument(id=USER_ID)
        assert _latest_gmail_scan_timestamp(user) is None

    def test_non_dict_gmail_state_returns_none(self) -> None:
        user = UserDocument(id=USER_ID, integration_scan_states={"gmail": "nope"})
        assert _latest_gmail_scan_timestamp(user) is None

    def test_returns_the_stored_timestamp(self) -> None:
        ts = datetime(2025, 6, 1, tzinfo=UTC)
        user = UserDocument(
            id=USER_ID, integration_scan_states={"gmail": {"last_scan_timestamp": ts}}
        )
        assert _latest_gmail_scan_timestamp(user) == ts


class TestFetchEmailsForOnboardingPins:
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_search_receives_exact_kwargs(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[])
        await fetch_emails_for_onboarding(USER_ID, max_total=5)
        kwargs = mock_search.await_args.kwargs
        assert kwargs["user_id"] == USER_ID
        assert kwargs["query"] == "in:inbox newer_than:30d"
        assert kwargs["max_results"] == 5  # min(BATCH_SIZE, remaining)
        assert kwargs["page_token"] is None
        opts = kwargs["options"]
        assert opts.output_format == "metadata"
        assert opts.include_payload is False
        assert opts.verbose is False

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_full_format_requests_payload_and_verbose(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[])
        await fetch_emails_for_onboarding(
            USER_ID, options=OnboardingFetchOptions(fmt="full", include_sent=True)
        )
        opts = mock_search.await_args.kwargs["options"]
        assert opts.output_format == "full"
        assert opts.include_payload is True
        assert opts.verbose is True

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_batches_are_appended_into_the_callers_list(self, mock_search: AsyncMock) -> None:
        batch = [{"id": "1"}, {"id": "2"}]
        mock_search.return_value = GmailMessagesResponse(messages=batch)
        into: list[dict] = []
        result = await fetch_emails_for_onboarding(USER_ID, max_total=2, into=into)
        assert into == batch
        assert result is into

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_on_batch_receives_running_count_and_latest_sender(
        self, mock_search: AsyncMock
    ) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[{"from": "Alice <alice@x.com>"}])
        seen: list[tuple[int, str | None]] = []

        async def on_batch(count: int, sender: str | None) -> None:
            seen.append((count, sender))

        await fetch_emails_for_onboarding(USER_ID, max_total=1, on_batch=on_batch)
        assert seen == [(1, "Alice")]

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_pagination_follows_next_page_token(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = [
            GmailMessagesResponse(messages=[{"id": "1"}], next_page_token="tok"),
            GmailMessagesResponse(messages=[{"id": "2"}]),
        ]
        result = await fetch_emails_for_onboarding(USER_ID, max_total=10)
        assert [m["id"] for m in result] == ["1", "2"]
        assert mock_search.await_count == 2
        assert mock_search.await_args_list[1].kwargs["page_token"] == "tok"

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_final_page_requests_only_the_remaining_allowance(
        self, mock_search: AsyncMock
    ) -> None:
        """After 3 of 10 emails, the next batch asks for exactly 7 — not
        max_total and not BATCH_SIZE."""
        mock_search.side_effect = [
            GmailMessagesResponse(
                messages=[{"id": "1"}, {"id": "2"}, {"id": "3"}], next_page_token="tok"
            ),
            GmailMessagesResponse(messages=[]),
        ]
        await fetch_emails_for_onboarding(USER_ID, max_total=10)
        assert mock_search.await_args_list[1].kwargs["max_results"] == 7

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_fetch_error_is_propagated_after_logging(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = RuntimeError("gmail down")
        with patch("app.agents.memory.email_processor.log") as log:
            with pytest.raises(RuntimeError, match="gmail down"):
                await fetch_emails_for_onboarding(USER_ID)
        log.error.assert_called_once()
        assert log.error.call_args.kwargs["error_type"] == "RuntimeError"
        assert log.error.call_args.kwargs["user_id"] == USER_ID


class TestCollectStorageResultsPins:
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_failed_storage_batch_is_counted_and_logged(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(
            return_value=UserDocument(id=USER_ID, email_memory_processed=False, name="T")
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_store.side_effect = RuntimeError("mongo down")
        mock_profiles.return_value = {"profiles_stored": 0}

        with patch("app.agents.memory.email_processor.log") as log:
            result = await process_gmail_to_memory(USER_ID)

        assert result["successful"] == 1
        assert result["processing_complete"] is True
        # Storage failed → the scan watermark must NOT advance, or the
        # parsed-but-unstored emails would be skipped on every later run.
        mock_users.set_gmail_scan_timestamp.assert_not_awaited()
        held = [
            c
            for c in log.warning.call_args_list
            if c.args and "watermark not advanced" in str(c.args[0])
        ]
        assert len(held) == 1
        failed_calls = [
            c
            for c in log.warning.call_args_list
            if c.args and c.args[0] == f"{LogTag.MEMORY} Email storage task failed"
        ]
        assert len(failed_calls) == 1
        assert failed_calls[0].kwargs["task_index"] == 1
        assert failed_calls[0].kwargs["error_type"] == "RuntimeError"

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_no_batches_skips_the_storage_phase_entirely(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(
            return_value=UserDocument(id=USER_ID, email_memory_processed=False, name="T")
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[])
        mock_profiles.return_value = {"profiles_stored": 0}

        with patch("app.agents.memory.email_processor.log") as log:
            result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 0
        dispatched = [
            c
            for c in log.info.call_args_list
            if c.args and "storage tasks dispatched" in str(c.args[0])
        ]
        assert dispatched == []

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_processing_complete_requires_at_least_one_parsed_email(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(
            return_value=UserDocument(id=USER_ID, email_memory_processed=False, name="T")
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        # Emails fetched but ALL fail parsing → nothing stored → not complete.
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([], 3)
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["failed"] == 3
        assert result["processing_complete"] is False
        mock_mark.assert_not_awaited()


class TestCollectStorageResultsDirect:
    """Direct pins on the storage-await helper's counting and logging."""

    def _timer(self) -> _StepTimer:
        return _StepTimer()

    async def test_no_tasks_returns_zero_without_logging_dispatch(self) -> None:
        from app.agents.memory.email_processor import _collect_storage_results

        with patch("app.agents.memory.email_processor.log") as log:
            errors = await _collect_storage_results(USER_ID, [], self._timer())
        assert errors == 0
        assert log.info.call_args_list == []

    async def test_failed_batches_are_counted_with_exact_log(self) -> None:
        from app.agents.memory.email_processor import _collect_storage_results

        async def ok() -> None:
            await asyncio.sleep(0)

        async def boom() -> None:
            raise RuntimeError("mongo down")

        tasks = [asyncio.create_task(ok()), asyncio.create_task(boom())]
        with patch("app.agents.memory.email_processor.log") as log:
            errors = await _collect_storage_results(USER_ID, tasks, self._timer())

        assert errors == 1
        warning = log.warning.call_args
        assert f"{LogTag.MEMORY} Email storage task failed" in warning.args[0]
        assert warning.kwargs["task_index"] == 2
        assert warning.kwargs["error_type"] == "RuntimeError"
        complete = [c for c in log.info.call_args_list if "storage complete" in str(c.args[0])]
        assert len(complete) == 1
        assert complete[0].kwargs["successful_batches"] == 1
        assert complete[0].kwargs["total_batches"] == 2
        assert complete[0].kwargs["failed_batches"] == 1

    async def test_two_failed_batches_count_two_with_each_tasks_error(self) -> None:
        """storage_errors accumulates (+1 per failure) and each warning names
        that task's own error message."""

        async def boom(message: str) -> None:
            raise RuntimeError(message)

        tasks = [asyncio.create_task(boom("mongo down")), asyncio.create_task(boom("redis down"))]
        with patch("app.agents.memory.email_processor.log") as log:
            errors = await _collect_storage_results(USER_ID, tasks, _StepTimer())

        assert errors == 2
        warnings = [
            c
            for c in log.warning.call_args_list
            if c.args and c.args[0] == f"{LogTag.MEMORY} Email storage task failed"
        ]
        assert [w.kwargs["task_index"] for w in warnings] == [1, 2]
        assert [w.kwargs["error_type"] for w in warnings] == ["RuntimeError", "RuntimeError"]
        assert [w.kwargs["error"] for w in warnings] == ["mongo down", "redis down"]

    async def test_a_gather_failure_counts_every_task_as_failed(self) -> None:
        from app.agents.memory.email_processor import _collect_storage_results

        class ExplodingTasks:
            def __iter__(self):
                return iter([])

            def __len__(self) -> int:
                return 3

        # gather() over an empty iterable returns [] without error, so force the
        # except path via a poisoned timer instead.
        timer = self._timer()
        timer.record = MagicMock(side_effect=RuntimeError("clock broke"))

        async def ok() -> None:
            await asyncio.sleep(0)

        tasks = [asyncio.create_task(ok())]
        with patch("app.agents.memory.email_processor.log") as log:
            errors = await _collect_storage_results(USER_ID, tasks, timer)

        assert errors == 1
        critical = [c for c in log.error.call_args_list if "Critical error" in str(c.args[0])]
        assert len(critical) == 1
        assert critical[0].kwargs["error_type"] == "RuntimeError"


class TestMarkProcessingCompletePins:
    async def test_incomplete_processing_skips_the_mark_write_but_stamps_the_time(self) -> None:
        timer = MagicMock()
        with (
            patch(_PATCH_USERS) as users,
            patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock) as mark,
        ):
            users.set_gmail_scan_timestamp = AsyncMock()
            await _mark_processing_complete(USER_ID, False, 0, timer)

        mark.assert_not_awaited()
        users.set_gmail_scan_timestamp.assert_awaited_once()

    async def test_complete_processing_marks_and_logs_exact_args(self) -> None:
        timer = MagicMock()
        with (
            patch(_PATCH_USERS) as users,
            patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock) as mark,
            patch("app.agents.memory.email_processor.log") as log,
        ):
            users.set_gmail_scan_timestamp = AsyncMock()
            await _mark_processing_complete(USER_ID, True, 7, timer)

        mark.assert_awaited_once_with(USER_ID, 7)
        done_logs = [
            c
            for c in log.info.call_args_list
            if "Marked email processing as complete" in str(c.args[0])
        ]
        assert len(done_logs) == 1
        assert done_logs[0].kwargs["user_id"] == USER_ID

    async def test_skipped_watermark_warning_names_the_user(self) -> None:
        timer = MagicMock()
        with (
            patch(_PATCH_USERS) as users,
            patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock),
            patch("app.agents.memory.email_processor.log") as log,
        ):
            users.set_gmail_scan_timestamp = AsyncMock()
            await _mark_processing_complete(USER_ID, False, 0, timer, False)

        warning = log.warning.call_args
        assert "watermark not advanced" in warning.args[0]
        assert warning.kwargs == {"user_id": USER_ID}
        users.set_gmail_scan_timestamp.assert_not_awaited()

    async def test_mark_failure_is_swallowed_and_timestamp_still_written(self) -> None:
        timer = MagicMock()
        with (
            patch(_PATCH_USERS) as users,
            patch(
                _PATCH_MARK_COMPLETE,
                new_callable=AsyncMock,
                side_effect=RuntimeError("db down"),
            ),
            patch("app.agents.memory.email_processor.log") as log,
        ):
            users.set_gmail_scan_timestamp = AsyncMock()
            await _mark_processing_complete(USER_ID, True, 5, timer)

        users.set_gmail_scan_timestamp.assert_awaited_once()
        error_logs = [
            c
            for c in log.error.call_args_list
            if "Failed to mark email processing" in str(c.args[0])
        ]
        assert len(error_logs) == 1
        assert error_logs[0].kwargs["error_type"] == "RuntimeError"


class TestLatestGmailScanTimestampEdges:
    def test_non_dict_scan_states_returns_none(self) -> None:
        user = UserDocument(id=USER_ID)
        object.__setattr__(user, "integration_scan_states", "not-a-dict")
        assert _latest_gmail_scan_timestamp(user) is None

    def test_missing_last_scan_key_returns_none(self) -> None:
        user = UserDocument(id=USER_ID, integration_scan_states={"gmail": {"other": 1}})
        assert _latest_gmail_scan_timestamp(user) is None


class TestProcessGmailToMemoryReturnShape:
    @patch(_PATCH_USERS)
    async def test_already_processed_return_dict_is_exact(self, mock_users: MagicMock) -> None:
        mock_users.get = AsyncMock(
            return_value=UserDocument(id=USER_ID, email_memory_processed=True, name="T")
        )
        result = await process_gmail_to_memory(USER_ID)
        assert result == {
            "total": 0,
            "successful": 0,
            "already_processed": True,
            "processing_complete": True,
        }

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_the_scan_query_is_the_after_timestamp_form(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        ts = datetime(2026, 3, 1, tzinfo=UTC)
        mock_users.get = AsyncMock(
            return_value=UserDocument(
                id=USER_ID,
                email_memory_processed=False,
                name="T",
                integration_scan_states={"gmail": {"last_scan_timestamp": ts}},
            )
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[])
        mock_profiles.return_value = {"profiles_stored": 0}

        await process_gmail_to_memory(USER_ID)

        expected_after = int(ts.timestamp())
        assert mock_search.await_args.kwargs["query"] == f"in:inbox after:{expected_after}"

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_non_datetime_scan_timestamp_leaves_query_untouched(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(
            return_value=UserDocument(
                id=USER_ID,
                email_memory_processed=False,
                name="T",
                integration_scan_states={"gmail": {"last_scan_timestamp": "not-a-date"}},
            )
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[])
        mock_profiles.return_value = {"profiles_stored": 0}

        await process_gmail_to_memory(USER_ID)

        assert mock_search.await_args.kwargs["query"] == "in:inbox"


# ---------------------------------------------------------------------------
# Mutation-kill pins: _extract_profiles_from_parallel_searches
# ---------------------------------------------------------------------------


def _success_platform_result(platform: str) -> dict[str, Any]:
    return {
        "success": True,
        "platform": platform,
        "url": f"https://{platform}.example/user",
        "discovery_task": f"task-{platform}",
    }


class TestExtractProfilesParallelPins:
    """Exact pins on tallying, propagation, early returns and error logging."""

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    async def test_no_platform_emails_returns_exactly_the_empty_dict(
        self, mock_parallel: AsyncMock, mock_users: MagicMock
    ) -> None:
        mock_users.get = AsyncMock(return_value=UserDocument(name="Test"))
        mock_parallel.return_value = {"github": [], "twitter": []}

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {"profiles_stored": 0}

    @patch(_PATCH_LOG)
    @patch(_PATCH_USERS)
    async def test_exception_returns_exact_error_dict_and_logs_exact_args(
        self, mock_users: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_users.get = AsyncMock(side_effect=RuntimeError("db down"))

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {"profiles_stored": 0, "extracted_profiles": []}
        (msg,), kwargs = mock_log.error.call_args
        assert msg == f"{LogTag.MEMORY} Error in profile extraction from parallel searches"
        assert kwargs["error_type"] == "RuntimeError"
        assert kwargs["error"] == "db down"
        assert kwargs["user_id"] == USER_ID

    @patch(_PATCH_LOG)
    @patch(_PATCH_AWAIT_DISCOVERY, new_callable=AsyncMock, return_value=5)
    @patch(_PATCH_PROCESS_SINGLE, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    async def test_happy_path_tallies_platforms_plus_discovered_and_logs_exact(
        self,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
        mock_single: AsyncMock,
        mock_discovery: AsyncMock,
        mock_log: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=UserDocument(name="Test User"))
        # "reddit" has no emails and must be filtered out entirely.
        mock_parallel.return_value = {
            "github": [{"id": "g"}],
            "reddit": [],
            "twitter": [{"id": "t"}],
        }
        seen: list[tuple[str, str | None, set[str]]] = []

        def fake_single(
            user_id: str,
            platform: str,
            emails: list[dict[str, Any]],
            semaphore: asyncio.Semaphore,
            user_name: str | None = None,
            crawled_urls: set[str] | None = None,
        ) -> dict[str, Any]:
            seen.append((platform, user_name, crawled_urls if crawled_urls is not None else set()))
            return _success_platform_result(platform)

        mock_single.side_effect = fake_single

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {
            "profiles_stored": 7,  # 2 platforms succeeded + 5 discovered
            "extracted_profiles": [
                {"platform": "github", "url": "https://github.example/user"},
                {"platform": "twitter", "url": "https://twitter.example/user"},
            ],
        }
        assert [s[0] for s in seen] == ["github", "twitter"]
        assert all(s[1] == "Test User" for s in seen)
        # Both calls share one deduplication set.
        shared_sets = {id(s[2]) for s in seen}
        assert len(shared_sets) == 1
        mock_discovery.assert_awaited_once_with(USER_ID, ["task-github", "task-twitter"])

        completed = [
            c
            for c in mock_log.info.call_args_list
            if c.args and c.args[0] == f"{LogTag.MEMORY} Profile extraction completed"
        ]
        assert len(completed) == 1
        assert completed[0].kwargs["profiles_stored"] == 7
        assert completed[0].kwargs["platform_count"] == 2
        assert completed[0].kwargs["discovered_count"] == 5
        assert completed[0].kwargs["user_id"] == USER_ID
        assert completed[0].kwargs["duration_s"] == round(completed[0].kwargs["duration_s"], 2)

    @patch(_PATCH_AWAIT_DISCOVERY, new_callable=AsyncMock, return_value=0)
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    async def test_missing_user_passes_none_as_user_name(
        self, mock_parallel: AsyncMock, mock_users: MagicMock, mock_discovery: AsyncMock
    ) -> None:
        mock_users.get = AsyncMock(return_value=None)
        mock_parallel.return_value = {"github": [{"id": "g"}]}

        with patch(_PATCH_PROCESS_SINGLE, new_callable=AsyncMock) as mock_single:
            mock_single.side_effect = lambda *a, **k: _success_platform_result(a[1])
            result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result["profiles_stored"] == 1
        assert mock_single.await_args.args[4] is None


# ---------------------------------------------------------------------------
# Mutation-kill pins: _source_domain_for
# ---------------------------------------------------------------------------


class TestSourceDomainFor:
    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "twitter": {"url_template": "https://x.com/{username}"},
            "linkedin": {"url_template": "https://linkedin.com/in/{username}"},
            "quora": {"url_template": "https://quora.com/profile/{username}"},
            "substack": {"url_template": "https://{username}.substack.com"},
        },
    )
    def test_returns_second_path_segment_of_the_url_template(self) -> None:
        assert _source_domain_for("twitter") == "x.com"
        assert _source_domain_for("linkedin") == "linkedin.com"
        assert _source_domain_for("quora") == "quora.com"
        assert _source_domain_for("substack") == "{username}.substack.com"

    @patch(_PATCH_PLATFORM_CONFIG, {"github": {"url_template": "https://github.com/{u}"}})
    def test_unknown_platform_returns_none(self) -> None:
        assert _source_domain_for("myspace") is None

    def test_real_config_domains(self) -> None:
        assert _source_domain_for("twitter") == "x.com"
        assert _source_domain_for("github") == "github.com"
        assert _source_domain_for("linkedin") == "linkedin.com"


# ---------------------------------------------------------------------------
# Mutation-kill pins: exact calls inside the remaining helpers
# ---------------------------------------------------------------------------


class _GetSpyDict(dict):
    """dict that records every .get() call so the exact query can be pinned."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.get_calls: list[tuple[str, Any]] = []

    def get(self, key: str, default: Any = None) -> Any:
        self.get_calls.append((key, default))
        return super().get(key, default)


class TestLatestGmailScanTimestampExactCallPins:
    def test_missing_gmail_key_is_queried_with_an_empty_dict_default(self) -> None:
        scan_states = _GetSpyDict({"other": {"last_scan_timestamp": "x"}})
        user = UserDocument(id=USER_ID)
        object.__setattr__(user, "integration_scan_states", scan_states)

        assert _latest_gmail_scan_timestamp(user) is None
        assert scan_states.get_calls == [("gmail", {})]

    def test_present_gmail_state_result_is_cast_to_datetime_or_none(self) -> None:
        ts = datetime(2025, 6, 1, tzinfo=UTC)
        user = UserDocument(
            id=USER_ID, integration_scan_states={"gmail": {"last_scan_timestamp": ts}}
        )

        with patch(
            "app.agents.memory.email_processor.cast", side_effect=lambda typ, val: val
        ) as mock_cast:
            result = _latest_gmail_scan_timestamp(user)

        assert result == ts
        mock_cast.assert_called_once_with(datetime | None, ts)


class TestExtractProfilesEarlyPhasePins:
    """Pins the ids forwarded and the search-stats log before platform processing."""

    @patch(_PATCH_LOG)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    async def test_early_phase_passes_exact_ids_and_logs_exact_search_stats(
        self, mock_users: MagicMock, mock_parallel: AsyncMock, mock_log: MagicMock
    ) -> None:
        mock_users.get = AsyncMock(return_value=UserDocument(name="U"))
        mock_parallel.return_value = {}

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {"profiles_stored": 0}
        mock_users.get.assert_awaited_once_with(USER_ID)
        mock_parallel.assert_awaited_once_with(USER_ID)

        (msg,), kwargs = mock_log.info.call_args
        assert msg == f"{LogTag.MEMORY} _search_platform_emails_parallel finished"
        assert set(kwargs) == {"duration_s"}
        assert isinstance(kwargs["duration_s"], float)


def _linked_links_config() -> dict[str, dict[str, str]]:
    return {
        "twitter": {
            "sender_domains": ["x.com"],
            "url_template": "https://x.com/{username}",
            "regex_pattern": r"[a-zA-Z0-9_]{1,15}",
        },
        # Resolves to twitter's domain: the same-domain skip must hide it.
        "xmirror": {
            "sender_domains": ["x.com"],
            "url_template": "https://x.com/{username}",
            "regex_pattern": r"[a-z]+[0-9]*",
        },
        "github": {
            "sender_domains": ["github.com"],
            "url_template": "https://github.com/{username}",
            "regex_pattern": r"^[a-zA-Z0-9-]{1,39}$",
        },
        "anchorp": {
            "sender_domains": ["anchor.fm"],
            "url_template": "https://anchor.fm/{username}",
            "regex_pattern": r"[a-z]+99",
        },
    }


_LINKED_CONTENT = (
    "Read https://github.com/johndoe, mirror https://x.com/mirror9, "
    "then HTTPS://ANCHOR.FM/sam99 today"
)


class TestExtractLinkedProfileLinksPins:
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    @patch(_PATCH_PLATFORM_CONFIG, _linked_links_config())
    def test_discovers_exact_links_with_exact_validate_and_build_calls(
        self, mock_validate: MagicMock, mock_build: MagicMock
    ) -> None:
        mock_validate.return_value = True
        mock_build.side_effect = lambda username, platform: f"https://built.{platform}/{username}"
        crawled_urls: set[str] = set()

        result = _extract_linked_profile_links(_LINKED_CONTENT, "twitter", crawled_urls)

        assert result == {
            "github_johndoe": {
                "platform": "github",
                "url": "https://built.github/johndoe",
                "username": "johndoe",
            },
            "anchorp_sam99": {
                "platform": "anchorp",
                "url": "https://built.anchorp/sam99",
                "username": "sam99",
            },
        }
        mock_validate.assert_has_calls([call("johndoe", "github"), call("sam99", "anchorp")])
        assert mock_validate.call_count == 2
        mock_build.assert_has_calls([call("johndoe", "github"), call("sam99", "anchorp")])
        assert mock_build.call_count == 2
        assert crawled_urls == {
            "https://built.github/johndoe",
            "https://built.anchorp/sam99",
        }

    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    @patch(_PATCH_PLATFORM_CONFIG, _linked_links_config())
    def test_already_crawled_url_is_skipped_without_stopping_the_scan(
        self, mock_validate: MagicMock, mock_build: MagicMock
    ) -> None:
        mock_validate.return_value = True
        mock_build.side_effect = lambda username, platform: f"https://built.{platform}/{username}"
        crawled_urls: set[str] = {"https://built.github/johndoe"}

        result = _extract_linked_profile_links(_LINKED_CONTENT, "twitter", crawled_urls)

        assert result == {
            "anchorp_sam99": {
                "platform": "anchorp",
                "url": "https://built.anchorp/sam99",
                "username": "sam99",
            },
        }
        assert crawled_urls == {
            "https://built.github/johndoe",
            "https://built.anchorp/sam99",
        }

    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    @patch(_PATCH_PLATFORM_CONFIG, _linked_links_config())
    def test_second_username_on_same_platform_survives_an_already_crawled_first(
        self, mock_validate: MagicMock, mock_build: MagicMock
    ) -> None:
        mock_validate.return_value = True
        mock_build.side_effect = lambda username, platform: f"https://built.{platform}/{username}"
        crawled_urls: set[str] = {"https://built.github/johndoe"}

        result = _extract_linked_profile_links(
            "first https://github.com/johndoe then https://github.com/octo99 end",
            "twitter",
            crawled_urls,
        )

        assert result == {
            "github_octo99": {
                "platform": "github",
                "url": "https://built.github/octo99",
                "username": "octo99",
            },
        }

    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    @patch(_PATCH_PLATFORM_CONFIG, _linked_links_config())
    def test_crawled_urls_none_still_finds_links_without_tracking(
        self, mock_validate: MagicMock, mock_build: MagicMock
    ) -> None:
        mock_validate.return_value = True
        mock_build.side_effect = lambda username, platform: f"https://built.{platform}/{username}"

        result = _extract_linked_profile_links(_LINKED_CONTENT, "twitter", None)

        assert set(result) == {"github_johndoe", "anchorp_sam99"}


_CRAWL_DISCOVERED_PROFILES = {
    "github_johndoe": {
        "platform": "github",
        "url": "u-github",
        "username": "johndoe",
    },
    "empty_content": {
        "platform": "anchorp",
        "url": "u-empty",
        "username": "sam99",
    },
    "boom": {"platform": "badplat", "url": "u-boom", "username": "x"},
    "errored": {"platform": "erplat", "url": "u-err", "username": "y"},
}

_CRAWL_RESPONSES = {
    "u-github": {"content": "GH CONTENT", "error": None},
    "u-empty": {"content": "", "error": None},
    "u-err": {"content": "SOME", "error": "boom"},
}


async def _fake_crawl(url: str, platform: str, semaphore: asyncio.Semaphore) -> dict[str, Any]:
    response = _CRAWL_RESPONSES.get(url)
    if url == "u-boom":
        raise RuntimeError("crawl blew up")
    return response


class TestCollectStorageResultsLogArgPins:
    @patch("app.agents.memory.email_processor.time")
    @patch(_PATCH_LOG)
    async def test_dispatch_log_pins_exact_rounded_duration(
        self, mock_log: MagicMock, mock_time: MagicMock
    ) -> None:
        from app.agents.memory.email_processor import _collect_storage_results

        # Non-zero base: the duration must be a DIFFERENCE of the two
        # monotonic readings, not their sum.
        mock_time.monotonic = MagicMock(side_effect=[10.0, 10.1234])

        async def ok() -> None:
            await asyncio.sleep(0)

        tasks = [asyncio.create_task(ok())]
        errors = await _collect_storage_results(USER_ID, tasks, _StepTimer())

        assert errors == 0
        dispatched = [
            c
            for c in mock_log.info.call_args_list
            if c.args and c.args[0] == f"{LogTag.MEMORY} Memory email storage tasks dispatched"
        ]
        assert len(dispatched) == 1
        assert dispatched[0].kwargs == {"duration_s": 0.1}

    @patch(_PATCH_LOG)
    async def test_critical_error_log_carries_exact_args(self, mock_log: MagicMock) -> None:
        from app.agents.memory.email_processor import _collect_storage_results

        timer = _StepTimer()
        timer.record = MagicMock(side_effect=RuntimeError("clock broke"))

        async def ok() -> None:
            await asyncio.sleep(0)

        tasks = [asyncio.create_task(ok())]
        errors = await _collect_storage_results(USER_ID, tasks, timer)

        assert errors == 1
        (msg,), kwargs = mock_log.error.call_args
        assert msg == f"{LogTag.MEMORY} Critical error in email storage tasks"
        assert kwargs == {
            "error_type": "RuntimeError",
            "error": "clock broke",
            "user_id": USER_ID,
        }


class TestCrawlAndStoreDiscoveredExactPins:
    @patch(_PATCH_LOG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL)
    async def test_success_path_makes_exact_crawl_and_retain_calls(
        self, mock_crawl: AsyncMock, mock_memory: MagicMock, mock_log: MagicMock
    ) -> None:
        semaphore = asyncio.Semaphore()
        mock_crawl.side_effect = _fake_crawl
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=3))

        count = await _crawl_and_store_discovered(
            USER_ID, _CRAWL_DISCOVERED_PROFILES, "twitter", semaphore
        )

        assert count == 1
        assert [(c.args[0], c.args[1], c.args[2]) for c in mock_crawl.await_args_list] == [
            ("u-github", "github", semaphore),
            ("u-empty", "anchorp", semaphore),
            ("u-boom", "badplat", semaphore),
            ("u-err", "erplat", semaphore),
        ]
        mock_memory.retain.assert_awaited_once_with(
            USER_ID,
            [
                {
                    "role": "user",
                    "content": "User's github profile: u-github\n\nGH CONTENT\n",
                }
            ],
            source_type=MemorySourceType.EMAIL,
            extraction_hints=_EXTRACTION_HINTS_TWITTER,
        )
        (msg,), kwargs = mock_log.info.call_args
        assert msg == f"{LogTag.MEMORY} Stored discovered profiles"
        assert kwargs == {
            "profile_count": 1,
            "source_platform": "twitter",
            "user_id": USER_ID,
        }
        mock_log.warning.assert_not_called()

    @patch(_PATCH_LOG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL)
    async def test_zero_facts_logs_exact_warning_and_returns_zero(
        self, mock_crawl: AsyncMock, mock_memory: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_crawl.side_effect = _fake_crawl
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=0))

        count = await _crawl_and_store_discovered(
            USER_ID,
            {"github_johndoe": _CRAWL_DISCOVERED_PROFILES["github_johndoe"]},
            "twitter",
            asyncio.Semaphore(),
        )

        assert count == 0
        (msg,), kwargs = mock_log.warning.call_args
        assert msg == f"{LogTag.MEMORY} No facts extracted from discovered profiles"
        assert kwargs == {"source_platform": "twitter", "user_id": USER_ID}
        mock_log.info.assert_not_called()


class TestDiscoverAndStoreLinkedProfilesArgPins:
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://built.github/selfie")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "twitter": {
                "sender_domains": ["x.com"],
                "url_template": "https://x.com/{username}",
                "regex_pattern": r"[a-zA-Z0-9_]{1,15}",
            },
            "github": {
                "sender_domains": ["github.com"],
                "url_template": "https://github.com/{username}",
                "regex_pattern": r"[a-zA-Z0-9-]{1,39}",
            },
        },
    )
    async def test_own_platform_links_are_never_discovered(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        count = await _discover_and_store_linked_profiles(
            USER_ID, "see my own https://x.com/selfie", "twitter", asyncio.Semaphore()
        )

        assert count == 0
        mock_crawl.assert_not_called()

    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://built.github/johndoe")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "twitter": {
                "sender_domains": ["x.com"],
                "url_template": "https://x.com/{username}",
                "regex_pattern": r"[a-zA-Z0-9_]{1,15}",
            },
            "github": {
                "sender_domains": ["github.com"],
                "url_template": "https://github.com/{username}",
                "regex_pattern": r"[a-zA-Z0-9-]{1,39}",
            },
        },
    )
    async def test_shares_crawled_set_and_forwards_user_id_to_storage(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        mock_crawl.return_value = {"content": "C", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))
        crawled_urls: set[str] = set()
        semaphore = asyncio.Semaphore()

        count = await _discover_and_store_linked_profiles(
            USER_ID,
            "find https://github.com/johndoe pls",
            "twitter",
            semaphore,
            crawled_urls=crawled_urls,
        )

        assert count == 1
        assert crawled_urls == {"https://built.github/johndoe"}
        mock_memory.retain.assert_awaited_once()
        assert mock_memory.retain.await_args.args[0] == USER_ID
        # The crawl runs with the caller's own semaphore...
        assert mock_crawl.await_args.args[2] is semaphore
        # ...and the retention hints name the SOURCE platform.
        hints = mock_memory.retain.await_args.kwargs["extraction_hints"]
        assert "their twitter emails" in hints


class TestExtractProfilesPlatformFailurePins:
    @patch(_PATCH_LOG)
    @patch(_PATCH_AWAIT_DISCOVERY, new_callable=AsyncMock, return_value=0)
    @patch(_PATCH_PROCESS_SINGLE, new_callable=AsyncMock, side_effect=RuntimeError("platform boom"))
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    async def test_platform_failure_error_log_carries_user_id(
        self,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
        mock_single: AsyncMock,
        mock_discovery: AsyncMock,
        mock_log: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=None)
        mock_parallel.return_value = {"github": [{"id": "g"}]}

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        failures = [
            c
            for c in mock_log.error.call_args_list
            if c.args and c.args[0] == f"{LogTag.MEMORY} Platform extraction failed"
        ]
        assert len(failures) == 1
        assert failures[0].kwargs["platform"] == "github"
        assert failures[0].kwargs["error_type"] == "RuntimeError"
        assert failures[0].kwargs["user_id"] == USER_ID
        assert result["profiles_stored"] == 0


# ---------------------------------------------------------------------------
# _collect_platform_results / _await_discovery_tasks — tally + discovery await
# ---------------------------------------------------------------------------


class TestCollectPlatformResultsDirect:
    @patch(_PATCH_LOG)
    def test_exception_result_is_logged_and_not_tallied(self, mock_log: MagicMock) -> None:
        boom = RuntimeError("gmail search down")

        profiles_stored, extracted, discovery = _collect_platform_results(
            USER_ID, [("github", None)], [boom]
        )

        assert profiles_stored == 0
        assert extracted == []
        assert discovery == []
        (msg,), kwargs = mock_log.error.call_args
        assert msg == f"{LogTag.MEMORY} Platform extraction failed"
        assert kwargs["platform"] == "github"
        assert kwargs["error_type"] == "RuntimeError"
        assert kwargs["error"] == "gmail search down"
        assert kwargs["user_id"] == USER_ID

    @patch(_PATCH_LOG)
    def test_non_success_dict_result_is_not_tallied(self, mock_log: MagicMock) -> None:
        """An error-dict outcome is neither tallied nor treated as a success."""
        profiles_stored, extracted, discovery = _collect_platform_results(
            USER_ID,
            [("github", None)],
            [{"error": "Invalid username 'bad!' for github"}],
        )

        assert profiles_stored == 0
        assert extracted == []
        assert discovery == []
        mock_log.error.assert_not_called()


class TestAwaitDiscoveryTasksDirect:
    @patch(_PATCH_LOG)
    async def test_empty_task_list_returns_zero_without_gathering(
        self, mock_log: MagicMock
    ) -> None:
        assert await _await_discovery_tasks(USER_ID, []) == 0
        mock_log.info.assert_not_called()

    @patch(_PATCH_LOG)
    async def test_sums_int_results_and_logs_failed_tasks(self, mock_log: MagicMock) -> None:
        async def store(count: int) -> int:
            return count

        async def boom() -> int:
            raise RuntimeError("crawl died")

        tasks = [
            asyncio.create_task(store(2)),
            asyncio.create_task(boom()),
            asyncio.create_task(store(3)),
        ]

        discovered = await _await_discovery_tasks(USER_ID, tasks)

        assert discovered == 5
        failure_logs = [
            c for c in mock_log.error.call_args_list if "Discovery task failed" in c.args[0]
        ]
        assert len(failure_logs) == 1
        assert failure_logs[0].kwargs["error_type"] == "RuntimeError"
        assert failure_logs[0].kwargs["error"] == "crawl died"
        assert failure_logs[0].kwargs["user_id"] == USER_ID


# ---------------------------------------------------------------------------
# Mutation-kill pins: process_gmail_to_memory forwarding + timing
# ---------------------------------------------------------------------------


class TestProcessGmailToMemoryForwardingPins:
    """Every id and total the orchestrator computes must reach the stage
    helpers intact."""

    async def test_ids_and_totals_flow_intact_through_every_stage(self) -> None:
        mock_users = MagicMock()
        mock_users.get = AsyncMock(
            return_value=UserDocument(
                id=USER_ID, email_memory_processed=False, name="N", email="n@x.com"
            )
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search = AsyncMock(return_value=GmailMessagesResponse(messages=[{"id": "1"}]))
        mock_profiles = AsyncMock(return_value={"profiles_stored": 0})
        mock_process = MagicMock(return_value=([{"role": "user", "content": "c"}], 0))
        mock_store = AsyncMock()
        mock_collect_storage = AsyncMock(return_value=0)
        mock_profile_collection = AsyncMock(return_value=(2, [{"platform": "github", "url": "u"}]))
        mock_mark = AsyncMock()
        mock_log = MagicMock()

        with patch.multiple(
            _EMAIL_PROCESSOR_MODULE,
            user_repository=mock_users,
            search_messages=mock_search,
            _extract_profiles_from_parallel_searches=mock_profiles,
            process_email_content=mock_process,
            store_emails_to_memory=mock_store,
            _collect_storage_results=mock_collect_storage,
            _collect_profile_extraction=mock_profile_collection,
            _mark_processing_complete=mock_mark,
            log=mock_log,
        ):
            result = await process_gmail_to_memory(USER_ID)

        # The DB lookup, batch-fetch loop and profile track all see USER_ID.
        mock_users.get.assert_awaited_once_with(USER_ID)
        assert mock_search.await_args.kwargs["user_id"] == USER_ID
        # create_task invokes the track immediately; its consumer is mocked,
        # so pin the call (not an await) with the caller's user_id.
        mock_profiles.assert_called_once_with(USER_ID)

        # The user's name/email reach the storage call untouched. The task's
        # consumer (_collect_storage_results) is mocked, so pin the call.
        mock_store.assert_called_once_with(
            USER_ID, [{"role": "user", "content": "c"}], "N", "n@x.com"
        )

        # Stage helpers receive the caller's user_id.
        assert mock_collect_storage.await_args.args[0] == USER_ID
        assert mock_profile_collection.await_args.args[0] == USER_ID

        # Completion gets (USER_ID, True, parsed + profiles, live timer) and
        # advances the watermark because no storage failed.
        mark_args = mock_mark.await_args.args
        assert mark_args[0] == USER_ID
        assert mark_args[1] is True
        assert mark_args[2] == 3  # 1 parsed email + 2 profiles
        assert isinstance(mark_args[3], _StepTimer)
        assert mock_mark.await_args.kwargs == {"advance_watermark": True}

        # The completion log's duration is a real elapsed time.
        completed = [
            c
            for c in mock_log.info.call_args_list
            if c.args and c.args[0] == f"{LogTag.MEMORY} Processing complete"
        ]
        assert len(completed) == 1
        assert completed[0].kwargs["duration_s"] < 10_000

        assert result["profiles_stored"] == 2

    @patch(_PATCH_LOG)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS, return_value=([], 0))
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_USERS)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock, return_value={"profiles_stored": 0})
    async def test_fetch_phase_timing_is_recorded_under_its_exact_label(
        self,
        mock_profiles: AsyncMock,
        mock_users: MagicMock,
        mock_search: AsyncMock,
        mock_process: MagicMock,
        mock_mark: AsyncMock,
        mock_log: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(
            return_value=UserDocument(id=USER_ID, email_memory_processed=False)
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[])

        with patch("app.agents.memory.email_processor.time") as mock_time:
            # Monotonic readings march upward from a non-zero base, so a
            # recorded elapsed time is only correct as a DIFFERENCE; a sum
            # lands near 2000 and fails the bound below.
            mock_time.monotonic = MagicMock(side_effect=itertools.count(1000.0, 0.25))
            mock_time.time = MagicMock(side_effect=[42.0, 42.5])
            await process_gmail_to_memory(USER_ID)

        summaries = [
            c
            for c in mock_log.info.call_args_list
            if c.args and c.args[0] == f"{LogTag.MEMORY} Onboarding email pipeline timing breakdown"
        ]
        assert len(summaries) == 1
        summary = summaries[0].kwargs["summary"]
        lines = summary.splitlines()
        matching = [
            line for line in lines if line.strip().startswith("Gmail fetch + parse phase (total)")
        ]
        assert len(matching) == 1
        elapsed = float(matching[0].split()[-1].rstrip("s"))
        assert elapsed < 100.0
