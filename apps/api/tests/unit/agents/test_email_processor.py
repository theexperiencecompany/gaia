"""Unit tests for app.agents.memory.email_processor."""

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.llm.exceptions import LLMNotConfiguredError
from app.agents.memory.email_processor import (
    _discover_and_store_linked_profiles,
    _extract_display_name,
    _extract_profiles_from_parallel_searches,
    _process_single_platform,
    _search_platform_emails,
    _search_platform_emails_parallel,
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
_PATCH_DISCOVER_LINKED = "app.agents.memory.email_processor._discover_and_store_linked_profiles"
_PATCH_LOG = "app.agents.memory.email_processor.log"

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


def _search_response(
    messages: list[dict[str, Any]], next_token: str | None = None
) -> GmailMessagesResponse:
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

        result = await _process_single_platform(USER_ID, "github", emails, semaphore, "Test User")

        assert result["success"] is True
        assert result["platform"] == "github"
        assert result["url"] == "https://github.com/testuser"
        assert isinstance(result["discovery_task"], asyncio.Task)
        mock_extract.assert_awaited_once_with("github", emails, "Test User", user_id=USER_ID)
        mock_crawl.assert_awaited_once_with("https://github.com/testuser", "github", semaphore)
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
        mock_users.get = AsyncMock(return_value=_make_user(email_memory_processed=True))
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
        mock_users.get = AsyncMock(return_value=_make_user(name="Test User", email="test@test.com"))
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
            return_value=_make_user(integration_scan_states={"gmail": {"last_scan_timestamp": ts}})
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
        mock_single.side_effect = [
            RuntimeError("boom"),
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

        count = await _discover_and_store_linked_profiles(USER_ID, content, "twitter", semaphore)

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
                USER_ID,
                "https://github.com/johndoe",
                "twitter",
                asyncio.Semaphore(),
                crawled_urls=crawled_urls,
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
        assert mock_search.await_args.kwargs["user_id"] == USER_ID

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
        result = await fetch_emails_for_onboarding(USER_ID, max_total=150, batch_size=100)
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
        mock_search.return_value = _search_response([{"id": "1", "sender": "Carol <carol@x.com>"}])
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
        mock_search.return_value = _search_response([{"id": "1", "from": '"Some Name" <s@x.com>'}])
        on_batch = AsyncMock()
        await fetch_emails_for_onboarding(USER_ID, max_total=10, on_batch=on_batch)
        assert on_batch.await_args.args[1] == "Some Name"

        mock_search.return_value = _search_response([{"id": "2", "from": f"{long_name} <l@x.com>"}])
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


# ---------------------------------------------------------------------------
# _StepTimer
# ---------------------------------------------------------------------------


class TestStepTimer:
    """Direct tests for the _StepTimer timing-summary helper."""

    @patch("app.agents.memory.email_processor.time.monotonic", return_value=100.0)
    def test_record_appends_label_and_elapsed(self, mock_monotonic: MagicMock) -> None:
        timer = _StepTimer()
        timer.record("fetch", 1.25)
        timer.record("parse", 2.5)
        assert timer._steps == [("fetch", 1.25), ("parse", 2.5)]

    @patch("app.agents.memory.email_processor.time.monotonic", return_value=100.0)
    def test_summary_contains_labels_elapsed_and_total(self, mock_monotonic: MagicMock) -> None:
        timer = _StepTimer()
        timer.record("fetch", 1.5)
        timer.record("parse", 2.25)
        summary = timer.summary()
        assert "ONBOARDING EMAIL PIPELINE" in summary
        assert "TIMING BREAKDOWN" in summary
        assert "fetch" in summary
        assert "parse" in summary
        assert "1.5s" in summary
        assert "2.2s" in summary  # elapsed renders with one decimal
        assert "TOTAL" in summary

    def test_summary_total_uses_wall_time_since_construction(self) -> None:
        timer = _StepTimer()
        timer._start = 100.0  # dataclass default_factory captured the real monotonic
        timer.record("fetch", 1.5)
        with patch("app.agents.memory.email_processor.time.monotonic", return_value=110.0):
            summary = timer.summary()
        assert "10.0s" in summary  # 110.0 - 100.0 construction timestamp

    @patch("app.agents.memory.email_processor.time.monotonic", return_value=0.0)
    def test_summary_bar_scales_with_elapsed_and_caps_at_20(
        self, mock_monotonic: MagicMock
    ) -> None:
        timer = _StepTimer()
        timer.record("short", 10.0)  # 10/2 = 5 blocks
        timer.record("long", 999.0)  # capped at 20 blocks
        summary = timer.summary()
        lines = summary.splitlines()
        short_line = next(line for line in lines if "short" in line)
        long_line = next(line for line in lines if "long" in line)
        assert short_line.count("█") == 5
        assert long_line.count("█") == 20

    @patch("app.agents.memory.email_processor.time.monotonic", return_value=0.0)
    def test_summary_renders_elapsed_with_one_decimal(self, mock_monotonic: MagicMock) -> None:
        timer = _StepTimer()
        timer.record("parse", 1.23456)
        summary = timer.summary()
        assert "1.2s" in summary
        assert "1.23456s" not in summary


# ---------------------------------------------------------------------------
# _extract_display_name
# ---------------------------------------------------------------------------


class TestExtractDisplayName:
    """Direct tests for the display-name helper used by fetch_emails_for_onboarding."""

    def test_empty_returns_empty(self) -> None:
        assert _extract_display_name("") == ""

    def test_plain_email_without_display_name(self) -> None:
        assert _extract_display_name("alice@example.com") == "alice@example.com"

    def test_angle_bracketed_email_only(self) -> None:
        assert _extract_display_name("<alice@example.com>") == "alice"

    def test_named_sender(self) -> None:
        assert _extract_display_name("Alice Smith <alice@example.com>") == "Alice Smith"

    def test_quoted_display_name_is_unquoted(self) -> None:
        assert _extract_display_name('"Alice Smith" <alice@example.com>') == "Alice Smith"

    def test_whitespace_is_stripped(self) -> None:
        assert _extract_display_name('  "Alice Smith"  <alice@example.com>') == "Alice Smith"

    def test_truncated_to_30_chars(self) -> None:
        long_name = "X" * 40
        assert _extract_display_name(f"{long_name} <x@example.com>") == "X" * 30

    def test_name_with_angle_content_falls_back_to_email_prefix(self) -> None:
        assert _extract_display_name("<a@b.com> trailing") == "a"


# ---------------------------------------------------------------------------
# _search_platform_emails_parallel — query construction details
# ---------------------------------------------------------------------------


class TestSearchPlatformEmailsParallelQueries:
    """Query strings built per platform from sender_domains."""

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"sender_domains": ["github.com"]}},
    )
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_single_domain_builds_simple_query(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "g1"}])
        result = await _search_platform_emails_parallel(USER_ID)
        assert result == {"github": [{"id": "g1"}]}
        assert mock_search.await_args.kwargs["query"] == "from:github.com"

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"sender_domains": ["a.github.com", "b.github.com", "c.github.com"]}},
    )
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_multiple_domains_join_with_or(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = GmailMessagesResponse(messages=[])
        await _search_platform_emails_parallel(USER_ID)
        assert (
            mock_search.await_args.kwargs["query"]
            == "from:a.github.com OR from:b.github.com OR from:c.github.com"
        )


# ---------------------------------------------------------------------------
# process_gmail_to_memory — remaining-cap batch sizing
# ---------------------------------------------------------------------------


class TestProcessGmailToMemoryBatchSizing:
    """The final page must be capped by the remaining MAX_RESULTS budget."""

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_final_partial_batch_uses_remaining_budget(
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
        pages = [
            _search_response([{"id": f"p{i}-{j}"} for j in range(50)], next_token=f"tok{i}")
            for i in range(9)
        ]
        pages.append(_search_response([{"id": f"p9-{j}"} for j in range(40)], next_token="tok9"))
        pages.append(_search_response([{"id": f"p10-{j}"} for j in range(10)]))
        mock_search.side_effect = pages
        mock_process.return_value = ([{"role": "user", "content": "c"}], 0)
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 500
        assert mock_search.await_count == 11
        # Full 50-wide batches while the budget allows, then exactly what remains.
        for call in mock_search.await_args_list[:10]:
            assert call.kwargs["max_results"] == 50
        assert mock_search.await_args_list[10].kwargs["max_results"] == 10
        # mark-complete gets parsed (1 per mocked batch) + profiles stored.
        mock_mark.assert_awaited_once_with(USER_ID, 11)


# ---------------------------------------------------------------------------
# _process_single_platform — crawl result shape edge cases
# ---------------------------------------------------------------------------


class TestProcessSinglePlatformCrawlShape:
    """How odd crawl_result shapes flow through the error handling."""

    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_crawl_result_missing_content_key_returns_error(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        """A crawl result without a content key must not crash the pipeline."""
        mock_crawl.return_value = {"error": None}
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        # The KeyError is caught by the outer handler and surfaced as its repr.
        assert result == {"error": "'content'"}


# ---------------------------------------------------------------------------
# _discover_and_store_linked_profiles — more crawl/retain edge cases
# ---------------------------------------------------------------------------


class TestDiscoverAndStoreLinkedProfilesCrawlShapes:
    """Additional crawl-result shapes for the discovery path."""

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_content_with_error_flag_is_not_stored(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        """An error flag wins even when content came back."""
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": "boom"}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore()
        )
        assert count == 0
        mock_memory.retain.assert_not_awaited()

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_non_dict_crawl_result_is_ignored(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = "not a dict"
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore()
        )
        assert count == 0
        mock_memory.retain.assert_not_awaited()

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
                "regex_pattern": r"^[a-zA-Z0-9-]{1,39}$",
            },
        },
    )
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_anchored_regex_patterns_are_stripped_for_url_matching(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        """regex_pattern anchors (^/$) must not leak into the URL match."""
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        count = await _discover_and_store_linked_profiles(
            USER_ID,
            "https://github.com/johndoe and more text after the link",
            "twitter",
            asyncio.Semaphore(),
        )
        assert count == 1
        assert mock_crawl.await_count == 1
        assert mock_crawl.await_args.args[0] == "https://github.com/johndoe"
        assert mock_crawl.await_args.args[1] == "github"


# ---------------------------------------------------------------------------
# _process_single_platform — discovery-task wiring & error logging
# ---------------------------------------------------------------------------

_SHARED_DOMAIN_CONFIG = {
    "twitter": {
        "sender_domains": ["twitter.com"],
        "url_template": "https://x.com/{username}",
        "regex_pattern": r"[a-zA-Z0-9_]{1,15}",
    },
    "x": {
        "sender_domains": ["x.com"],
        "url_template": "https://x.com/{username}",
        "regex_pattern": r"[a-zA-Z0-9_]{1,15}",
    },
    "github": {
        "sender_domains": ["github.com"],
        "url_template": "https://github.com/{username}",
        "regex_pattern": r"[a-zA-Z0-9-]{1,39}",
    },
}


class TestProcessSinglePlatformDiscoveryWiring:
    """The follow-up discovery task must receive every processed input."""

    @patch(_PATCH_DISCOVER_LINKED, new_callable=AsyncMock, return_value=0)
    @patch(_PATCH_STORE_PROFILE, new_callable=AsyncMock)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_discovery_task_receives_all_inputs(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_store: AsyncMock,
        mock_discover: AsyncMock,
    ) -> None:
        mock_crawl.return_value = {"content": "Profile content", "error": None}
        semaphore = asyncio.Semaphore()
        crawled_urls: set[str] = set()

        result = await _process_single_platform(
            USER_ID,
            "github",
            [{"id": "1"}],
            semaphore,
            "Test User",
            crawled_urls=crawled_urls,
        )

        assert result["success"] is True
        assert isinstance(result["discovery_task"], asyncio.Task)
        await result["discovery_task"]
        mock_discover.assert_awaited_once_with(
            USER_ID, "Profile content", "github", semaphore, crawled_urls
        )


class TestProcessSinglePlatformErrorLogging:
    """The exception path must report the exact failure to the log."""

    @patch(_PATCH_LOG)
    @patch(
        _PATCH_EXTRACT_USER,
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM down"),
    )
    async def test_exception_logs_exact_error(
        self, mock_extract: AsyncMock, mock_log: MagicMock
    ) -> None:
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert result == {"error": "LLM down"}
        mock_log.error.assert_called_once_with(
            f"{LogTag.MEMORY} Error processing platform profile",
            platform="github",
            error_type="RuntimeError",
            error="LLM down",
            user_id=USER_ID,
        )


# ---------------------------------------------------------------------------
# _discover_and_store_linked_profiles — source-domain semantics
# ---------------------------------------------------------------------------


class TestDiscoverAndStoreLinkedProfilesSourceDomain:
    """Same-domain skipping must use the source platform's resolved domain."""

    @patch(_PATCH_PLATFORM_CONFIG, _SHARED_DOMAIN_CONFIG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_shared_domain_platform_is_skipped(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        """A second platform key sharing the source domain must not be crawled."""
        mock_validate.return_value = True
        mock_build.return_value = "https://x.com/otheruser"
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://x.com/otheruser", "twitter", asyncio.Semaphore()
        )
        assert count == 0
        mock_crawl.assert_not_awaited()
        mock_memory.retain.assert_not_awaited()

    @patch(_PATCH_PLATFORM_CONFIG, _SHARED_DOMAIN_CONFIG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_skip_does_not_abort_later_platforms(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        """The same-domain skip must continue the scan, not break it."""
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore()
        )
        assert count == 1
        mock_crawl.assert_awaited_once_with(
            "https://github.com/johndoe", "github", mock_crawl.await_args.args[2]
        )
        mock_memory.retain.assert_awaited_once()

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "twitter": {
                "sender_domains": ["twitter.com"],
                "url_template": "https://x.com",
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
    async def test_short_source_template_still_yields_domain(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        """The source domain comes from the third URL segment, not beyond it."""
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore()
        )
        assert count == 1


# ---------------------------------------------------------------------------
# _discover_and_store_linked_profiles — match/validate/build semantics
# ---------------------------------------------------------------------------


class TestDiscoverAndStoreLinkedProfilesMatchSemantics:
    """Case handling and platform propagation in the discovery pipeline."""

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
                "regex_pattern": r"[a-z0-9-]{1,39}",
            },
        },
    )
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_username_matching_is_case_insensitive(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        """A lowercase-only pattern must still match an uppercase URL."""
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/JOHNDOE", "twitter", asyncio.Semaphore()
        )
        assert count == 1

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_validate_receives_the_matching_platform(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        """Validation must run against the platform that matched the URL."""
        mock_validate.side_effect = lambda username, platform: platform == "github"
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore()
        )
        assert count == 1
        mock_validate.assert_any_call("johndoe", "github")

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_build_url_receives_the_matching_platform(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        """URL building must use the platform that matched the URL."""
        mock_validate.return_value = True
        mock_build.side_effect = (
            lambda username, platform: f"https://github.com/{username}"
            if platform == "github"
            else None
        )
        mock_crawl.side_effect = (
            lambda url, platform, semaphore: {"content": "data", "error": None}
            if url
            else {"content": None, "error": "no url"}
        )
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore()
        )
        assert count == 1
        mock_build.assert_any_call("johndoe", "github")

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_one_failed_crawl_does_not_drop_successful_ones(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        """A raising crawl must not abort storage of the profiles that succeeded."""
        mock_validate.return_value = True
        mock_build.side_effect = [
            "https://github.com/johndoe",
            "https://linkedin.com/in/johndoe",
        ]
        mock_crawl.side_effect = [
            {"content": "data", "error": None},
            RuntimeError("crawl crash"),
        ]
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        count = await _discover_and_store_linked_profiles(
            USER_ID,
            "links: https://github.com/johndoe and https://linkedin.com/in/johndoe",
            "twitter",
            asyncio.Semaphore(),
        )
        assert count == 1
        assert mock_memory.retain.await_count == 1
        assert len(mock_memory.retain.await_args.args[1]) == 1


# ---------------------------------------------------------------------------
# _discover_and_store_linked_profiles — exact log contracts
# ---------------------------------------------------------------------------


class TestDiscoverAndStoreLinkedProfilesLogging:
    """Every log line in the discovery path must carry its exact payload."""

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_LOG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_stored_profiles_logs_exact_payload(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=1))

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore()
        )
        assert count == 1
        mock_log.info.assert_called_once_with(
            f"{LogTag.MEMORY} Stored discovered profiles",
            profile_count=1,
            source_platform="twitter",
            user_id=USER_ID,
        )

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_LOG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_no_facts_extracted_logs_exact_payload(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_validate.return_value = True
        mock_build.return_value = "https://github.com/johndoe"
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=0))

        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore()
        )
        assert count == 0
        mock_log.warning.assert_called_once_with(
            f"{LogTag.MEMORY} No facts extracted from discovered profiles",
            source_platform="twitter",
            user_id=USER_ID,
        )

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_LOG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, side_effect=RuntimeError("build crash"))
    @patch(_PATCH_VALIDATE, return_value=True)
    async def test_exception_logs_exact_payload(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_log: MagicMock,
    ) -> None:
        count = await _discover_and_store_linked_profiles(
            USER_ID, "https://github.com/johndoe", "twitter", asyncio.Semaphore()
        )
        assert count == 0
        mock_log.error.assert_called_once_with(
            f"{LogTag.MEMORY} Error discovering linked profiles",
            source_platform="twitter",
            error_type="RuntimeError",
            error="build crash",
            user_id=USER_ID,
        )


