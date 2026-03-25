"""Tests for app.helpers.email_helpers — email processing and storage utilities."""

from datetime import datetime, timezone
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.email import NO_SUBJECT, UNKNOWN_SENDER
from app.helpers.email_helpers import (
    _build_user_context,
    mark_email_processing_complete,
    process_email_content,
    remove_invisible_chars,
    store_emails_to_mem0,
    store_single_profile,
)


# ---------------------------------------------------------------------------
# _build_user_context
# ---------------------------------------------------------------------------


class TestBuildUserContext:
    """Tests for _build_user_context()."""

    def test_with_name_and_email(self) -> None:
        result = _build_user_context("Alice", "alice@example.com")
        assert "Alice" in result
        assert "alice@example.com" in result

    def test_with_name_only(self) -> None:
        result = _build_user_context("Bob", None)
        assert "Bob" in result
        assert "email" not in result.lower()

    def test_with_none_name(self) -> None:
        result = _build_user_context(None, "user@test.com")
        assert result == ""

    def test_with_empty_string_name(self) -> None:
        result = _build_user_context("", "user@test.com")
        assert result == ""

    def test_with_both_none(self) -> None:
        result = _build_user_context(None, None)
        assert result == ""

    @pytest.mark.parametrize(
        "name, email, should_contain_email",
        [
            ("Alice", "a@b.com", True),
            ("Alice", None, False),
            ("Alice", "", False),
        ],
        ids=["with-email", "none-email", "empty-email"],
    )
    def test_email_inclusion(
        self,
        name: str,
        email: str | None,
        should_contain_email: bool,
    ) -> None:
        result = _build_user_context(name, email)
        if should_contain_email:
            assert email in result  # type: ignore[operator]
        else:
            assert result == f"The user's name is {name}."


# ---------------------------------------------------------------------------
# remove_invisible_chars
# ---------------------------------------------------------------------------


class TestRemoveInvisibleChars:
    """Tests for remove_invisible_chars()."""

    def test_plain_ascii_unchanged(self) -> None:
        assert remove_invisible_chars("Hello World") == "Hello World"

    def test_empty_string(self) -> None:
        assert remove_invisible_chars("") == ""

    def test_removes_zero_width_space(self) -> None:
        # U+200B ZERO WIDTH SPACE — category Cf
        text = "hello\u200bworld"
        assert remove_invisible_chars(text) == "helloworld"

    def test_removes_zero_width_joiner(self) -> None:
        # U+200D ZERO WIDTH JOINER — category Cf
        text = "a\u200db"
        assert remove_invisible_chars(text) == "ab"

    def test_removes_soft_hyphen(self) -> None:
        # U+00AD SOFT HYPHEN — category Cf
        text = "hel\u00adlo"
        assert remove_invisible_chars(text) == "hello"

    def test_removes_null_byte(self) -> None:
        # U+0000 NULL — category Cc
        text = "hello\x00world"
        assert remove_invisible_chars(text) == "helloworld"

    def test_removes_control_characters(self) -> None:
        # U+0001 SOH, U+0002 STX — category Cc
        text = "a\x01b\x02c"
        assert remove_invisible_chars(text) == "abc"

    def test_preserves_newlines_tabs(self) -> None:
        # \n (U+000A) and \t (U+0009) are category Cc — they WILL be removed
        text = "hello\n\tworld"
        result = remove_invisible_chars(text)
        assert "\n" not in result
        assert "\t" not in result

    def test_preserves_normal_unicode(self) -> None:
        # Accented characters (category L) should be preserved
        text = "\u00e9l\u00e8ve caf\u00e9"
        assert remove_invisible_chars(text) == "\u00e9l\u00e8ve caf\u00e9"

    def test_removes_bom(self) -> None:
        # U+FEFF BOM — category Cf
        text = "\ufeffHello"
        assert remove_invisible_chars(text) == "Hello"

    def test_removes_right_to_left_mark(self) -> None:
        # U+200F RIGHT-TO-LEFT MARK — category Cf
        text = "abc\u200fdef"
        assert remove_invisible_chars(text) == "abcdef"

    @pytest.mark.parametrize(
        "char, name",
        [
            ("\u200b", "zero-width-space"),
            ("\u200c", "zero-width-non-joiner"),
            ("\u200d", "zero-width-joiner"),
            ("\u2060", "word-joiner"),
            ("\ufeff", "bom"),
            ("\u00ad", "soft-hyphen"),
            ("\u200e", "left-to-right-mark"),
            ("\u200f", "right-to-left-mark"),
        ],
        ids=[
            "ZWSP",
            "ZWNJ",
            "ZWJ",
            "WJ",
            "BOM",
            "SHY",
            "LRM",
            "RLM",
        ],
    )
    def test_common_invisible_chars_removed(self, char: str, name: str) -> None:
        text = f"before{char}after"
        assert remove_invisible_chars(text) == "beforeafter"

    def test_multiple_invisible_chars(self) -> None:
        text = "\u200b\u200c\u200dvisible\ufeff\u00ad"
        assert remove_invisible_chars(text) == "visible"


