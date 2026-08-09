"""Unit tests for app.agents.memory.email_processor."""

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.llm.exceptions import LLMNotConfiguredError
from app.agents.memory.email_processor import (
    _discover_and_store_linked_profiles,
    _extract_profiles_from_parallel_searches,
    _process_single_platform,
    _search_platform_emails,
    _search_platform_emails_parallel,
    fetch_emails_for_onboarding,
    process_gmail_to_memory,
)
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
_PATCH_USERS = "app.agents.memory.email_processor.user_repository"
_PATCH_SEARCH = "app.agents.memory.email_processor.search_messages"
_PATCH_PROCESS = "app.agents.memory.email_processor.process_email_content"
_PATCH_STORE_EMAILS = "app.agents.memory.email_processor.store_emails_to_memory"
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
_PATCH_MEMORY_ENGINE = "app.agents.memory.email_processor.memory_engine"
_PATCH_SEARCH_PARALLEL = "app.agents.memory.email_processor._search_platform_emails_parallel"
_PATCH_SINGLE_PLATFORM = "app.agents.memory.email_processor._process_single_platform"

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
    "linkedin": {
        "sender_domains": ["linkedin.com"],
        "url_template": "https://linkedin.com/in/{username}",
        "regex_pattern": r"[\w-]{3,100}",
    },
    "medium": {
        "sender_domains": ["medium.com"],
        "url_template": "https://medium.com/@{username}",
        "regex_pattern": r"[a-zA-Z0-9_-]{3,50}",
    },
}


def _make_user(**overrides: Any) -> UserDocument:
    base: dict[str, Any] = {
        "id": USER_ID,
        "email_memory_processed": False,
        "name": "Test",
        "email": "t@t.com",
    }
    base.update(overrides)
    return UserDocument(**base)


def _search_response(messages: list[dict[str, Any]], next_token: str | None = None) -> GmailMessagesResponse:
    return GmailMessagesResponse(messages=messages, next_page_token=next_token)


async def _fake_discovery(value: int) -> int:
    """Stand-in for a discovery task that resolves to `value` stored profiles."""
    return value


async def _raise_discovery() -> int:
    raise RuntimeError("discovery crash")


# ---------------------------------------------------------------------------
# _search_platform_emails
# ---------------------------------------------------------------------------