class TestProcessSinglePlatformSuccessLogging:
    """Success-path log lines must carry their exact payloads (timers pinned)."""

    @patch(_PATCH_DISCOVER_LINKED, new_callable=AsyncMock, return_value=0)
    @patch(_PATCH_LOG)
    @patch("app.agents.memory.email_processor.time.monotonic")
    @patch(_PATCH_STORE_PROFILE, new_callable=AsyncMock)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_success_logs_carry_exact_timers_and_platform(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_store: AsyncMock,
        mock_monotonic: MagicMock,
        mock_log: MagicMock,
        mock_discover: AsyncMock,
    ) -> None:
        # t0_platform, t0_llm, llm_elapsed, t0_crawl, crawl_elapsed,
        # t0_store, store_elapsed, final total = 8 calls; anything beyond
        # (e.g. the discovery task) must not consume the pinned sequence.
        # llm and crawl elapsed are 1.2345 so round(x, 1) != round(x, 2).
        values = [100.0, 100.0, 101.2345, 100.0, 101.2345, 101.5, 101.75, 101.2345]
        state = {"i": 0}

        def _mono() -> float:
            i = state["i"]
            state["i"] += 1
            return values[i] if i < len(values) else 100.0

        mock_monotonic.side_effect = _mono
        mock_crawl.return_value = {"content": "Profile content", "error": None}
        semaphore = asyncio.Semaphore()

        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], semaphore, "Test User"
        )

        assert result["success"] is True
        # crawl_elapsed = 101.2345 - 100.0 = 1.2345 -> one decimal (1.2),
        # two decimals (1.23) must NOT be what the log carries.
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Profile crawl finished",
            platform="github",
            duration_s=1.2,
            success=True,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} LLM username extraction completed",
            platform="github",
            duration_s=1.2,
            username="testuser",
        )
        # store_elapsed = 101.75 - 101.5 = 0.25 -> one decimal (0.2).
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Memory profile store finished",
            platform="github",
            duration_s=0.2,
        )
        # total = 101.2345 - 100.0 = 1.2345 -> 1.2; llm = 1.2; crawl = 1.2;
        # store = 0.2. All carry 2 decimals so round(x, 1) != round(x, 2).
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Platform profile processing finished",
            platform="github",
            total_s=1.2,
            llm_s=1.2,
            crawl_s=1.2,
            store_s=0.2,
        )

        # The mocked discovery task resolves immediately.
        await result["discovery_task"]
        mock_discover.assert_awaited_once()


