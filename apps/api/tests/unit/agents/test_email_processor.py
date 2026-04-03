"""Unit tests for app.agents.memory.email_processor."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch


from app.agents.memory.email_processor import (
    _discover_and_store_linked_profiles,
    _extract_profiles_from_parallel_searches,
    _process_single_platform,
    _search_platform_emails,
    _search_platform_emails_parallel,
    process_gmail_to_memory,
)

# Valid 24-char hex string for ObjectId compatibility
USER_ID = "507f1f77bcf86cd799439011"

# ---------------------------------------------------------------------------
# Shared patch targets
# ---------------------------------------------------------------------------
_PATCH_USERS = "app.agents.memory.email_processor.users_collection"
_PATCH_SEARCH = "app.agents.memory.email_processor.search_messages"
_PATCH_EMIT = "app.agents.memory.email_processor.emit_progress"
_PATCH_PROCESS = "app.agents.memory.email_processor.process_email_content"
_PATCH_STORE_EMAILS = "app.agents.memory.email_processor.store_emails_to_mem0"
_PATCH_MARK_COMPLETE = (
    "app.agents.memory.email_processor.mark_email_processing_complete"
)
_PATCH_POST_ONBOARD = (
    "app.agents.memory.email_processor.process_post_onboarding_personalization"
)
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
_PATCH_SEARCH_PARALLEL = (
    "app.agents.memory.email_processor._search_platform_emails_parallel"
)


# ---------------------------------------------------------------------------
# _search_platform_emails
# ---------------------------------------------------------------------------


class TestSearchPlatformEmails:
    """Tests for _search_platform_emails."""

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_messages(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = {"messages": [{"id": "1"}, {"id": "2"}]}
        result = await _search_platform_emails(USER_ID, "github", "from:github.com")
        assert len(result) == 2
        mock_search.assert_awaited_once_with(
            user_id=USER_ID, query="from:github.com", max_results=50
        )

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_empty_on_no_messages(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = {"messages": []}
        result = await _search_platform_emails(USER_ID, "github", "from:github.com")
        assert result == []

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_empty_on_missing_messages_key(
        self, mock_search: AsyncMock
    ) -> None:
        mock_search.return_value = {}
        result = await _search_platform_emails(USER_ID, "twitter", "from:twitter.com")
        assert result == []

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_empty_on_exception(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = RuntimeError("API error")
        result = await _search_platform_emails(USER_ID, "github", "from:github.com")
        assert result == []

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_respects_max_results(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = {"messages": [{"id": "1"}]}
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
    async def test_parallel_search_aggregates_results(
        self, mock_search: AsyncMock
    ) -> None:
        mock_search.side_effect = [
            {"messages": [{"id": "g1"}]},
            {"messages": [{"id": "t1"}, {"id": "t2"}]},
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
    async def test_parallel_search_handles_exception(
        self, mock_search: AsyncMock
    ) -> None:
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
        emails: List[Dict[str, Any]] = [{"id": "1"}]
        semaphore = asyncio.Semaphore(5)

        result = await _process_single_platform(
            USER_ID, "github", emails, semaphore, "Test User"
        )

        assert result["success"] is True
        assert result["platform"] == "github"
        assert result["url"] == "https://github.com/testuser"
        assert "discovery_task" in result
        mock_store.assert_awaited_once()

        # Clean up the discovery task
        if "discovery_task" in result:
            result["discovery_task"].cancel()
            try:
                await result["discovery_task"]
            except (asyncio.CancelledError, Exception):
                pass

    @patch(_PATCH_VALIDATE, return_value=False)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="bad!")
    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"regex_pattern": r"^[a-zA-Z0-9]+$"}},
    )
    async def test_invalid_username(
        self, mock_extract: AsyncMock, mock_validate: MagicMock
    ) -> None:
        semaphore = asyncio.Semaphore(5)
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], semaphore
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
        semaphore = asyncio.Semaphore(5)
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], semaphore
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
        semaphore = asyncio.Semaphore(5)
        crawled_urls: set[str] = {"https://github.com/testuser"}
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], semaphore, crawled_urls=crawled_urls
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
        semaphore = asyncio.Semaphore(5)
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], semaphore
        )
        assert "error" in result
        assert result["error"] == "timeout"

    @patch(
        _PATCH_EXTRACT_USER,
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM down"),
    )
    async def test_exception_returns_error(self, mock_extract: AsyncMock) -> None:
        semaphore = asyncio.Semaphore(5)
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], semaphore
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
        semaphore = asyncio.Semaphore(5)

        with patch(_PATCH_CRAWL, new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = {"content": None, "error": "fail"}
            await _process_single_platform(
                USER_ID, "github", [{"id": "1"}], semaphore, crawled_urls=crawled_urls
            )

        assert "https://github.com/testuser" in crawled_urls


# ---------------------------------------------------------------------------
# process_gmail_to_memory
# ---------------------------------------------------------------------------


class TestProcessGmailToMemory:
    """Tests for the main orchestrator function."""

    @patch(_PATCH_USERS)
    async def test_already_processed_user_returns_early(
        self, mock_users: MagicMock
    ) -> None:
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": USER_ID,
                "email_memory_processed": True,
                "name": "Test",
            }
        )
        result = await process_gmail_to_memory(USER_ID)
        assert result["already_processed"] is True
        assert result["total"] == 0

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_EMIT, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_POST_ONBOARD, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_processes_emails_successfully(
        self,
        mock_profiles: AsyncMock,
        mock_post: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_emit: AsyncMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": USER_ID,
                "email_memory_processed": False,
                "name": "Test User",
                "email": "test@test.com",
            }
        )
        mock_users.update_one = AsyncMock()

        mock_search.return_value = {
            "messages": [{"id": "1"}, {"id": "2"}],
            "nextPageToken": None,
        }
        mock_process.return_value = ([{"role": "user", "content": "email1"}], 0)
        mock_store.return_value = None
        mock_profiles.return_value = {"profiles_stored": 2}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 2
        assert result["successful"] == 1
        assert result["profiles_stored"] == 2
        assert result["processing_complete"] is True
        mock_mark.assert_awaited_once()
        mock_post.assert_awaited_once()

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_EMIT, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_POST_ONBOARD, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_handles_no_emails(
        self,
        mock_profiles: AsyncMock,
        mock_post: AsyncMock,
        mock_mark: AsyncMock,
        mock_process: MagicMock,
        mock_emit: AsyncMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": USER_ID,
                "email_memory_processed": False,
                "name": "Test",
                "email": "t@t.com",
            }
        )
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {"messages": []}
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 0
        assert result["successful"] == 0
        assert result["processing_complete"] is False

    @patch(_PATCH_USERS)
    async def test_handles_null_user(self, mock_users: MagicMock) -> None:
        """If user not found in DB, should proceed without crashing."""
        mock_users.find_one = AsyncMock(return_value=None)
        mock_users.update_one = AsyncMock()

        with (
            patch(_PATCH_SEARCH, new_callable=AsyncMock) as mock_search,
            patch(_PATCH_EMIT, new_callable=AsyncMock),
            patch(_PATCH_PROCESS, return_value=([], 0)),
            patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock),
            patch(_PATCH_POST_ONBOARD, new_callable=AsyncMock),
            patch(
                _PATCH_EXTRACT_PROFILES,
                new_callable=AsyncMock,
                return_value={"profiles_stored": 0},
            ),
        ):
            mock_search.return_value = {"messages": []}
            result = await process_gmail_to_memory(USER_ID)
            assert result["total"] == 0

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_EMIT, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_POST_ONBOARD, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_appends_timestamp_query_when_available(
        self,
        mock_profiles: AsyncMock,
        mock_post: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_emit: AsyncMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": USER_ID,
                "email_memory_processed": False,
                "name": "Test",
                "email": "t@t.com",
                "integration_scan_states": {"gmail": {"last_scan_timestamp": ts}},
            }
        )
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {"messages": []}
        mock_profiles.return_value = {"profiles_stored": 0}

        await process_gmail_to_memory(USER_ID)

        # Should have called with after: timestamp
        call_args = mock_search.call_args
        assert "after:" in call_args.kwargs.get("query", call_args[1].get("query", ""))

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_EMIT, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_POST_ONBOARD, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_profile_extraction_failure_does_not_block(
        self,
        mock_profiles: AsyncMock,
        mock_post: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_emit: AsyncMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        """Profile extraction failure should not block completion."""
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": USER_ID,
                "email_memory_processed": False,
                "name": "Test",
                "email": "t@t.com",
            }
        )
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {
            "messages": [{"id": "1"}],
            "nextPageToken": None,
        }
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_store.return_value = None
        mock_profiles.side_effect = RuntimeError("profile crash")

        result = await process_gmail_to_memory(USER_ID)

        assert result["successful"] == 1
        assert result["profiles_stored"] == 0

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_EMIT, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(
        _PATCH_MARK_COMPLETE,
        new_callable=AsyncMock,
        side_effect=RuntimeError("mark fail"),
    )
    @patch(_PATCH_POST_ONBOARD, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_mark_complete_failure_continues(
        self,
        mock_profiles: AsyncMock,
        mock_post: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_emit: AsyncMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.find_one = AsyncMock(
            return_value={
                "_id": USER_ID,
                "email_memory_processed": False,
                "name": "Test",
                "email": "t@t.com",
            }
        )
        mock_users.update_one = AsyncMock()
        mock_search.return_value = {
            "messages": [{"id": "1"}],
            "nextPageToken": None,
        }
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_store.return_value = None
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        # Should still continue to post-onboarding
        mock_post.assert_awaited_once()
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
        mock_users.find_one = AsyncMock(return_value={"name": "Test"})
        mock_parallel.return_value = {"github": [], "twitter": []}

        result = await _extract_profiles_from_parallel_searches(USER_ID)
        assert result["profiles_stored"] == 0

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    async def test_handles_exception_gracefully(
        self, mock_parallel: AsyncMock, mock_users: MagicMock
    ) -> None:
        mock_users.find_one = AsyncMock(side_effect=RuntimeError("db down"))

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
    @patch(_PATCH_MEMORY_SERVICE)
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
        mock_crawl.return_value = {"content": "profile data", "error": None}
        mock_memory.store_memory_batch = AsyncMock(return_value=True)

        content = "Check out my github: https://github.com/johndoe"
        semaphore = asyncio.Semaphore(5)

        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", semaphore
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
        semaphore = asyncio.Semaphore(5)
        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", semaphore
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
        semaphore = asyncio.Semaphore(5)
        crawled_urls: set[str] = {"https://github.com/johndoe"}

        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", semaphore, crawled_urls=crawled_urls
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
        semaphore = asyncio.Semaphore(5)
        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", semaphore
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
    @patch(_PATCH_MEMORY_SERVICE)
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
        mock_crawl.return_value = {"content": None, "error": "timeout"}
        mock_memory.store_memory_batch = AsyncMock(return_value=True)

        content = "https://github.com/johndoe"
        semaphore = asyncio.Semaphore(5)
        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", semaphore
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

        content = "https://github.com/johndoe"
        semaphore = asyncio.Semaphore(5)
        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", semaphore
        )
        assert count == 0
