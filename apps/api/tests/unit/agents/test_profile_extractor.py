"""Tests for profile extractor (LLM-based username extraction from emails)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, sentinel

import pytest

from app.agents.memory import profile_extractor as pe_module
from app.agents.memory.profile_extractor import (
    PLATFORM_CONFIG,
    UsernameExtraction,
    _deduplicate_emails,
    _filter_garbage_content,
    _write_debug_json,
    build_profile_url,
    extract_username_with_llm,
    validate_username,
)
from app.constants.log_tags import LogTag

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

    def test_twitter_max_length_boundary(self) -> None:
        assert validate_username("a" * 15, "twitter") is True
        assert validate_username("a" * 16, "twitter") is False

    def test_github_max_length_boundary(self) -> None:
        assert validate_username("a" * 39, "github") is True
        assert validate_username("a" * 40, "github") is False

    def test_github_hyphen_rules(self) -> None:
        assert validate_username("a-b-c", "github") is True
        assert validate_username("a-", "github") is False
        assert validate_username("-a", "github") is False

    def test_linkedin_min_length_boundary(self) -> None:
        assert validate_username("ab", "linkedin") is False
        assert validate_username("abc", "linkedin") is True

    def test_empty_username(self) -> None:
        assert validate_username("", "github") is False

    def test_whitespace_only_username(self) -> None:
        assert validate_username("   ", "github") is False

    def test_not_found_username(self) -> None:
        assert validate_username("NOT_FOUND", "github") is False

    def test_not_found_rejected_even_when_regex_would_match(self) -> None:
        # Twitter's regex accepts "NOT_FOUND" — the literal is rejected first.
        assert validate_username("NOT_FOUND", "twitter") is False

    def test_lowercase_not_found_is_just_a_username(self) -> None:
        assert validate_username("not_found", "twitter") is True

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

    def test_case_sensitive_match(self) -> None:
        assert validate_username("Jack", "twitter") is True

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

    @pytest.mark.parametrize("platform", list(PLATFORM_CONFIG.keys()))
    def test_url_matches_template_exactly(self, platform: str) -> None:
        url = build_profile_url("user123", platform)
        assert url == PLATFORM_CONFIG[platform]["url_template"].format(username="user123")


# ---------------------------------------------------------------------------
# _filter_garbage_content
# ---------------------------------------------------------------------------


class TestFilterGarbageContent:
    def test_removes_html_tags(self) -> None:
        result = _filter_garbage_content("<p>Hello <b>World</b></p>")
        assert "<p>" not in result
        assert "Hello" in result
        assert "World" in result

    def test_html_tags_exact_output(self) -> None:
        assert _filter_garbage_content("<p>Hello <b>World</b></p>") == "Hello  World"

    def test_html_entities_decoded(self) -> None:
        result = _filter_garbage_content("<p>Tom &amp; Jerry</p>")
        assert "&amp;" not in result
        assert "Tom & Jerry" in result

    def test_fixes_mojibake_encoding(self) -> None:
        assert _filter_garbage_content("cafÃ©") == "café"

    def test_normalizes_curly_quotes(self) -> None:
        assert _filter_garbage_content("don\u2019t") == "don't"

    def test_removes_repetitive_chars(self) -> None:
        result = _filter_garbage_content("text ========== more text")
        assert "==========" not in result

    def test_repetitive_chars_need_six(self) -> None:
        # The regex is `(non-alnum)\1{5,}` — the char plus five repeats.
        assert _filter_garbage_content("text ==== more text") == "text ==== more text"
        assert _filter_garbage_content("text ===== more text") == "text ===== more text"
        assert _filter_garbage_content("text ====== more text") == "text   more text"

    def test_repetitive_uppercase_replaced(self) -> None:
        # Negated class covers [a-zA-Z0-9@]; a lowercase-only mutant would
        # wrongly treat uppercase runs as garbage.
        assert _filter_garbage_content("text AAAAAA more text") == "text AAAAAA more text"

    def test_repetitive_lowercase_replaced(self) -> None:
        assert _filter_garbage_content("text aaaaaa more text") == "text aaaaaa more text"

    def test_removes_code_block_markers(self) -> None:
        result = _filter_garbage_content("```python\ncode\n```")
        assert "```" not in result

    def test_removes_bare_code_fence(self) -> None:
        assert _filter_garbage_content("```") == " "

    def test_code_fence_with_uppercase_lang(self) -> None:
        # ```Python: [a-z]* matches the empty prefix, so only the fence drops.
        assert _filter_garbage_content("```Python code here") == " Python code here"

    def test_removes_dashes(self) -> None:
        result = _filter_garbage_content("text ------- more text")
        assert "-------" not in result

    def test_short_dash_run_preserved(self) -> None:
        assert _filter_garbage_content("text -- more text") == "text -- more text"
        assert _filter_garbage_content("text --- more text") == "text   more text"

    def test_removes_long_urls(self) -> None:
        long_url = "https://example.com/" + "a" * 60
        result = _filter_garbage_content(f"Check {long_url} out")
        assert result == "Check   out"

    def test_long_url_boundary(self) -> None:
        # URLs whose non-space tail after :// is < 50 chars survive; >= 50 are dropped.
        kept = "https://" + "a" * 49
        removed = "https://" + "a" * 50
        assert kept in _filter_garbage_content(f"See {kept} now")
        assert removed not in _filter_garbage_content(f"See {removed} now")

    def test_short_url_preserved(self) -> None:
        url = "https://example.com/abc"
        result = _filter_garbage_content(f"Check {url} out")
        assert url in result

    def test_preserves_short_text(self) -> None:
        text = "Hello, @username! Welcome back."
        result = _filter_garbage_content(text)
        assert "@username" in result

    def test_empty_text(self) -> None:
        assert _filter_garbage_content("") == ""


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
            {"messageText": "Welcome to GitHub! Your account is ready. Start coding today."},
            {"messageText": "New security alert for your repository. Please review immediately."},
        ]
        result = _deduplicate_emails(emails)
        assert len(result) == 2

    def test_digits_normalized(self) -> None:
        # Only differing in numeric IDs — treated as duplicates.
        emails = [
            {"messageText": "Your PR #123 was merged into main"},
            {"messageText": "Your PR #456 was merged into main"},
        ]
        result = _deduplicate_emails(emails)
        assert result == [emails[0]]

    def test_digits_at_content_edges_normalized(self) -> None:
        emails = [
            {"messageText": "abc123"},
            {"messageText": "abc"},
        ]
        result = _deduplicate_emails(emails)
        assert result == [emails[0]]

    def test_urls_normalized(self) -> None:
        emails = [
            {"messageText": "See https://a.example/x for the full details"},
            {"messageText": "See https://b.example/y for the full details"},
        ]
        result = _deduplicate_emails(emails)
        assert result == [emails[0]]

    def test_email_addresses_normalized(self) -> None:
        emails = [
            {"messageText": "Contact a@b.com about the update"},
            {"messageText": "Contact c@d.com about the update"},
        ]
        result = _deduplicate_emails(emails)
        assert result == [emails[0]]

    def test_case_insensitive_duplicates(self) -> None:
        emails = [
            {"messageText": "HELLO WORLD from the team"},
            {"messageText": "hello world from the team"},
        ]
        result = _deduplicate_emails(emails)
        assert result == [emails[0]]

    def test_punctuation_normalized(self) -> None:
        emails = [
            {"messageText": "Hello, world! We are live."},
            {"messageText": "Hello world we are live"},
        ]
        result = _deduplicate_emails(emails)
        assert result == [emails[0]]

    def test_whitespace_normalized(self) -> None:
        emails = [
            {"messageText": "hello world"},
            {"messageText": "hello  world"},
        ]
        result = _deduplicate_emails(emails)
        assert result == [emails[0]]

    def test_similarity_at_threshold_is_duplicate(self) -> None:
        # SequenceMatcher ratio of these two is exactly 0.9 == threshold.
        emails = [
            {"messageText": "aaaaaaaaab"},
            {"messageText": "aaaaaaaaac"},
        ]
        result = _deduplicate_emails(emails)
        assert result == [emails[0]]

    def test_similarity_below_threshold_kept(self) -> None:
        # SequenceMatcher ratio is 0.875 < 0.9.
        emails = [
            {"messageText": "aaaaaaab"},
            {"messageText": "aaaaaaac"},
        ]
        result = _deduplicate_emails(emails)
        assert result == emails

    def test_skips_empty_content(self) -> None:
        emails = [
            {"messageText": ""},
            {"messageText": "Valid content here from a platform notification"},
        ]
        result = _deduplicate_emails(emails)
        assert len(result) == 1

    def test_skips_missing_message_text(self) -> None:
        emails = [
            {"subject": "no body at all"},
            {"messageText": "Valid content here from a platform notification"},
        ]
        result = _deduplicate_emails(emails)
        assert result == [emails[1]]

    def test_skips_whitespace_only_content(self) -> None:
        emails = [
            {"messageText": "   "},
            {"messageText": "Valid content here from a platform notification"},
        ]
        result = _deduplicate_emails(emails)
        assert result == [emails[1]]

    def test_returns_original_if_all_empty(self) -> None:
        emails = [{"messageText": ""}, {"messageText": ""}]
        result = _deduplicate_emails(emails)
        # Falls back to original emails
        assert result == emails

    def test_returns_original_if_all_normalize_empty(self) -> None:
        emails = [
            {"messageText": "12345"},
            {"messageText": "https://a.com"},
            {"messageText": "a@b.com"},
        ]
        result = _deduplicate_emails(emails)
        assert result == emails


# ---------------------------------------------------------------------------
# _write_debug_json
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWriteDebugJson:
    @patch("app.agents.memory.profile_extractor.Path")
    @patch("app.agents.memory.profile_extractor.settings")
    async def test_debug_disabled_skips_write(
        self, mock_settings: MagicMock, mock_path: MagicMock, tmp_path: object
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        await _write_debug_json("github", "llm_input", {"platform": "github"})
        mock_path.assert_not_called()
        assert not (Path(tmp_path) / "debug_logs").exists()

    @patch("app.agents.memory.profile_extractor.Path")
    @patch("app.agents.memory.profile_extractor.settings")
    async def test_debug_enabled_writes_payload(
        self, mock_settings: MagicMock, mock_path: MagicMock, tmp_path: object
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = True
        mock_path.side_effect = lambda part: Path(tmp_path) / "__root__"
        payload = {"platform": "github", "count": 2}
        await _write_debug_json("github", "llm_input", payload)
        mock_path.assert_called_once_with(pe_module.__file__)
        target = Path(tmp_path) / "debug_logs" / "github_llm_input.json"
        assert target.read_text(encoding="utf-8") == json.dumps(payload, indent=2)


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
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_empty_emails_returns_not_found(
        self, mock_ainvoke_structured: AsyncMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        result = await extract_username_with_llm("github", [], user_id="u1")
        assert result == "NOT_FOUND"
        mock_ainvoke_structured.assert_not_awaited()

    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_unknown_platform_returns_not_found(
        self, mock_ainvoke_structured: AsyncMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        result = await extract_username_with_llm(
            "unknown_platform", [{"messageText": "hi"}], user_id="u1"
        )
        assert result == "NOT_FOUND"
        mock_ainvoke_structured.assert_not_awaited()

    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_successful_extraction(
        self, mock_ainvoke_structured: AsyncMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )

        emails = [
            {
                "messageText": "Welcome back, @octocat! Your PR was merged.",
                "subject": "PR merged",
            },
        ]

        result = await extract_username_with_llm("github", emails, user_id="u1")
        assert result == "octocat"

    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_cleans_at_symbol(
        self, mock_ainvoke_structured: AsyncMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="@octocat", confidence="high"
        )

        emails = [{"messageText": "Hello @octocat from GitHub", "subject": "Test"}]

        result = await extract_username_with_llm("github", emails, user_id="u1")
        assert result == "octocat"

    @patch("app.agents.memory.profile_extractor.log")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_llm_error_returns_not_found(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.side_effect = RuntimeError("LLM error")

        emails = [{"messageText": "Hello from GitHub notifications", "subject": "Test"}]

        result = await extract_username_with_llm("github", emails, user_id="u1")
        assert result == "NOT_FOUND"

        error_call = next(
            c
            for c in mock_log.error.call_args_list
            if c.args[0] == f"{LogTag.MEMORY} LLM username extraction failed"
        )
        assert error_call.kwargs["platform"] == "github"
        assert error_call.kwargs["duration_s"] == 0.0
        assert isinstance(error_call.kwargs["duration_s"], float)
        assert error_call.kwargs["error_type"] == "RuntimeError"
        assert error_call.kwargs["error"] == "LLM error"

    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_with_user_name_context(
        self, mock_ainvoke_structured: AsyncMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="jdoe", confidence="high"
        )

        emails = [{"messageText": "Welcome @jdoe to GitHub", "subject": "Test"}]

        result = await extract_username_with_llm(
            "github", emails, user_name="John Doe", user_id="u1"
        )
        assert result == "jdoe"

    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_short_content_skipped(
        self, mock_ainvoke_structured: AsyncMock, mock_settings: MagicMock
    ) -> None:
        """Emails with very short cleaned content are skipped."""
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="NOT_FOUND", confidence="low"
        )

        # Email with very short content after cleaning
        emails = [{"messageText": "hi", "subject": "Test"}]

        result = await extract_username_with_llm("github", emails, user_id="u1")
        assert result == "NOT_FOUND"
        assert "Email 1:" not in mock_ainvoke_structured.call_args.args[1]

    @patch("app.agents.memory.profile_extractor.log")
    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_exact_llm_args_and_logs(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_metered_config.return_value = sentinel.config
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )

        emails = [
            {
                "subject": "PR merged",
                "messageText": "Welcome back, @octocat! Your pull request was merged.",
            },
        ]
        await extract_username_with_llm("github", emails, user_name="John Doe", user_id="u1")

        mock_ainvoke_structured.assert_awaited_once()
        mock_metered_config.assert_called_once_with("u1")
        args, kwargs = mock_ainvoke_structured.call_args
        assert args[0] is UsernameExtraction
        assert kwargs["label"] == "profile_extraction"
        assert kwargs["config"] is sentinel.config

        prompt = args[1]
        assert "github" in prompt
        assert "The recipient's name is John Doe." in prompt
        assert "Email 1:" in prompt
        assert "Subject: PR merged" in prompt
        assert "Mentions: @octocat" in prompt
        assert "Welcome back, @octocat! Your pull request was merged." in prompt

        mock_log.info.assert_any_call(
            f"{LogTag.MEMORY} Deduplicated platform emails",
            platform="github",
            email_count=1,
            unique_count=1,
        )
        extracted_call = next(
            c
            for c in mock_log.info.call_args_list
            if c.args[0] == f"{LogTag.MEMORY} LLM extracted username"
        )
        assert extracted_call.kwargs["platform"] == "github"
        assert extracted_call.kwargs["username"] == "octocat"
        assert extracted_call.kwargs["confidence"] == "high"
        assert extracted_call.kwargs["duration_s"] == 0.0
        assert isinstance(extracted_call.kwargs["duration_s"], float)

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_unknown_user_context(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        emails = [
            {
                "subject": "PR merged",
                "messageText": "Welcome back, @octocat! Your pull request was merged.",
            },
        ]
        await extract_username_with_llm("github", emails, user_id="u1")

        args, _ = mock_ainvoke_structured.call_args
        prompt = args[1]
        assert "The recipient's name is unknown." in prompt

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_content_cleaned_in_prompt(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        """Newlines and repeated whitespace are collapsed in the prompt."""
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        emails = [
            {
                "subject": "Test",
                "messageText": "Hello\r\nworld  and beyond this is long enough text",
            },
        ]
        await extract_username_with_llm("github", emails, user_id="u1")

        args, _ = mock_ainvoke_structured.call_args
        prompt = args[1]
        assert "Hello\r\nworld" not in prompt
        assert "Hello world and beyond this is long enough text" in prompt
        assert "XX" not in prompt

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_default_subject(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        emails = [
            {
                "messageText": "Welcome back, @octocat! Your pull request was merged.",
            },
        ]
        await extract_username_with_llm("github", emails, user_id="u1")

        args, _ = mock_ainvoke_structured.call_args
        prompt = args[1]
        assert "[No Subject]" in prompt

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_content_length_boundary(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        # 19-char content is dropped; 20-char content is included.
        await extract_username_with_llm(
            "github", [{"subject": "s", "messageText": "a" * 19}], user_id="u1"
        )
        assert "Email 1:" not in mock_ainvoke_structured.call_args.args[1]

        await extract_username_with_llm(
            "github", [{"subject": "s", "messageText": "a" * 20}], user_id="u1"
        )
        assert "Email 1:" in mock_ainvoke_structured.call_args.args[1]

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_short_email_before_long_kept(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        """A short email is skipped, not treated as end of the list."""
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        emails = [
            {"subject": "s", "messageText": ""},
            {
                "subject": "s",
                "messageText": "A valid long enough notification body here for real",
            },
        ]
        await extract_username_with_llm("github", emails, user_id="u1")

        args, _ = mock_ainvoke_structured.call_args
        assert "Email 1:" in args[1]

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_mentions_from_raw_content(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        """Mentions are harvested from the raw text, including inside HTML attrs
        that do not survive cleaning."""
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        raw = '<a href="@octocat">click here</a> for more information about this thing ok'
        await extract_username_with_llm(
            "github", [{"subject": "s", "messageText": raw}], user_id="u1"
        )

        args, _ = mock_ainvoke_structured.call_args
        prompt = args[1]
        assert "Mentions: @octocat" in prompt

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_uppercase_mention_kept(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        raw = '<a href="@OctoCat">click here</a> for more information about this thing ok'
        await extract_username_with_llm(
            "github", [{"subject": "s", "messageText": raw}], user_id="u1"
        )

        args, _ = mock_ainvoke_structured.call_args
        prompt = args[1]
        assert "Mentions: @OctoCat" in prompt

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_multiple_mentions_joined(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        raw = "@alice mentioned @bob in a thread with plenty of context here ok"
        await extract_username_with_llm(
            "github", [{"subject": "s", "messageText": raw}], user_id="u1"
        )

        args, _ = mock_ainvoke_structured.call_args
        prompt = args[1]
        assert "Mentions: @alice, @bob" in prompt

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_no_mentions_reported_as_none(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        raw = "A completely plain notification body with plenty of context here ok"
        await extract_username_with_llm(
            "github", [{"subject": "s", "messageText": raw}], user_id="u1"
        )

        args, _ = mock_ainvoke_structured.call_args
        prompt = args[1]
        assert "Mentions: None" in prompt

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_deduplicates_before_llm(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        emails = [
            {
                "subject": "PR merged",
                "messageText": "Your PR #123 was merged into main by the team",
            },
            {
                "subject": "PR merged",
                "messageText": "Your PR #456 was merged into main by the team",
            },
        ]
        await extract_username_with_llm("github", emails, user_id="u1")

        mock_ainvoke_structured.assert_awaited_once()
        prompt = mock_ainvoke_structured.call_args.args[1]
        assert prompt.count("Email 1:") == 1
        assert "Email 2:" not in prompt
        assert "---" not in prompt

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_multiple_emails_joined(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        emails = [
            {
                "subject": "PR merged",
                "messageText": "Your pull request was merged into main by the team",
            },
            {
                "subject": "Security alert",
                "messageText": "A new device signed in to your account this morning",
            },
        ]
        await extract_username_with_llm("github", emails, user_id="u1")

        prompt = mock_ainvoke_structured.call_args.args[1]
        assert "Email 1:" in prompt
        assert "Email 2:" in prompt
        assert "---" in prompt
        assert "Subject: Security alert" in prompt

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_cleans_backslash_n(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octo\\ncat", confidence="high"
        )
        emails = [{"subject": "Test", "messageText": "Hello from GitHub notifications"}]
        result = await extract_username_with_llm("github", emails, user_id="u1")
        assert result == "octocat"

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_strips_username_whitespace(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="  octocat  ", confidence="high"
        )
        emails = [{"subject": "Test", "messageText": "Hello from GitHub notifications"}]
        result = await extract_username_with_llm("github", emails, user_id="u1")
        assert result == "octocat"

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_removes_all_at_symbols(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="@@octo@cat", confidence="high"
        )
        emails = [{"subject": "Test", "messageText": "Hello from GitHub notifications"}]
        result = await extract_username_with_llm("github", emails, user_id="u1")
        assert result == "octocat"

    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_not_found_passthrough(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="NOT_FOUND", confidence="low"
        )
        emails = [{"subject": "Test", "messageText": "Hello from GitHub notifications"}]
        result = await extract_username_with_llm("github", emails, user_id="u1")
        assert result == "NOT_FOUND"

    @patch("app.agents.memory.profile_extractor.Path")
    @patch("app.agents.memory.profile_extractor.metered_config")
    @patch("app.agents.memory.profile_extractor.settings")
    @patch("app.agents.memory.profile_extractor.ainvoke_structured", new_callable=AsyncMock)
    async def test_debug_payloads_written(
        self,
        mock_ainvoke_structured: AsyncMock,
        mock_settings: MagicMock,
        mock_metered_config: MagicMock,
        mock_path: MagicMock,
        tmp_path: object,
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = True
        mock_path.side_effect = lambda part: Path(tmp_path) / "__root__"
        mock_ainvoke_structured.return_value = UsernameExtraction(
            username="octocat", confidence="high"
        )
        emails = [
            {
                "subject": "PR merged",
                "messageText": "Your PR #123 was merged into main by the team",
                "sender": "github@example.com",
            },
            {
                "subject": "PR merged",
                "messageText": "Your PR #456 was merged into main by the team",
                "sender": "github@example.com",
            },
        ]
        await extract_username_with_llm("github", emails, user_id="u1")

        mock_path.assert_called_with(pe_module.__file__)
        debug_dir = Path(tmp_path) / "debug_logs"

        dedup_payload = json.loads(
            (debug_dir / "github_deduplication.json").read_text(encoding="utf-8")
        )
        assert dedup_payload == {
            "platform": "github",
            "original_count": 2,
            "deduplicated_count": 1,
            "removed_count": 1,
            "unique_emails": [{"subject": "PR merged", "sender": "github@example.com"}],
        }

        llm_input_payload = json.loads(
            (debug_dir / "github_llm_input.json").read_text(encoding="utf-8")
        )
        assert llm_input_payload["platform"] == "github"
        assert llm_input_payload["num_emails_sent"] == 1
        assert llm_input_payload["emails_text_length"] == len(llm_input_payload["emails_text"])
        assert "Email 1:" in llm_input_payload["emails_text"]
        assert "Subject: PR merged" in llm_input_payload["emails_text"]

        llm_output_payload = json.loads(
            (debug_dir / "github_llm_output.json").read_text(encoding="utf-8")
        )
        assert llm_output_payload["platform"] == "github"
        assert llm_output_payload["username"] == "octocat"
        assert llm_output_payload["confidence"] == "high"
        assert llm_output_payload["result"] == {
            "username": "octocat",
            "confidence": "high",
        }
        assert 0 <= llm_output_payload["elapsed_seconds"] < 60


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

    @pytest.mark.parametrize("platform", list(PLATFORM_CONFIG.keys()))
    def test_url_template_single_placeholder(self, platform: str) -> None:
        assert PLATFORM_CONFIG[platform]["url_template"].count("{username}") == 1

    def test_expected_platforms_present(self) -> None:
        expected = {"twitter", "github", "linkedin", "reddit", "instagram"}
        assert expected.issubset(set(PLATFORM_CONFIG.keys()))