class TestProcessSinglePlatformBuildSeam:
    """The URL builder must receive the extracted username and the platform."""

    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_build_url_requires_username_and_platform(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
    ) -> None:
        mock_build.side_effect = (
            lambda username, platform: "https://github.com/testuser"
            if username == "testuser" and platform == "github"
            else None
        )
        mock_crawl.return_value = {"content": "Profile content", "error": None}

        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore(), "Test User"
        )

        assert result["success"] is True
        assert result["url"] == "https://github.com/testuser"
        mock_build.assert_called_once_with("testuser", "github")

        # Clean up the discovery task.
        if "discovery_task" in result:
            result["discovery_task"].cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await result["discovery_task"]


class TestProcessSinglePlatformWarningLogs:
    """The skip-path warnings must carry their exact payloads."""

    @patch(_PATCH_LOG)
    @patch(_PATCH_BUILD_URL, return_value=None)
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_no_url_warning_logs_exact_payload(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert result == {"error": "Could not build URL for github"}
        mock_log.warning.assert_called_once_with(
            f"{LogTag.MEMORY} Could not build profile URL",
            platform="github",
            username="testuser",
        )

    @patch(_PATCH_LOG)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE, return_value=True)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_crawl_failure_warning_logs_exact_payload(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_log: MagicMock,
    ) -> None:
        mock_crawl.return_value = {"content": None, "error": "timeout"}
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert result == {"error": "timeout"}
        mock_log.warning.assert_called_once_with(
            f"{LogTag.MEMORY} Failed to crawl profile",
            platform="github",
            error="timeout",
        )