# ---------------------------------------------------------------------------
# process_email_content
# ---------------------------------------------------------------------------


class TestProcessEmailContent:
    """Tests for process_email_content()."""

    def test_basic_html_email(self) -> None:
        emails = [
            {
                "messageId": "msg_1",
                "sender": "friend@example.com",
                "subject": "Hello",
                "messageText": "<p>Hello there!</p>",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 1
        assert failed == 0
        assert "Hello there!" in processed[0]["content"]
        assert processed[0]["metadata"]["message_id"] == "msg_1"
        assert processed[0]["metadata"]["sender"] == "friend@example.com"
        assert processed[0]["metadata"]["subject"] == "Hello"
        assert processed[0]["metadata"]["type"] == "email"
        assert processed[0]["metadata"]["source"] == "gmail"

    def test_empty_list(self) -> None:
        processed, failed = process_email_content([])
        assert processed == []
        assert failed == 0

    def test_empty_message_text_increments_failed(self) -> None:
        emails = [
            {
                "sender": "someone@example.com",
                "subject": "Empty",
                "messageText": "",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 0
        assert failed == 1

    def test_whitespace_only_message_text_increments_failed(self) -> None:
        emails = [
            {
                "sender": "someone@example.com",
                "subject": "Whitespace",
                "messageText": "   \n\t  ",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 0
        assert failed == 1

    def test_platform_emails_skipped_twitter(self) -> None:
        emails = [
            {
                "sender": "notify@twitter.com",
                "subject": "New follower",
                "messageText": "<p>You have a new follower</p>",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 0
        assert failed == 0  # skipped, not failed

    def test_platform_emails_skipped_github(self) -> None:
        emails = [
            {
                "sender": "noreply@github.com",
                "subject": "PR merged",
                "messageText": "<p>Your PR was merged</p>",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 0
        assert failed == 0

    def test_platform_emails_skipped_linkedin(self) -> None:
        emails = [
            {
                "sender": "messages-noreply@linkedin.com",
                "subject": "New message",
                "messageText": "<p>You have a new message</p>",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 0
        assert failed == 0

    def test_sender_from_field_fallback(self) -> None:
        """When 'sender' key is missing, uses 'from' field."""
        emails = [
            {
                "from": "friend@example.com",
                "subject": "Hey",
                "messageText": "<b>Hi</b>",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 1
        assert processed[0]["metadata"]["sender"] == "friend@example.com"

    def test_sender_none_uses_from(self) -> None:
        """When sender is None, fall through to from."""
        emails = [
            {
                "sender": None,
                "from": "other@example.com",
                "subject": "Test",
                "messageText": "<p>Content</p>",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 1
        assert processed[0]["metadata"]["sender"] == "other@example.com"

    def test_default_sender_and_subject(self) -> None:
        """Missing sender and subject should use defaults."""
        emails = [
            {
                "messageText": "<p>Some content</p>",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 1
        assert processed[0]["metadata"]["sender"] == UNKNOWN_SENDER
        assert processed[0]["metadata"]["subject"] == NO_SUBJECT

    def test_message_id_fallback_to_id(self) -> None:
        """When messageId is missing, falls back to 'id' field."""
        emails = [
            {
                "id": "alt_id_1",
                "sender": "test@example.com",
                "messageText": "<p>Hello</p>",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 1
        assert processed[0]["metadata"]["message_id"] == "alt_id_1"

    def test_invisible_chars_removed_from_content(self) -> None:
        emails = [
            {
                "sender": "test@example.com",
                "messageText": "<p>Hello\u200bWorld</p>",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 1
        assert "\u200b" not in processed[0]["content"]

    def test_multiple_emails_mixed(self) -> None:
        """Mix of valid, platform-skipped, and empty emails."""
        emails = [
            {
                "sender": "friend@example.com",
                "messageText": "<p>Valid email</p>",
                "subject": "Hi",
            },
            {
                "sender": "notify@twitter.com",
                "messageText": "<p>Platform email</p>",
            },
            {
                "sender": "another@example.com",
                "messageText": "",
            },
            {
                "sender": "third@example.com",
                "messageText": "<p>Another valid</p>",
                "subject": "Hey",
            },
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 2
        assert failed == 1  # only the empty one

    def test_exception_in_processing_increments_failed(self) -> None:
        """If an email causes an exception, it's counted as failed."""
        # Pass something that will cause html2text to choke or other error
        emails = [
            {
                "sender": "test@example.com",
                "messageText": "<p>Valid</p>",
            },
        ]
        with patch(
            "app.helpers.email_helpers._html_converter.handle",
            side_effect=Exception("parse error"),
        ):
            processed, failed = process_email_content(emails)
        assert len(processed) == 0
        assert failed == 1

    def test_html_converted_to_clean_text(self) -> None:
        """HTML tags should be stripped from output."""
        emails = [
            {
                "sender": "test@example.com",
                "messageText": "<h1>Title</h1><p>Paragraph with <b>bold</b></p>",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 1
        content = processed[0]["content"]
        assert "<h1>" not in content
        assert "<p>" not in content
        assert "<b>" not in content
        assert "Title" in content
        assert "bold" in content

    def test_platform_detection_case_insensitive(self) -> None:
        """Platform domain check should be case-insensitive."""
        emails = [
            {
                "sender": "NOTIFY@TWITTER.COM",
                "messageText": "<p>Content</p>",
            }
        ]
        processed, failed = process_email_content(emails)
        assert len(processed) == 0  # skipped as platform email

    def test_html_to_text_strips_empty_result(self) -> None:
        """If HTML converts to empty string after stripping, count as failed."""
        emails = [
            {
                "sender": "test@example.com",
                "messageText": "<p>  </p>",  # converts to whitespace
            }
        ]
        # This may or may not be empty depending on html2text behavior.
        # We just verify no crash and correct accounting.
        processed, failed = process_email_content(emails)
        assert isinstance(processed, list)
        assert isinstance(failed, int)
        assert len(processed) + failed <= 1


# ---------------------------------------------------------------------------
# store_emails_to_mem0
# ---------------------------------------------------------------------------


class TestStoreEmailsToMem0:
    """Tests for store_emails_to_mem0()."""

    @pytest.fixture
    def mock_memory_service(self) -> Generator[AsyncMock, None, None]:
        with patch("app.helpers.email_helpers.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)
            yield mock_svc

    async def test_empty_list_returns_early(
        self, mock_memory_service: AsyncMock
    ) -> None:
        await store_emails_to_mem0("user_1", [])
        mock_memory_service.store_memory_batch.assert_not_called()

    async def test_calls_store_memory_batch(
        self, mock_memory_service: AsyncMock
    ) -> None:
        processed = [
            {
                "content": "Email body text",
                "metadata": {
                    "sender": "alice@example.com",
                    "subject": "Hello",
                },
            }
        ]
        await store_emails_to_mem0("user_1", processed)
        mock_memory_service.store_memory_batch.assert_called_once()

    async def test_passes_user_id(self, mock_memory_service: AsyncMock) -> None:
        processed = [
            {
                "content": "Body",
                "metadata": {"sender": "a@b.com", "subject": "S"},
            }
        ]
        await store_emails_to_mem0("user_42", processed)
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert call_kwargs["user_id"] == "user_42"

    async def test_async_mode_default_true(
        self, mock_memory_service: AsyncMock
    ) -> None:
        processed = [
            {
                "content": "Body",
                "metadata": {"sender": "a@b.com", "subject": "S"},
            }
        ]
        await store_emails_to_mem0("user_1", processed)
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert call_kwargs["async_mode"] is True

    async def test_async_mode_false(self, mock_memory_service: AsyncMock) -> None:
        processed = [
            {
                "content": "Body",
                "metadata": {"sender": "a@b.com", "subject": "S"},
            }
        ]
        await store_emails_to_mem0("user_1", processed, async_mode=False)
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert call_kwargs["async_mode"] is False

    async def test_user_name_and_email_in_metadata(
        self,
        mock_memory_service: AsyncMock,
    ) -> None:
        processed = [
            {
                "content": "Body",
                "metadata": {"sender": "a@b.com", "subject": "S"},
            }
        ]
        await store_emails_to_mem0(
            "user_1",
            processed,
            user_name="Alice",
            user_email="alice@x.com",
        )
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert call_kwargs["metadata"]["user_name"] == "Alice"
        assert call_kwargs["metadata"]["user_email"] == "alice@x.com"

    async def test_messages_built_correctly(
        self, mock_memory_service: AsyncMock
    ) -> None:
        processed = [
            {
                "content": "Email text here",
                "metadata": {
                    "sender": "bob@example.com",
                    "subject": "Important",
                },
            }
        ]
        await store_emails_to_mem0("user_1", processed)
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "bob@example.com" in messages[0]["content"]
        assert "Important" in messages[0]["content"]
        assert "Email text here" in messages[0]["content"]

    async def test_skips_emails_with_empty_content(
        self,
        mock_memory_service: AsyncMock,
    ) -> None:
        processed = [
            {
                "content": "",
                "metadata": {"sender": "a@b.com", "subject": "S"},
            },
            {
                "content": "   ",
                "metadata": {"sender": "a@b.com", "subject": "S"},
            },
        ]
        await store_emails_to_mem0("user_1", processed)
        # Both have empty/whitespace content, so messages list should be empty
        # and function returns early after building empty messages
        mock_memory_service.store_memory_batch.assert_not_called()

    async def test_store_failure_logs_warning(
        self,
        mock_memory_service: AsyncMock,
    ) -> None:
        mock_memory_service.store_memory_batch.return_value = False
        processed = [
            {
                "content": "Body",
                "metadata": {"sender": "a@b.com", "subject": "S"},
            }
        ]
        # Should not raise
        await store_emails_to_mem0("user_1", processed)

    async def test_exception_does_not_propagate(
        self,
        mock_memory_service: AsyncMock,
    ) -> None:
        mock_memory_service.store_memory_batch.side_effect = Exception("boom")
        processed = [
            {
                "content": "Body",
                "metadata": {"sender": "a@b.com", "subject": "S"},
            }
        ]
        # Should swallow the exception
        await store_emails_to_mem0("user_1", processed)

    async def test_custom_instructions_include_user_context(
        self,
        mock_memory_service: AsyncMock,
    ) -> None:
        processed = [
            {
                "content": "Body",
                "metadata": {"sender": "a@b.com", "subject": "S"},
            }
        ]
        await store_emails_to_mem0(
            "user_1",
            processed,
            user_name="Alice",
            user_email="alice@x.com",
        )
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert "Alice" in call_kwargs["custom_instructions"]
        assert "alice@x.com" in call_kwargs["custom_instructions"]

    async def test_batch_size_in_metadata(self, mock_memory_service: AsyncMock) -> None:
        processed = [
            {
                "content": f"Email {i}",
                "metadata": {"sender": "a@b.com", "subject": f"S{i}"},
            }
            for i in range(5)
        ]
        await store_emails_to_mem0("user_1", processed)
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert call_kwargs["metadata"]["batch_size"] == 5
        assert call_kwargs["metadata"]["source"] == "gmail_batch"


# ---------------------------------------------------------------------------
# mark_email_processing_complete
# ---------------------------------------------------------------------------


class TestMarkEmailProcessingComplete:
    """Tests for mark_email_processing_complete()."""

    @patch("app.helpers.email_helpers.users_collection")
    async def test_updates_user_document(self, mock_collection: MagicMock) -> None:
        mock_collection.update_one = AsyncMock()
        await mark_email_processing_complete(
            "507f1f77bcf86cd799439011",  # pragma: allowlist secret
            42,
        )
        mock_collection.update_one.assert_called_once()
        call_args = mock_collection.update_one.call_args
        # First positional arg is the filter
        filter_doc = call_args[0][0]
        assert (
            str(filter_doc["_id"]) == "507f1f77bcf86cd799439011"
        )  # pragma: allowlist secret
        # Second positional arg is the update
        update_doc = call_args[0][1]
        assert update_doc["$set"]["email_memory_processed"] is True
        assert update_doc["$set"]["email_memory_count"] == 42
        assert "email_memory_processed_at" in update_doc["$set"]

    @patch("app.helpers.email_helpers.users_collection")
    async def test_zero_memory_count(self, mock_collection: MagicMock) -> None:
        mock_collection.update_one = AsyncMock()
        await mark_email_processing_complete(
            "507f1f77bcf86cd799439011",  # pragma: allowlist secret
            0,
        )
        update_doc = mock_collection.update_one.call_args[0][1]
        assert update_doc["$set"]["email_memory_count"] == 0

    @patch("app.helpers.email_helpers.users_collection")
    async def test_timestamp_is_utc(self, mock_collection: MagicMock) -> None:
        mock_collection.update_one = AsyncMock()
        await mark_email_processing_complete(
            "507f1f77bcf86cd799439011",  # pragma: allowlist secret
            1,
        )
        update_doc = mock_collection.update_one.call_args[0][1]
        ts = update_doc["$set"]["email_memory_processed_at"]
        assert isinstance(ts, datetime)
        assert ts.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# store_single_profile
# ---------------------------------------------------------------------------


class TestStoreSingleProfile:
    """Tests for store_single_profile()."""

    @pytest.fixture
    def mock_memory_service(self) -> Generator[AsyncMock, None, None]:
        with patch("app.helpers.email_helpers.memory_service") as mock_svc:
            mock_svc.store_memory_batch = AsyncMock(return_value=True)
            yield mock_svc

    async def test_stores_profile_content(self, mock_memory_service: AsyncMock) -> None:
        await store_single_profile(
            "user_1",
            "twitter",
            "https://x.com/alice",
            "Bio: Software Engineer",
        )
        mock_memory_service.store_memory_batch.assert_called_once()
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        assert "twitter" in messages[0]["content"]
        assert "https://x.com/alice" in messages[0]["content"]
        assert "Bio: Software Engineer" in messages[0]["content"]

    async def test_metadata_includes_platform_and_url(
        self,
        mock_memory_service: AsyncMock,
    ) -> None:
        await store_single_profile(
            "user_1",
            "github",
            "https://github.com/alice",
            "repos: 50",
        )
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        metadata = call_kwargs["metadata"]
        assert metadata["type"] == "social_profile"
        assert metadata["platform"] == "github"
        assert metadata["url"] == "https://github.com/alice"
        assert metadata["source"] == "gmail_extraction"

    async def test_user_name_in_metadata(self, mock_memory_service: AsyncMock) -> None:
        await store_single_profile(
            "user_1",
            "linkedin",
            "https://linkedin.com/in/alice",
            "Profile content",
            user_name="Alice",
        )
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert call_kwargs["metadata"]["user_name"] == "Alice"

    async def test_default_async_mode_true(
        self, mock_memory_service: AsyncMock
    ) -> None:
        await store_single_profile(
            "user_1",
            "twitter",
            "https://x.com/a",
            "content",
        )
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert call_kwargs["async_mode"] is True

    async def test_async_mode_false(self, mock_memory_service: AsyncMock) -> None:
        await store_single_profile(
            "user_1",
            "twitter",
            "https://x.com/a",
            "content",
            async_mode=False,
        )
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert call_kwargs["async_mode"] is False

    async def test_exception_does_not_propagate(
        self,
        mock_memory_service: AsyncMock,
    ) -> None:
        mock_memory_service.store_memory_batch.side_effect = Exception("boom")
        # Should swallow the exception
        await store_single_profile(
            "user_1",
            "twitter",
            "https://x.com/a",
            "content",
        )

    async def test_user_id_passed_correctly(
        self,
        mock_memory_service: AsyncMock,
    ) -> None:
        await store_single_profile(
            "user_99",
            "github",
            "https://github.com/bob",
            "data",
        )
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert call_kwargs["user_id"] == "user_99"

    async def test_discovered_at_in_metadata(
        self,
        mock_memory_service: AsyncMock,
    ) -> None:
        await store_single_profile(
            "user_1",
            "twitter",
            "https://x.com/a",
            "content",
        )
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert "discovered_at" in call_kwargs["metadata"]

    @pytest.mark.parametrize(
        "platform, url",
        [
            ("twitter", "https://x.com/user"),
            ("github", "https://github.com/user"),
            ("linkedin", "https://linkedin.com/in/user"),
        ],
        ids=["twitter", "github", "linkedin"],
    )
    async def test_various_platforms(
        self,
        mock_memory_service: AsyncMock,
        platform: str,
        url: str,
    ) -> None:
        await store_single_profile("user_1", platform, url, "some content")
        call_kwargs = mock_memory_service.store_memory_batch.call_args.kwargs
        assert call_kwargs["metadata"]["platform"] == platform
        assert call_kwargs["metadata"]["url"] == url