class TestSearchPlatformEmails:
    """Tests for _search_platform_emails."""

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_messages(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}, {"id": "2"}])
        result = await _search_platform_emails(USER_ID, "github", "from:github.com")
        assert result == [{"id": "1"}, {"id": "2"}]
        mock_search.assert_awaited_once_with(
            user_id=USER_ID, query="from:github.com", max_results=10
        )

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_empty_on_no_messages(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[])
        result = await _search_platform_emails(USER_ID, "github", "from:github.com")
        assert result == []

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_returns_empty_on_exception(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = RuntimeError("API error")
        result = await _search_platform_emails(USER_ID, "github", "from:github.com")
        assert result == []

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_forwards_custom_max_results(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        await _search_platform_emails(USER_ID, "github", "q", max_results=7)
        mock_search.assert_awaited_once_with(user_id=USER_ID, query="q", max_results=7)


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
        assert result == {"github": [{"id": "g1"}], "twitter": [{"id": "t1"}, {"id": "t2"}]}
        assert mock_search.await_count == 2
        assert mock_search.await_args_list[0].kwargs == {
            "user_id": USER_ID,
            "query": "from:github.com OR from:notifications.github.com",
            "max_results": 10,
        }
        assert mock_search.await_args_list[1].kwargs == {
            "user_id": USER_ID,
            "query": "from:twitter.com OR from:x.com",
            "max_results": 10,
        }

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"sender_domains": ["github.com"]}},
    )
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_parallel_search_handles_exception(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = RuntimeError("fail")
        result = await _search_platform_emails_parallel(USER_ID)
        assert result == {"github": []}

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "github": {"sender_domains": ["github.com"]},
            "twitter": {"sender_domains": ["twitter.com"]},
        },
    )
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_parallel_search_mixed_failure(self, mock_search: AsyncMock) -> None:
        """A failing platform yields [] while a successful one keeps its emails."""
        mock_search.side_effect = [
            RuntimeError("boom"),
            GmailMessagesResponse(messages=[{"id": "t1"}]),
        ]
        result = await _search_platform_emails_parallel(USER_ID)
        assert result == {"github": [], "twitter": [{"id": "t1"}]}

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "github": {"sender_domains": ["github.com"]},
            "twitter": {"sender_domains": ["twitter.com"]},
        },
    )
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_parallel_search_non_list_result_becomes_empty(
        self, mock_search: AsyncMock
    ) -> None:
        """A search that returns neither a list nor an exception yields []."""
        mock_search.return_value = "not a list"
        result = await _search_platform_emails_parallel(USER_ID)
        assert result == {"github": [], "twitter": []}

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
        semaphore = asyncio.Semaphore()

        result = await _process_single_platform(
            USER_ID, "github", emails, semaphore, "Test User"
        )

        assert result["success"] is True
        assert result["platform"] == "github"
        assert result["url"] == "https://github.com/testuser"
        assert isinstance(result["discovery_task"], asyncio.Task)
        mock_extract.assert_awaited_once_with(
            "github", emails, "Test User", user_id=USER_ID
        )
        mock_crawl.assert_awaited_once_with(
            "https://github.com/testuser", "github", semaphore
        )
        mock_store.assert_awaited_once_with(
            USER_ID, "github", "https://github.com/testuser", "Profile content", "Test User"
        )

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
        assert result == {"error": "Invalid username 'bad!' for github"}

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
        assert result == {"error": "Could not build URL for github"}

    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_duplicate_url_skipped(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        crawled_urls: set[str] = {"https://github.com/testuser"}
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore(), crawled_urls=crawled_urls
        )
        assert result == {
            "error": "duplicate",
            "url": "https://github.com/testuser",
        }
        mock_crawl.assert_not_awaited()

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
        assert result == {"error": "timeout"}

    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_crawl_error_even_with_content_is_rejected(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        """An error flag wins even when content came back — both must be clean."""
        mock_crawl.return_value = {"content": "data", "error": "boom"}
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert result == {"error": "boom"}

    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_crawl_empty_content_error_none(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        """Empty content is rejected even when the error key is explicitly None."""
        mock_crawl.return_value = {"content": "", "error": None}
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert result == {"error": None}

    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_crawl_no_content_no_error_falls_back(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_crawl.return_value = {"content": None}
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert result == {"error": "Crawl failed"}

    @patch(
        _PATCH_EXTRACT_USER,
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM down"),
    )
    async def test_exception_returns_error(self, mock_extract: AsyncMock) -> None:
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert result == {"error": "LLM down"}

    @patch(_PATCH_CRAWL, new_callable=AsyncMock, side_effect=RuntimeError("crawl crash"))
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_crawl_raise_returns_error(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert result == {"error": "crawl crash"}

    @patch(_PATCH_STORE_PROFILE, new_callable=AsyncMock, side_effect=RuntimeError("store boom"))
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_store_raise_returns_error(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_store: AsyncMock,
    ) -> None:
        mock_crawl.return_value = {"content": "data", "error": None}
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert result == {"error": "store boom"}

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

        assert crawled_urls == {"https://github.com/testuser"}


# ---------------------------------------------------------------------------
# process_gmail_to_memory
# ---------------------------------------------------------------------------


class TestProcessGmailToMemory:
    """Tests for the main orchestrator function."""

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_already_processed_user_returns_early(
        self, mock_search: AsyncMock, mock_users: MagicMock
    ) -> None:
        mock_users.get = AsyncMock(
            return_value=_make_user(email_memory_processed=True)
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        result = await process_gmail_to_memory(USER_ID)
        assert result == {
            "total": 0,
            "successful": 0,
            "already_processed": True,
            "processing_complete": True,
        }
        mock_search.assert_not_awaited()
        mock_users.set_gmail_scan_timestamp.assert_not_awaited()

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
            return_value=_make_user(name="Test User", email="test@test.com")
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()

        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}, {"id": "2"}])
        mock_process.return_value = ([{"role": "user", "content": "email1"}], 0)
        mock_store.return_value = None
        mock_profiles.return_value = {"profiles_stored": 2}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 2
        assert result["successful"] == 1
        assert result["failed"] == 0
        assert result["profiles_stored"] == 2
        assert result["processing_complete"] is True
        mock_search.assert_awaited_once_with(
            user_id=USER_ID,
            query="in:inbox",
            max_results=50,
            page_token=None,
        )
        mock_process.assert_called_once_with([{"id": "1"}, {"id": "2"}])
        mock_store.assert_awaited_once_with(
            USER_ID, [{"role": "user", "content": "email1"}], "Test User", "test@test.com"
        )
        mock_mark.assert_awaited_once_with(USER_ID, 3)
        mock_users.set_gmail_scan_timestamp.assert_awaited_once()
        timestamp_arg = mock_users.set_gmail_scan_timestamp.await_args.args[1]
        assert isinstance(timestamp_arg, datetime)

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
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[])
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 0
        assert result["successful"] == 0
        assert result["failed"] == 0
        assert result["processing_complete"] is False
        mock_mark.assert_not_awaited()
        mock_users.set_gmail_scan_timestamp.assert_awaited_once()

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_handles_null_user(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        """If user not found in DB, should proceed without crashing."""
        mock_users.get = AsyncMock(return_value=None)
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 1

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_null_user_passes_none_attribution(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=None)
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_profiles.return_value = {"profiles_stored": 0}

        await process_gmail_to_memory(USER_ID)

        mock_store.assert_awaited_once_with(USER_ID, [{"role": "user", "content": "c"}], None, None)

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_skips_storage_when_batch_parses_to_nothing(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([], 1)
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["successful"] == 0
        assert result["failed"] == 1
        mock_store.assert_not_awaited()

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_paginates_until_next_page_token_runs_out(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.side_effect = [
            _search_response([{"id": "1"}], next_token="tok1"),
            _search_response([{"id": "2"}], next_token="tok2"),
            _search_response([]),
        ]
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 2
        assert mock_search.await_count == 3
        assert mock_search.await_args_list[1].kwargs["page_token"] == "tok1"
        assert mock_search.await_args_list[2].kwargs["page_token"] == "tok2"

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_stops_at_max_results_cap(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        """MAX_RESULTS (500) bounds the scan even when Gmail keeps paging."""
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        pages = [
            _search_response([{"id": f"{i}-{j}"} for j in range(50)], next_token=f"tok{i}")
            for i in range(10)
        ]
        mock_search.side_effect = pages
        mock_process.return_value = ([{"role": "user", "content": "c"}] * 50, 0)
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 500
        assert mock_search.await_count == 10
        for call in mock_search.await_args_list:
            assert call.kwargs["max_results"] == 50

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
            return_value=_make_user(
                integration_scan_states={"gmail": {"last_scan_timestamp": ts}}
            )
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[])
        mock_profiles.return_value = {"profiles_stored": 0}

        await process_gmail_to_memory(USER_ID)

        assert mock_search.await_args.kwargs["query"] == "in:inbox after:1735689600"

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_non_datetime_timestamp_keeps_plain_query(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        """A non-datetime stored timestamp must not produce a broken query."""
        mock_users.get = AsyncMock(
            return_value=_make_user(
                integration_scan_states={"gmail": {"last_scan_timestamp": "yesterday"}}
            )
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[])
        mock_profiles.return_value = {"profiles_stored": 0}

        await process_gmail_to_memory(USER_ID)

        assert mock_search.await_args.kwargs["query"] == "in:inbox"

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_non_dict_scan_states_keeps_plain_query(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.get.return_value.integration_scan_states = "garbage"  # type: ignore[assignment]
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[])
        mock_profiles.return_value = {"profiles_stored": 0}

        await process_gmail_to_memory(USER_ID)

        assert mock_search.await_args.kwargs["query"] == "in:inbox"

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_non_dict_gmail_state_keeps_plain_query(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(
            return_value=_make_user(integration_scan_states={"gmail": "garbage"})
        )
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[])
        mock_profiles.return_value = {"profiles_stored": 0}

        await process_gmail_to_memory(USER_ID)

        assert mock_search.await_args.kwargs["query"] == "in:inbox"

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
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_store.return_value = None
        mock_profiles.side_effect = RuntimeError("profile crash")

        result = await process_gmail_to_memory(USER_ID)

        assert result["successful"] == 1
        assert result["profiles_stored"] == 0
        assert result["extracted_profiles"] == []
        mock_mark.assert_awaited_once()

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_profile_result_without_keys_defaults_to_zero(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_profiles.return_value = {}

        result = await process_gmail_to_memory(USER_ID)

        assert result["profiles_stored"] == 0
        assert result["extracted_profiles"] == []

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_extracted_profiles_forwarded_and_mark_gets_combined_count(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        extracted = [{"platform": "github", "url": "https://github.com/a"}]
        mock_profiles.return_value = {"profiles_stored": 2, "extracted_profiles": extracted}

        result = await process_gmail_to_memory(USER_ID)

        assert result["extracted_profiles"] == extracted
        assert result["profiles_stored"] == 2
        mock_mark.assert_awaited_once_with(USER_ID, 3)

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_storage_task_failure_does_not_break_run(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_store.side_effect = RuntimeError("db down")
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["processing_complete"] is True
        assert result["successful"] == 1
        mock_mark.assert_awaited_once()

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_search_failure_returns_partial_results(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.side_effect = [
            _search_response([{"id": "1"}, {"id": "2"}], next_token="tok1"),
            RuntimeError("gmail down"),
        ]
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 2
        assert result["processing_complete"] is True

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_scan_timestamp_failure_continues(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock(side_effect=RuntimeError("ts down"))
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_store.return_value = None
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["processing_complete"] is True
        assert result["total"] == 1
        mock_users.set_gmail_scan_timestamp.assert_awaited_once()

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
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_store.return_value = None
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        # mark_email_processing_complete raised, but the function should
        # continue and still return a complete result
        assert result["processing_complete"] is True
        mock_users.set_gmail_scan_timestamp.assert_awaited_once()


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
        assert result == {"profiles_stored": 0}

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    async def test_handles_exception_gracefully(
        self, mock_parallel: AsyncMock, mock_users: MagicMock
    ) -> None:
        mock_users.get = AsyncMock(side_effect=RuntimeError("db down"))

        result = await _extract_profiles_from_parallel_searches(USER_ID)
        assert result == {"profiles_stored": 0, "extracted_profiles": []}

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_counts_profiles_and_discovered_links(
        self,
        mock_single: AsyncMock,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=UserDocument(name="Test"))
        mock_parallel.return_value = {
            "github": [{"id": "1"}],
            "twitter": [{"id": "2"}],
        }

        async def fake_impl(
            user_id: str,
            platform: str,
            emails: list[dict[str, Any]],
            semaphore: asyncio.Semaphore,
            user_name: str | None = None,
            crawled_urls: set[str] | None = None,
        ) -> dict[str, Any]:
            if platform == "github":
                return {
                    "success": True,
                    "platform": "github",
                    "url": "https://github.com/a",
                    "discovery_task": asyncio.create_task(_fake_discovery(3)),
                }
            return {
                "success": True,
                "platform": "twitter",
                "url": "https://x.com/b",
            }

        mock_single.side_effect = fake_impl

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {
            "profiles_stored": 5,
            "extracted_profiles": [
                {"platform": "github", "url": "https://github.com/a"},
                {"platform": "twitter", "url": "https://x.com/b"},
            ],
        }
        assert mock_single.await_count == 2
        first_call = mock_single.await_args_list[0]
        assert first_call.args[0] == USER_ID
        assert first_call.args[1] == "github"
        assert first_call.args[2] == [{"id": "1"}]
        assert isinstance(first_call.args[3], asyncio.Semaphore)
        assert first_call.args[4] == "Test"
        assert isinstance(first_call.args[5], set)
        second_call = mock_single.await_args_list[1]
        assert second_call.args[5] is first_call.args[5]

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_null_user_passes_none_name(
        self,
        mock_single: AsyncMock,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=None)
        mock_parallel.return_value = {"github": [{"id": "1"}]}
        mock_single.return_value = {
            "success": True,
            "platform": "github",
            "url": "https://github.com/a",
        }

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result["profiles_stored"] == 1
        assert mock_single.await_args.args[4] is None

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_platform_exception_is_skipped(
        self,
        mock_single: AsyncMock,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=UserDocument(name="Test"))
        mock_parallel.return_value = {
            "github": [{"id": "1"}],
            "twitter": [{"id": "2"}],
        }
        mock_single.side_effect = [RuntimeError("boom"), {"success": True, "platform": "twitter", "url": "https://x.com/b"}]

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {
            "profiles_stored": 1,
            "extracted_profiles": [{"platform": "twitter", "url": "https://x.com/b"}],
        }

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_empty_platform_is_excluded(
        self,
        mock_single: AsyncMock,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=UserDocument(name="Test"))
        mock_parallel.return_value = {"github": [{"id": "1"}], "twitter": []}
        mock_single.return_value = {
            "success": True,
            "platform": "github",
            "url": "https://github.com/a",
        }

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result["profiles_stored"] == 1
        assert mock_single.await_count == 1
        assert mock_single.await_args.args[1] == "github"

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_result_without_success_is_not_counted(
        self,
        mock_single: AsyncMock,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        """A non-success dict must be skipped without aborting the other platforms."""
        mock_users.get = AsyncMock(return_value=UserDocument(name="Test"))
        mock_parallel.return_value = {
            "github": [{"id": "1"}],
            "twitter": [{"id": "2"}],
        }
        mock_single.side_effect = [
            {"platform": "github", "url": "https://github.com/a"},
            {"success": True, "platform": "twitter", "url": "https://x.com/b"},
        ]

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {
            "profiles_stored": 1,
            "extracted_profiles": [{"platform": "twitter", "url": "https://x.com/b"}],
        }

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_discovery_failure_is_not_counted(
        self,
        mock_single: AsyncMock,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=UserDocument(name="Test"))
        mock_parallel.return_value = {"github": [{"id": "1"}]}
        mock_single.return_value = {
            "success": True,
            "platform": "github",
            "url": "https://github.com/a",
            "discovery_task": asyncio.create_task(_raise_discovery()),
        }

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {
            "profiles_stored": 1,
            "extracted_profiles": [{"platform": "github", "url": "https://github.com/a"}],
        }

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_discovery_non_int_result_is_ignored(
        self,
        mock_single: AsyncMock,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=UserDocument(name="Test"))
        mock_parallel.return_value = {"github": [{"id": "1"}]}
        mock_single.return_value = {
            "success": True,
            "platform": "github",
            "url": "https://github.com/a",
            "discovery_task": asyncio.create_task(_fake_discovery(7)),
        }

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result["profiles_stored"] == 8


# ---------------------------------------------------------------------------
# _discover_and_store_linked_profiles
# ---------------------------------------------------------------------------


class TestDiscoverAndStoreLinkedProfiles:
    """Tests for _discover_and_store_linked_profiles."""

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
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
        mock_crawl.return_value = {"content": "profile data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        content = "Check out my github: https://github.com/johndoe and more links after"
        semaphore = asyncio.Semaphore()

        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", semaphore
        )

        assert count == 1
        mock_crawl.assert_awaited_once_with("https://github.com/johndoe", "github", semaphore)
        mock_memory.retain.assert_awaited_once_with(
            USER_ID,
            [
                {
                    "role": "user",
                    "content": "User's github profile: https://github.com/johndoe\n\nprofile data\n",
                }
            ],
            source_type=MemorySourceType.EMAIL,
            extraction_hints=(
                "These are the user's own social profiles, discovered from their "
                "twitter emails. Extract durable facts about the user: "
                "handles, bio, role, projects, interests, and location."
            ),
        )

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_discovers_multiple_platforms(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.side_effect = [
            "https://github.com/johndoe",
            "https://linkedin.com/in/johndoe",
        ]
        mock_crawl.return_value = {"content": "data", "error": None}

        with patch(_PATCH_MEMORY_ENGINE) as mock_memory:
            mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=2))
            content = "links: https://github.com/johndoe and https://linkedin.com/in/johndoe"
            count = await _discover_and_store_linked_profiles(
                USER_ID, content, "twitter", asyncio.Semaphore()
            )

        assert count == 2
        assert mock_crawl.await_count == 2
        assert mock_memory.retain.await_count == 1
        assert len(mock_memory.retain.await_args.args[1]) == 2

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_deduplicates_repeated_mentions(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}

        with patch(_PATCH_MEMORY_ENGINE) as mock_memory:
            mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))
            content = "https://github.com/johndoe and again https://github.com/johndoe"
            count = await _discover_and_store_linked_profiles(
                USER_ID, content, "twitter", asyncio.Semaphore()
            )

        assert count == 1
        mock_crawl.assert_awaited_once()
        assert len(mock_memory.retain.await_args.args[1]) == 1

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_matches_case_insensitively_and_without_scheme(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}

        with patch(_PATCH_MEMORY_ENGINE) as mock_memory:
            mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))
            content = "see WWW.GITHUB.COM/JOHNDOE and github.com/JOHNDOE"
            count = await _discover_and_store_linked_profiles(
                USER_ID, content, "twitter", asyncio.Semaphore()
            )

        assert count == 1
        assert mock_crawl.await_count == 1

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_matches_at_prefix_style_urls(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://medium.com/@johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}

        with patch(_PATCH_MEMORY_ENGINE) as mock_memory:
            mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))
            content = "blog: https://medium.com/@johndoe"
            count = await _discover_and_store_linked_profiles(
                USER_ID, content, "twitter", asyncio.Semaphore()
            )

        assert count == 1

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_matches_in_path_style_urls(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://linkedin.com/in/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}

        with patch(_PATCH_MEMORY_ENGINE) as mock_memory:
            mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))
            content = "linkedin: https://linkedin.com/in/johndoe"
            count = await _discover_and_store_linked_profiles(
                USER_ID, content, "twitter", asyncio.Semaphore()
            )

        assert count == 1

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_skips_invalid_usernames(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_validate.side_effect = lambda username, platform: username != "123"
        mock_build.side_effect = lambda username, platform: f"https://github.com/{username}"
        mock_crawl.return_value = {"content": "data", "error": None}
        semaphore = asyncio.Semaphore()

        with patch(_PATCH_MEMORY_ENGINE) as mock_memory:
            mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))
            content = "https://github.com/johndoe and https://github.com/123"
            count = await _discover_and_store_linked_profiles(
                USER_ID, content, "twitter", semaphore
            )

        assert count == 1
        mock_crawl.assert_awaited_once_with("https://github.com/johndoe", "github", semaphore)

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

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_skips_already_crawled_urls(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        content = "https://github.com/johndoe"
        crawled_urls: set[str] = {"https://github.com/johndoe"}

        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", asyncio.Semaphore(), crawled_urls=crawled_urls
        )
        assert count == 0
        mock_crawl.assert_not_awaited()

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_populates_crawled_urls(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}
        crawled_urls: set[str] = set()

        with patch(_PATCH_MEMORY_ENGINE) as mock_memory:
            mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))
            await _discover_and_store_linked_profiles(
                USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore(), crawled_urls=crawled_urls
            )

        assert crawled_urls == {"https://github.com/johndoe"}

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    async def test_skips_same_platform(self) -> None:
        """Profiles from the same platform as source should be skipped."""
        content = "https://x.com/otheruser"
        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", asyncio.Semaphore()
        )
        assert count == 0

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_skips_same_domain_different_platform_key(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        """A github source must not crawl github.com links found in its content."""
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/someuser"
        content = "https://github.com/someuser"

        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "github", asyncio.Semaphore()
        )
        assert count == 0
        mock_crawl.assert_not_awaited()

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_crawl_failure_yields_zero(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        # crawl_profile_url returns a single dict with error set
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": None, "error": "timeout"}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        content = "https://github.com/johndoe"
        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", asyncio.Semaphore()
        )
        assert count == 0
        mock_memory.retain.assert_not_awaited()

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock, side_effect=RuntimeError("crawl crash"))
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_crawl_exception_yields_zero(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore()
        )
        assert count == 0

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_zero_facts_extracted_returns_zero(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        # crawl_profile_url returns a single dict with content
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=0))

        content = "https://github.com/johndoe"
        count = await _discover_and_store_linked_profiles(
            USER_ID, content, "twitter", asyncio.Semaphore()
        )
        assert count == 0

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_retain_failure_yields_zero(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(side_effect=RuntimeError("retain down"))

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore()
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
        await fetch_emails_for_onboarding(USER_ID, include_sent=True)
        query = mock_search.await_args.kwargs["query"]
        assert query == "(in:inbox OR in:sent) newer_than:30d"

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_months_scales_the_recency_window(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[])
        await fetch_emails_for_onboarding(USER_ID, months=3, include_sent=True)
        assert mock_search.await_args.kwargs["query"] == "(in:inbox OR in:sent) newer_than:90d"


class TestFetchEmailsForOnboarding:
    """Pagination, batching, callbacks, and metadata/full formats."""

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_paginates_with_page_token(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = [
            _search_response([{"id": "1"}], next_token="tok1"),
            _search_response([{"id": "2"}], next_token="tok2"),
            _search_response([]),
        ]
        result = await fetch_emails_for_onboarding(USER_ID, max_total=10)
        assert [e["id"] for e in result] == ["1", "2"]
        assert mock_search.await_count == 3
        assert mock_search.await_args_list[0].kwargs["page_token"] is None
        assert mock_search.await_args_list[1].kwargs["page_token"] == "tok1"
        assert mock_search.await_args_list[2].kwargs["page_token"] == "tok2"

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_stops_without_page_token_even_if_batch_full(
        self, mock_search: AsyncMock
    ) -> None:
        mock_search.side_effect = [
            _search_response([{"id": "1"}, {"id": "2"}]),
            _search_response([{"id": "3"}]),
        ]
        result = await fetch_emails_for_onboarding(USER_ID, max_total=10)
        assert len(result) == 2
        assert mock_search.await_count == 1

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_breaks_on_empty_first_batch(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = _search_response([])
        result = await fetch_emails_for_onboarding(USER_ID, max_total=10)
        assert result == []
        assert mock_search.await_count == 1

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_max_total_caps_batch_sizes(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = [
            _search_response([{"id": f"p1-{i}"} for i in range(100)], next_token="tok1"),
            _search_response([{"id": f"p2-{i}"} for i in range(50)], next_token="tok2"),
            _search_response([{"id": "extra"}], next_token="tok3"),
        ]
        result = await fetch_emails_for_onboarding(
            USER_ID, max_total=150, batch_size=100
        )
        assert len(result) == 150
        assert mock_search.await_count == 2
        assert mock_search.await_args_list[0].kwargs["max_results"] == 100
        assert mock_search.await_args_list[1].kwargs["max_results"] == 50

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_metadata_format_sets_payload_flags(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = _search_response([])
        await fetch_emails_for_onboarding(USER_ID, fmt="metadata")
        kwargs = mock_search.await_args.kwargs
        assert kwargs["format"] == "metadata"
        assert kwargs["include_payload"] is False
        assert kwargs["verbose"] is False

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_full_format_sets_payload_flags(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = _search_response([])
        await fetch_emails_for_onboarding(USER_ID, fmt="full")
        kwargs = mock_search.await_args.kwargs
        assert kwargs["format"] == "full"
        assert kwargs["include_payload"] is True
        assert kwargs["verbose"] is True

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_on_batch_receives_count_and_sender(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = _search_response(
            [
                {"id": "1", "from": "Alice <alice@x.com>"},
                {"id": "2", "from": "Bob <bob@x.com>"},
            ]
        )
        on_batch = AsyncMock()
        result = await fetch_emails_for_onboarding(USER_ID, max_total=10, on_batch=on_batch)
        assert len(result) == 2
        on_batch.assert_awaited_once_with(2, "Bob")
        assert isinstance(on_batch.await_args.args[0], int)
        assert on_batch.await_args.args[1] == "Bob"

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_on_batch_uses_sender_fallback_and_none(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = _search_response(
            [{"id": "1", "sender": "Carol <carol@x.com>"}]
        )
        on_batch = AsyncMock()
        await fetch_emails_for_onboarding(USER_ID, max_total=10, on_batch=on_batch)
        on_batch.assert_awaited_once_with(1, "Carol")

        mock_search.return_value = _search_response([{"id": "2"}])
        on_batch = AsyncMock()
        await fetch_emails_for_onboarding(USER_ID, max_total=10, on_batch=on_batch)
        on_batch.assert_awaited_once_with(1, None)

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_on_batch_fires_per_page(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = [
            _search_response([{"id": "1", "from": "A <a@x.com>"}], next_token="tok1"),
            _search_response([{"id": "2", "from": "B <b@x.com>"}], next_token="tok2"),
            _search_response([]),
        ]
        on_batch = AsyncMock()
        await fetch_emails_for_onboarding(USER_ID, max_total=10, on_batch=on_batch)
        assert on_batch.await_count == 2
        assert on_batch.await_args_list[0].args == (1, "A")
        assert on_batch.await_args_list[1].args == (2, "B")

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_appends_to_provided_list_live(self, mock_search: AsyncMock) -> None:
        into: list[dict[str, Any]] = []
        mock_search.side_effect = [
            _search_response([{"id": "1"}], next_token="tok1"),
            _search_response([{"id": "2"}]),
        ]
        result = await fetch_emails_for_onboarding(USER_ID, max_total=10, into=into)
        assert result is into
        assert [e["id"] for e in into] == ["1", "2"]

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_search_failure_returns_partial_results(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = [
            _search_response([{"id": "1"}], next_token="tok1"),
            RuntimeError("gmail down"),
        ]
        result = await fetch_emails_for_onboarding(USER_ID, max_total=10)
        assert [e["id"] for e in result] == ["1"]

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_initial_failure_returns_empty(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = RuntimeError("gmail down")
        result = await fetch_emails_for_onboarding(USER_ID)
        assert result == []

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_display_name_quoted_and_truncated(self, mock_search: AsyncMock) -> None:
        long_name = "X" * 40
        mock_search.return_value = _search_response(
            [{"id": "1", "from": '"Some Name" <s@x.com>'}]
        )
        on_batch = AsyncMock()
        await fetch_emails_for_onboarding(USER_ID, max_total=10, on_batch=on_batch)
        assert on_batch.await_args.args[1] == "Some Name"

        mock_search.return_value = _search_response(
            [{"id": "2", "from": f"{long_name} <l@x.com>"}]
        )
        on_batch = AsyncMock()
        await fetch_emails_for_onboarding(USER_ID, max_total=10, on_batch=on_batch)
        assert len(on_batch.await_args.args[1]) == 30
        assert on_batch.await_args.args[1] == "X" * 30

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_display_name_edge_cases(self, mock_search: AsyncMock) -> None:
        cases = [
            ({"id": "1", "from": "<only@x.com>"}, "only"),
            ({"id": "2", "from": "just@x.com"}, "just@x.com"),
            ({"id": "3", "from": ""}, None),
        ]
        for message, expected in cases:
            mock_search.return_value = _search_response([message])
            on_batch = AsyncMock()
            await fetch_emails_for_onboarding(USER_ID, max_total=10, on_batch=on_batch)
            assert on_batch.await_args.args[1] == expected


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
                USER_ID, fmt="full", include_sent=True, max_total=10
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
            "app.services.onboarding.social_profile_service.get_default_llm",
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
            "app.services.onboarding.social_profile_service.get_default_llm",
            side_effect=LLMNotConfiguredError("no llm"),
        ):
            profiles = await extract_social_profiles_from_emails(emails, "Octo Cat", None)
        assert profiles == []