class TestDiscoverAndStoreLinkedProfilesDedupeContinue:
    """The dedupe skip must continue scanning, not abort the username loop."""

    @patch(_PATCH_PLATFORM_CONFIG, _DISCOVERY_CONFIG)
    @patch(_PATCH_MEMORY_ENGINE)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL)
    @patch(_PATCH_VALIDATE)
    async def test_dedupe_skip_does_not_abort_later_usernames(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_memory: MagicMock,
    ) -> None:
        """A repeated URL must be skipped, but the next username still processed."""
        mock_validate.return_value = True
        mock_build.side_effect = [
            "https://github.com/johndoe",  # first mention
            "https://github.com/johndoe",  # duplicate (build runs before dedupe)
            "https://github.com/janedoe",  # after the duplicate, same platform
        ]
        mock_crawl.return_value = {"content": "data", "error": None}
        mock_memory.retain = AsyncMock(return_value=MagicMock(facts_extracted=2))

        content = "https://github.com/johndoe https://github.com/johndoe https://github.com/janedoe"
        count = await _discover_and_store_linked_profiles(
            USER_ID,
            content,
            "twitter",
            asyncio.Semaphore(),
            crawled_urls=set(),
        )
        assert count == 2
        assert mock_crawl.await_count == 2
        assert len(mock_memory.retain.await_args.args[1]) == 2


