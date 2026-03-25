"""Tests for profile extractor (LLM-based username extraction from emails)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.memory.profile_extractor import (
    PLATFORM_CONFIG,
    UsernameExtraction,
    _deduplicate_emails,
    _filter_garbage_content,
    build_profile_url,
    extract_username_with_llm,
    filter_emails_by_platform,
    validate_username,
)


# ---------------------------------------------------------------------------
# filter_emails_by_platform
# ---------------------------------------------------------------------------


class TestFilterEmailsByPlatform:
    def test_filters_github_emails(self) -> None:
        emails = [
            {"sender": "noreply@github.com", "subject": "PR merged"},
            {"sender": "noreply@notifications.github.com", "subject": "New issue"},
            {"sender": "noreply@twitter.com", "subject": "New follower"},
        ]
        result = filter_emails_by_platform(emails, "github")
        assert len(result) == 2

    def test_filters_twitter_emails(self) -> None:
        emails = [
            {"sender": "notify@twitter.com", "subject": "New DM"},
            {"sender": "info@x.com", "subject": "Trending"},
        ]
        result = filter_emails_by_platform(emails, "twitter")
        assert len(result) == 2

    def test_unknown_platform_returns_empty(self) -> None:
        emails = [{"sender": "test@example.com"}]
        assert filter_emails_by_platform(emails, "unknown_platform") == []

    def test_no_matching_emails(self) -> None:
        emails = [{"sender": "noreply@example.com"}]
        assert filter_emails_by_platform(emails, "github") == []

    def test_uses_from_field_as_fallback(self) -> None:
        emails = [{"from": "noreply@github.com", "subject": "Test"}]
        result = filter_emails_by_platform(emails, "github")
        assert len(result) == 1

    def test_handles_missing_sender(self) -> None:
        emails = [{"subject": "No sender"}]
        result = filter_emails_by_platform(emails, "github")
        assert result == []

    def test_respects_max_limit(self) -> None:
        emails = [
            {"sender": "noreply@github.com", "subject": f"Email {i}"} for i in range(30)
        ]
        result = filter_emails_by_platform(emails, "github")
        assert len(result) == 20  # MAX_EMAILS_PER_PLATFORM

    def test_handles_angle_bracket_sender(self) -> None:
        emails = [{"sender": "GitHub <noreply@github.com>"}]
        result = filter_emails_by_platform(emails, "github")
        assert len(result) == 1

    def test_case_insensitive_matching(self) -> None:
        emails = [{"sender": "NoReply@GitHub.com"}]
        result = filter_emails_by_platform(emails, "github")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# validate_username
# ---------------------------------------------------------------------------


class TestValidateUsername:
    def test_valid_github_username(self) -> None:
        assert validate_username("octocat", "github") is True

    def test_valid_twitter_username(self) -> None:
        assert validate_username("jack", "twitter") is True

    def test_invalid_twitter_username_too_long(self) -> None:
        assert validate_username("a" * 20, "twitter") is False

    def test_empty_username(self) -> None:
        assert validate_username("", "github") is False

    def test_not_found_username(self) -> None:
        assert validate_username("NOT_FOUND", "github") is False

    def test_unknown_platform(self) -> None:
        assert validate_username("user", "unknown_platform") is False

    def test_valid_linkedin_username(self) -> None:
        assert validate_username("john-doe", "linkedin") is True

    def test_valid_instagram_username(self) -> None:
        assert validate_username("john.doe", "instagram") is True

    def test_invalid_github_start_with_hyphen(self) -> None:
        assert validate_username("-invalid", "github") is False

    def test_valid_reddit_username(self) -> None:
        assert validate_username("cool_user", "reddit") is True

    def test_valid_medium_username(self) -> None:
        assert validate_username("my-blog", "medium") is True

    def test_strips_whitespace(self) -> None:
        assert validate_username(" jack ", "twitter") is True

    @pytest.mark.parametrize(
        "platform",
        list(PLATFORM_CONFIG.keys()),
    )
    def test_all_platforms_have_regex(self, platform: str) -> None:
        # Ensures every platform config has a working regex
        assert "regex_pattern" in PLATFORM_CONFIG[platform]


# ---------------------------------------------------------------------------
# build_profile_url
# ---------------------------------------------------------------------------


class TestBuildProfileUrl:
    def test_github_url(self) -> None:
        assert build_profile_url("octocat", "github") == "https://github.com/octocat"

    def test_twitter_url(self) -> None:
        assert build_profile_url("jack", "twitter") == "https://x.com/jack"

    def test_substack_url(self) -> None:
        assert build_profile_url("myblog", "substack") == "https://myblog.substack.com"

    def test_unknown_platform_returns_empty(self) -> None:
        assert build_profile_url("user", "unknown_platform") == ""

    def test_medium_url_with_at(self) -> None:
        assert build_profile_url("user123", "medium") == "https://medium.com/@user123"

    @pytest.mark.parametrize("platform", list(PLATFORM_CONFIG.keys()))
    def test_all_platforms_build_url(self, platform: str) -> None:
        url = build_profile_url("testuser", platform)
        assert url != ""
        assert "testuser" in url


# ---------------------------------------------------------------------------
# _filter_garbage_content
# ---------------------------------------------------------------------------


class TestFilterGarbageContent:
    def test_removes_html_tags(self) -> None:
        result = _filter_garbage_content("<p>Hello <b>World</b></p>")
        assert "<p>" not in result
        assert "Hello" in result
        assert "World" in result

    def test_removes_repetitive_chars(self) -> None:
        result = _filter_garbage_content("text ========== more text")
        assert "==========" not in result

    def test_removes_code_block_markers(self) -> None:
        result = _filter_garbage_content("```python\ncode\n```")
        assert "```" not in result

    def test_removes_long_urls(self) -> None:
        long_url = "https://example.com/" + "a" * 60
        result = _filter_garbage_content(f"Check {long_url} out")
        assert long_url not in result

    def test_preserves_short_text(self) -> None:
        text = "Hello, @username! Welcome back."
        result = _filter_garbage_content(text)
        assert "@username" in result

    def test_removes_dashes(self) -> None:
        result = _filter_garbage_content("text ------- more text")
        assert "-------" not in result


# ---------------------------------------------------------------------------
# _deduplicate_emails
# ---------------------------------------------------------------------------


class TestDeduplicateEmails:
    def test_empty_list(self) -> None:
        assert _deduplicate_emails([]) == []

    def test_no_duplicates(self) -> None:
        emails = [
            {"messageText": "Hello from GitHub about your PR"},
            {"messageText": "LinkedIn notification about a new connection"},
        ]
        result = _deduplicate_emails(emails)
        assert len(result) == 2

    def test_removes_exact_duplicates(self) -> None:
        emails = [
            {"messageText": "Hello from GitHub about your PR merge"},
            {"messageText": "Hello from GitHub about your PR merge"},
        ]
        result = _deduplicate_emails(emails)
        assert len(result) == 1

    def test_removes_near_duplicates(self) -> None:
        # Very similar content (same template, different IDs)
        emails = [
            {"messageText": "Your pull request was merged by user in repo"},
            {"messageText": "Your pull request was merged by user in repo"},
        ]
        result = _deduplicate_emails(emails)
        assert len(result) == 1

    def test_keeps_different_emails(self) -> None:
        emails = [
            {
                "messageText": "Welcome to GitHub! Your account is ready. Start coding today."
            },
            {
                "messageText": "New security alert for your repository. Please review immediately."
            },
        ]
        result = _deduplicate_emails(emails)
        assert len(result) == 2

    def test_skips_empty_content(self) -> None:
        emails = [
            {"messageText": ""},
            {"messageText": "Valid content here from a platform notification"},
        ]
        result = _deduplicate_emails(emails)
        assert len(result) == 1

    def test_returns_original_if_all_empty(self) -> None:
        emails = [{"messageText": ""}, {"messageText": ""}]
        result = _deduplicate_emails(emails)
        # Falls back to original emails
        assert result == emails


# ---------------------------------------------------------------------------
# UsernameExtraction model
# ---------------------------------------------------------------------------


class TestUsernameExtraction:
    def test_basic_model(self) -> None:
        extraction = UsernameExtraction(username="octocat", confidence="high")
        assert extraction.username == "octocat"
        assert extraction.confidence == "high"


# ---------------------------------------------------------------------------
# extract_username_with_llm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExtractUsernameWithLLM:
    async def test_empty_emails_returns_not_found(self) -> None:
        result = await extract_username_with_llm("github", [])
        assert result == "NOT_FOUND"

    async def test_unknown_platform_returns_not_found(self) -> None:
        result = await extract_username_with_llm(
            "unknown_platform", [{"messageText": "hi"}]
        )
        assert result == "NOT_FOUND"

    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.init_llm")
    async def test_successful_extraction(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False

        # Mock the LLM chain
        mock_response = MagicMock()
        mock_response.content = '{"username": "octocat", "confidence": "high"}'

        mock_llm = MagicMock()
        mock_llm.with_config = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_init_llm.return_value = mock_llm

        emails = [
            {
                "messageText": "Welcome back, @octocat! Your PR was merged.",
                "subject": "PR merged",
            },
        ]

        result = await extract_username_with_llm("github", emails)
        assert result == "octocat"

    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.init_llm")
    async def test_cleans_at_symbol(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False

        mock_response = MagicMock()
        mock_response.content = '{"username": "@octocat", "confidence": "high"}'

        mock_llm = MagicMock()
        mock_llm.with_config = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_init_llm.return_value = mock_llm

        emails = [{"messageText": "Hello @octocat from GitHub", "subject": "Test"}]

        result = await extract_username_with_llm("github", emails)
        assert result == "octocat"

    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.init_llm")
    async def test_llm_error_returns_not_found(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False

        mock_llm = MagicMock()
        mock_llm.with_config = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM error"))
        mock_init_llm.return_value = mock_llm

        emails = [{"messageText": "Hello from GitHub notifications", "subject": "Test"}]

        result = await extract_username_with_llm("github", emails)
        assert result == "NOT_FOUND"

    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.init_llm")
    async def test_with_user_name_context(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False

        mock_response = MagicMock()
        mock_response.content = '{"username": "jdoe", "confidence": "high"}'

        mock_llm = MagicMock()
        mock_llm.with_config = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_init_llm.return_value = mock_llm

        emails = [{"messageText": "Welcome @jdoe to GitHub", "subject": "Test"}]

        result = await extract_username_with_llm("github", emails, user_name="John Doe")
        assert result == "jdoe"

    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.init_llm")
    async def test_short_content_skipped(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Emails with very short cleaned content are skipped."""
        mock_settings.DEBUG_EMAIL_PROCESSING = False

        mock_response = MagicMock()
        mock_response.content = '{"username": "NOT_FOUND", "confidence": "low"}'

        mock_llm = MagicMock()
        mock_llm.with_config = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_init_llm.return_value = mock_llm

        # Email with very short content after cleaning
        emails = [{"messageText": "hi", "subject": "Test"}]

        result = await extract_username_with_llm("github", emails)
        assert result == "NOT_FOUND"


# ---------------------------------------------------------------------------
# PLATFORM_CONFIG completeness
# ---------------------------------------------------------------------------


class TestPlatformConfig:
    @pytest.mark.parametrize("platform", list(PLATFORM_CONFIG.keys()))
    def test_all_platforms_have_required_keys(self, platform: str) -> None:
        config = PLATFORM_CONFIG[platform]
        assert "sender_domains" in config
        assert "url_template" in config
        assert "regex_pattern" in config
        assert len(config["sender_domains"]) > 0

    def test_expected_platforms_present(self) -> None:
        expected = {"twitter", "github", "linkedin", "reddit", "instagram"}
        assert expected.issubset(set(PLATFORM_CONFIG.keys()))