class TestExtractProfilesLogging:
    """Exact log payloads for the parallel profile-extraction track."""

    @patch(_PATCH_LOG)
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_platform_failure_logs_exact_payload(
        self,
        mock_single: AsyncMock,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=UserDocument(name="Test"))
        mock_parallel.return_value = {"github": [{"id": "1"}]}
        mock_single.side_effect = RuntimeError("boom")

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {"profiles_stored": 0, "extracted_profiles": []}
        mock_log.error.assert_any_call(
            f"{LogTag.MEMORY} Platform extraction failed",
            platform="github",
            error_type="RuntimeError",
            error="boom",
            user_id=USER_ID,
        )

    @patch(_PATCH_LOG)
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_discovery_failure_logs_exact_payload(
        self,
        mock_single: AsyncMock,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
        mock_log: MagicMock,
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

        assert result["profiles_stored"] == 1
        mock_log.error.assert_any_call(
            f"{LogTag.MEMORY} Discovery task failed",
            error_type="RuntimeError",
            error="discovery crash",
            user_id=USER_ID,
        )

    @patch(_PATCH_LOG)
    @patch(_PATCH_USERS)
    async def test_outer_failure_logs_exact_payload(
        self, mock_users: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_users.get = AsyncMock(side_effect=RuntimeError("db down"))

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result == {"profiles_stored": 0, "extracted_profiles": []}
        mock_log.error.assert_called_once_with(
            f"{LogTag.MEMORY} Error in profile extraction from parallel searches",
            error_type="RuntimeError",
            error="db down",
            user_id=USER_ID,
        )

    @patch(_PATCH_LOG)
    @patch("app.agents.memory.email_processor.time")
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_completion_logs_carry_exact_timers_and_counts(
        self,
        mock_single: AsyncMock,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
        mock_time: MagicMock,
        mock_log: MagicMock,
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
                    "discovery_task": asyncio.create_task(_fake_discovery(2)),
                }
            return {
                "success": True,
                "platform": "twitter",
                "url": "https://x.com/b",
                "discovery_task": asyncio.create_task(_fake_discovery(3)),
            }

        mock_single.side_effect = fake_impl
        # The module's own `time` reference is replaced wholesale, so only
        # email_processor's calls hit these pins — the asyncio event loop
        # keeps real time. monotonic: t0 + duration x3 = 6 calls, each
        # elapsed 1.2345 so round(x, 1) != round(x, 2). time.time:
        # extraction_start + elapsed = 1.2345 (two decimals matter).
        mock_time.monotonic.side_effect = [
            100.0,
            101.2345,
            100.0,
            101.2345,
            100.0,
            101.2345,
        ]
        mock_time.time.side_effect = [100.0, 101.2345]

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        # 2 platforms + 2 + 3 discovered = 7; the += must accumulate, not assign.
        assert result["profiles_stored"] == 7
        assert result["extracted_profiles"] == [
            {"platform": "github", "url": "https://github.com/a"},
            {"platform": "twitter", "url": "https://x.com/b"},
        ]
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} _search_platform_emails_parallel finished",
            duration_s=1.2,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Platform tasks gather finished",
            duration_s=1.2,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Discovered profile tasks gather finished",
            duration_s=1.2,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Profile extraction completed",
            duration_s=1.23,
            profiles_stored=7,
            platform_count=2,
            discovered_count=5,
            user_id=USER_ID,
        )


class TestProcessSinglePlatformValidationSeam:
    """Username validation must receive the extracted username and platform."""

    @patch(_PATCH_STORE_PROFILE, new_callable=AsyncMock)
    @patch(_PATCH_CRAWL, new_callable=AsyncMock)
    @patch(_PATCH_BUILD_URL, return_value="https://github.com/testuser")
    @patch(_PATCH_VALIDATE)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="testuser")
    async def test_validation_receives_username_and_platform(
        self,
        mock_extract: AsyncMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_crawl: AsyncMock,
        mock_store: AsyncMock,
    ) -> None:
        """Validation must pass the real platform, not drop either argument."""
        mock_validate.side_effect = lambda username, platform: platform == "github"
        mock_crawl.return_value = {"content": "Profile content", "error": None}

        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore(), "Test User"
        )

        assert result["success"] is True
        assert result["url"] == "https://github.com/testuser"
        mock_validate.assert_called_once_with("testuser", "github")

        # Clean up the discovery task.
        if "discovery_task" in result:
            result["discovery_task"].cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await result["discovery_task"]

    @patch(_PATCH_LOG)
    @patch(_PATCH_VALIDATE, return_value=False)
    @patch(_PATCH_EXTRACT_USER, new_callable=AsyncMock, return_value="bad!")
    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"regex_pattern": r"^[a-zA-Z0-9]+$"}},
    )
    async def test_validation_failure_warning_logs_exact_payload(
        self, mock_extract: AsyncMock, mock_validate: MagicMock, mock_log: MagicMock
    ) -> None:
        result = await _process_single_platform(
            USER_ID, "github", [{"id": "1"}], asyncio.Semaphore()
        )
        assert result == {"error": "Invalid username 'bad!' for github"}
        mock_log.warning.assert_called_once_with(
            f"{LogTag.MEMORY} Username validation failed",
            platform="github",
            username="bad!",
            expected_pattern=r"^[a-zA-Z0-9]+$",
        )


# ---------------------------------------------------------------------------
# process_gmail_to_memory — exact log contracts & storage failure semantics
# ---------------------------------------------------------------------------


class TestProcessGmailToMemoryLogging:
    """Every log line in the orchestrator must carry its exact payload."""

    @patch(_PATCH_LOG)
    @patch("app.agents.memory.email_processor.time")
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_success_path_logs_exact_payloads(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
        mock_time: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user(name="Test User", email="test@test.com"))
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}, {"id": "2"}])
        mock_process.return_value = ([{"role": "user", "content": "email1"}], 0)
        mock_store.return_value = None
        mock_profiles.return_value = {"profiles_stored": 0}

        # monotonic: _StepTimer start, t0_fetch_phase, t0_search, fetch_elapsed,
        # t0_parse, parse_elapsed, fetch+parse total, t0_storage, storage_elapsed,
        # t0_profile, profile_elapsed, t0_mark, mark_elapsed, summary total.
        mock_time.monotonic.side_effect = [
            100.0,
            100.0,
            101.2345,
            100.0,
            101.2345,
            101.2345,
            100.0,
            101.2345,
            100.0,
            101.2345,
            100.0,
            101.2345,
            101.2345,
        ]
        # time.time: fetch_start_time + total_elapsed = 1.2345.
        mock_time.time.side_effect = [100.0, 101.2345]

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 2
        assert result["successful"] == 1
        mock_users.get.assert_awaited_once_with(USER_ID)
        mock_profiles.assert_awaited_once_with(USER_ID)
        mock_store.assert_awaited_once_with(
            USER_ID, [{"role": "user", "content": "email1"}], "Test User", "test@test.com"
        )
        # The scan timestamp must be written for this user as an aware UTC stamp.
        ts_call = mock_users.set_gmail_scan_timestamp.await_args
        assert ts_call.args[0] == USER_ID
        assert ts_call.args[1].tzinfo == UTC
        mock_log.error.assert_not_called()
        mock_log.warning.assert_not_called()
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Gmail fetch batch completed",
            batch=1,
            duration_s=1.2,
            fetched_so_far=2,
            user_id=USER_ID,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Email content parsing batch completed",
            batch=1,
            duration_s=1.234,
            parsed_count=1,
            failed_count=0,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Awaiting memory storage tasks",
            task_count=1,
            email_count=1,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Memory email storage tasks dispatched",
            duration_s=1.2,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Email storage complete",
            successful_batches=1,
            total_batches=1,
            failed_batches=0,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Profile extraction track finished",
            duration_s=1.2,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Processing complete",
            duration_s=1.23,
            parsed_count=1,
            profiles_stored=0,
            storage_errors=0,
            user_id=USER_ID,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} mark_email_processing_complete finished",
            duration_s=1.2,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Marked email processing as complete",
            user_id=USER_ID,
        )
        # The timing breakdown must carry every recorded step label with its
        # pinned elapsed value (mutants that swap labels or flip the timer
        # arithmetic change these lines).
        breakdown_call = next(
            call for call in mock_log.info.call_args_list if call.kwargs.get("summary") is not None
        )
        assert breakdown_call.args[0] == (
            f"{LogTag.MEMORY} Onboarding email pipeline timing breakdown"
        )
        breakdown = breakdown_call.kwargs["summary"]
        for label in [
            "Gmail API fetch — batch 1",
            "Email parse (HTML→text) — batch 1 (1 emails)",
            "Gmail fetch + parse phase (total)",
            "Memory email storage await (1 batches queued)",
            "Profile extraction track (wait for completion)",
            "DB mark-complete write",
        ]:
            # The label must start the line (mutants that mangle it break the
            # prefix) and the last token must be the pinned one-decimal
            # elapsed (mutants that flip the arithmetic change the value).
            line = next(line for line in breakdown.splitlines() if line.strip().startswith(label))
            assert line.split()[-1] == "1.2s", f"{label!r} line carried {line!r}"
        assert "TOTAL" in breakdown

    @patch(_PATCH_LOG)
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_storage_failures_log_exact_payloads(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_process.side_effect = [
            ([{"role": "user", "content": "email1"}], 1),
            ([{"role": "user", "content": "email2"}], 2),
        ]
        mock_store.side_effect = [RuntimeError("db down"), RuntimeError("db down2")]
        mock_profiles.return_value = {"profiles_stored": 0}

        # Two batches, both failing -> storage_errors and total_failed must
        # COUNT, not assign; the batch counter must keep incrementing.
        mock_search.side_effect = [
            _search_response([{"id": "1"}], next_token="tok1"),
            _search_response([{"id": "2"}]),
        ]

        result = await process_gmail_to_memory(USER_ID)

        assert result["successful"] == 2
        assert result["failed"] == 3
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Gmail fetch batch completed",
            batch=2,
            duration_s=0.0,
            fetched_so_far=2,
            user_id=USER_ID,
        )
        assert mock_log.warning.call_count == 2
        mock_log.warning.assert_any_call(
            f"{LogTag.MEMORY} Email storage task failed",
            task_index=1,
            error_type="RuntimeError",
            error="db down",
        )
        mock_log.warning.assert_any_call(
            f"{LogTag.MEMORY} Email storage task failed",
            task_index=2,
            error_type="RuntimeError",
            error="db down2",
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Email storage complete",
            successful_batches=0,
            total_batches=2,
            failed_batches=2,
        )
        mock_log.error.assert_not_called()

    @patch(_PATCH_LOG)
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_storage_warning_crash_falls_back_to_critical_error(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        """Any exception inside the storage wait falls back to the critical log."""
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "email1"}], 0)
        mock_store.side_effect = RuntimeError("db down")
        mock_profiles.return_value = {"profiles_stored": 0}
        mock_log.warning.side_effect = RuntimeError("log boom")

        result = await process_gmail_to_memory(USER_ID)

        assert result["processing_complete"] is True
        mock_log.error.assert_any_call(
            f"{LogTag.MEMORY} Critical error in email storage tasks",
            error_type="RuntimeError",
            error="log boom",
            user_id=USER_ID,
        )
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Processing complete",
            duration_s=0.0,
            parsed_count=1,
            profiles_stored=0,
            storage_errors=1,
            user_id=USER_ID,
        )

    @patch(_PATCH_LOG)
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock, side_effect=RuntimeError("gmail down"))
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_fetch_failure_logs_exact_payload(
        self,
        mock_profiles: AsyncMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()

        result = await process_gmail_to_memory(USER_ID)

        assert result["total"] == 0
        mock_log.error.assert_any_call(
            f"{LogTag.MEMORY} Error in email processing pipeline",
            error_type="RuntimeError",
            error="gmail down",
            user_id=USER_ID,
        )

    @patch(_PATCH_LOG)
    @patch(_PATCH_USERS)
    async def test_already_processed_logs_exact_payload(
        self, mock_users: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user(email_memory_processed=True))

        result = await process_gmail_to_memory(USER_ID)

        assert result["already_processed"] is True
        mock_log.info.assert_called_once_with(
            f"{LogTag.MEMORY} User emails already processed, skipping",
            user_id=USER_ID,
        )

    @patch(_PATCH_LOG)
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
    async def test_mark_failure_logs_exact_payload(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "email1"}], 0)
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["processing_complete"] is True
        mock_log.error.assert_any_call(
            f"{LogTag.MEMORY} Failed to mark email processing complete",
            error_type="RuntimeError",
            error="mark fail",
            user_id=USER_ID,
        )

    @patch(_PATCH_LOG)
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_scan_timestamp_failure_logs_exact_payload(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock(side_effect=RuntimeError("ts down"))
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "email1"}], 0)
        mock_profiles.return_value = {"profiles_stored": 0}

        result = await process_gmail_to_memory(USER_ID)

        assert result["processing_complete"] is True
        mock_log.error.assert_any_call(
            f"{LogTag.MEMORY} Failed to update Gmail scan timestamp",
            error_type="RuntimeError",
            error="ts down",
            user_id=USER_ID,
        )

    @patch(_PATCH_LOG)
    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_STORE_EMAILS, new_callable=AsyncMock)
    @patch(_PATCH_MARK_COMPLETE, new_callable=AsyncMock)
    @patch(_PATCH_EXTRACT_PROFILES, new_callable=AsyncMock)
    async def test_profile_task_failure_logs_exact_payload(
        self,
        mock_profiles: AsyncMock,
        mock_mark: AsyncMock,
        mock_store: AsyncMock,
        mock_process: MagicMock,
        mock_search: AsyncMock,
        mock_users: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(return_value=_make_user())
        mock_users.set_gmail_scan_timestamp = AsyncMock()
        mock_search.return_value = GmailMessagesResponse(messages=[{"id": "1"}])
        mock_process.return_value = ([{"role": "user", "content": "email1"}], 0)
        mock_profiles.side_effect = RuntimeError("profile crash")

        result = await process_gmail_to_memory(USER_ID)

        assert result["profiles_stored"] == 0
        mock_log.error.assert_any_call(
            f"{LogTag.MEMORY} Profile extraction task failed",
            error_type="RuntimeError",
            error="profile crash",
            user_id=USER_ID,
        )


class TestExtractProfilesArgumentSeams:
    """The extraction track must pass the user id through every seam."""

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_user_id_reaches_repository_and_search(
        self,
        mock_single: AsyncMock,
        mock_parallel: AsyncMock,
        mock_users: MagicMock,
    ) -> None:
        mock_users.get = AsyncMock(
            side_effect=lambda uid: UserDocument(name="Test") if uid == USER_ID else None
        )
        mock_parallel.return_value = {"github": [{"id": "1"}]}
        mock_single.return_value = {
            "success": True,
            "platform": "github",
            "url": "https://github.com/a",
        }

        result = await _extract_profiles_from_parallel_searches(USER_ID)

        assert result["profiles_stored"] == 1
        mock_users.get.assert_awaited_once_with(USER_ID)
        mock_parallel.assert_awaited_once_with(USER_ID)
        assert mock_single.await_args.args[0] == USER_ID

    @patch(_PATCH_USERS)
    @patch(_PATCH_SEARCH_PARALLEL, new_callable=AsyncMock)
    @patch(_PATCH_SINGLE_PLATFORM, new_callable=AsyncMock)
    async def test_crawl_semaphore_is_20_wide(
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
        }

        await _extract_profiles_from_parallel_searches(USER_ID)

        semaphore = mock_single.await_args.args[3]
        assert isinstance(semaphore, asyncio.Semaphore)
        assert semaphore._value == 20


class TestSearchPlatformEmailsParallelLogging:
    """Exact log payloads for the parallel-search track."""

    @patch(_PATCH_LOG)
    @patch(
        _PATCH_PLATFORM_CONFIG,
        {
            "github": {"sender_domains": ["github.com"]},
            "twitter": {"sender_domains": ["twitter.com"]},
        },
    )
    @patch(
        "app.agents.memory.email_processor._search_platform_emails",
        new_callable=AsyncMock,
    )
    async def test_failure_and_completion_logs_exact_payloads(
        self, mock_single_search: AsyncMock, mock_log: MagicMock
    ) -> None:
        mock_single_search.side_effect = [
            RuntimeError("boom"),
            [{"id": "t1"}],
        ]

        with patch("app.agents.memory.email_processor.time.time") as mock_time:
            mock_time.side_effect = [100.0, 101.2345]
            result = await _search_platform_emails_parallel(USER_ID)

        assert result == {"github": [], "twitter": [{"id": "t1"}]}
        mock_log.error.assert_called_once_with(
            f"{LogTag.MEMORY} Platform email search failed",
            platform="github",
            error_type="RuntimeError",
            error="boom",
            user_id=USER_ID,
        )
        mock_log.info.assert_called_once_with(
            f"{LogTag.MEMORY} Parallel Gmail searches completed",
            duration_s=1.23,
            email_count=1,
            platform_count=2,
            user_id=USER_ID,
        )

    @patch(_PATCH_LOG)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock, side_effect=RuntimeError("gmail down"))
    async def test_search_platform_emails_error_logs_exact_payload(
        self, mock_search: AsyncMock, mock_log: MagicMock
    ) -> None:
        result = await _search_platform_emails(USER_ID, "github", "from:github.com")
        assert result == []
        mock_log.error.assert_called_once_with(
            f"{LogTag.MEMORY} Error searching platform emails",
            platform="github",
            error_type="RuntimeError",
            error="gmail down",
            user_id=USER_ID,
        )


class TestFetchEmailsForOnboardingLogging:
    """Exact log payloads for the onboarding fetch helper."""

    @patch(_PATCH_LOG)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_finished_logs_exact_payload(
        self, mock_search: AsyncMock, mock_log: MagicMock
    ) -> None:
        mock_search.return_value = _search_response([])
        result = await fetch_emails_for_onboarding(USER_ID, fmt="metadata")
        assert result == []
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} fetch_emails_for_onboarding finished",
            email_count=0,
            user_id=USER_ID,
            fmt="metadata",
        )

    @patch(_PATCH_LOG)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock, side_effect=RuntimeError("gmail down"))
    async def test_failure_logs_exact_payload(
        self, mock_search: AsyncMock, mock_log: MagicMock
    ) -> None:
        result = await fetch_emails_for_onboarding(USER_ID)
        assert result == []
        mock_log.error.assert_any_call(
            f"{LogTag.MEMORY} fetch_emails_for_onboarding failed",
            user_id=USER_ID,
            fetched_count=0,
            error_type="RuntimeError",
            error="gmail down",
            exc_info=True,
        )


class TestExtractDisplayNameEdgeCases:
    """Multi-delimiter and charset edge cases for the display-name helper."""

    def test_two_angle_brackets_uses_first_split(self) -> None:
        """rsplit would take the LAST '<' — the FIRST must win."""
        assert _extract_display_name("A <B <c@x.com>") == "A"

    def test_two_at_signs_fallback_uses_first_split(self) -> None:
        """rsplit would take the LAST '@' — the FIRST must win."""
        assert _extract_display_name("<a@b@c.com>") == "a"

    def test_name_with_x_chars_strips_only_angle_brackets(self) -> None:
        """The strip charset is exactly '<' and '>' — not letters."""
        assert _extract_display_name("<Xavier@x.com>") == "Xavier"


class TestFetchEmailsForOnboardingDefaults:
    """The default argument values must stay exactly as documented."""

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_default_batch_size_is_100(self, mock_search: AsyncMock) -> None:
        mock_search.return_value = _search_response([])
        await fetch_emails_for_onboarding(USER_ID)
        assert mock_search.await_args.kwargs["max_results"] == 100

    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_default_max_total_caps_at_200(self, mock_search: AsyncMock) -> None:
        mock_search.side_effect = [
            _search_response([{"id": f"a{i}"} for i in range(100)], next_token="tok1"),
            _search_response([{"id": f"b{i}"} for i in range(100)], next_token="tok2"),
            _search_response([{"id": f"c{i}"} for i in range(100)], next_token="tok3"),
        ]
        result = await fetch_emails_for_onboarding(USER_ID)
        assert len(result) == 200
        assert mock_search.await_count == 2

    @patch(_PATCH_LOG)
    @patch(_PATCH_SEARCH, new_callable=AsyncMock)
    async def test_default_fmt_is_metadata(
        self, mock_search: AsyncMock, mock_log: MagicMock
    ) -> None:
        mock_search.return_value = _search_response([])
        await fetch_emails_for_onboarding(USER_ID)
        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} fetch_emails_for_onboarding finished",
            email_count=0,
            user_id=USER_ID,
            fmt="metadata",
        )


class TestSearchPlatformEmailsParallelSeams:
    """The platform search task must receive the platform and query."""

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"sender_domains": ["github.com"]}},
    )
    @patch(
        "app.agents.memory.email_processor._search_platform_emails",
        new_callable=AsyncMock,
    )
    async def test_platform_search_receives_platform_and_query(
        self, mock_single: AsyncMock
    ) -> None:
        mock_single.return_value = [{"id": "g1"}]
        result = await _search_platform_emails_parallel(USER_ID)
        assert result == {"github": [{"id": "g1"}]}
        mock_single.assert_awaited_once_with(USER_ID, "github", "from:github.com")


class TestSearchPlatformEmailsParallelDefensiveBranches:
    """The defensive fallbacks fire when the per-platform search misbehaves."""

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"sender_domains": ["github.com"]}},
    )
    @patch(
        "app.agents.memory.email_processor._search_platform_emails",
        new_callable=AsyncMock,
        side_effect=RuntimeError("search crash"),
    )
    async def test_raising_search_yields_empty_list(self, mock_single_search: AsyncMock) -> None:
        result = await _search_platform_emails_parallel(USER_ID)
        assert result == {"github": []}
        assert isinstance(result["github"], list)

    @patch(
        _PATCH_PLATFORM_CONFIG,
        {"github": {"sender_domains": ["github.com"]}},
    )
    @patch(
        "app.agents.memory.email_processor._search_platform_emails",
        new_callable=AsyncMock,
        return_value="not a list",
    )
    async def test_non_list_search_yields_empty_list(self, mock_single_search: AsyncMock) -> None:
        result = await _search_platform_emails_parallel(USER_ID)
        assert result == {"github": []}
        assert isinstance(result["github"], list)
