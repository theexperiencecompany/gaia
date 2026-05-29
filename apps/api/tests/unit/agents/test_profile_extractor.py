"""Behavior spec + tests for the LLM profile-username extractor.

UNIT: app/agents/memory/profile_extractor.py

The module turns a user's platform notification emails into validated, canonical
profile URLs. Six live functions carry all the logic; PLATFORM_CONFIG and the
UsernameExtraction model are static data exercised through those functions.

----------------------------------------------------------------------------
filter_emails_by_platform(emails, platform) -> list[dict]
EXPECTED: keep only emails whose sender domain belongs to `platform`, newest-
          capped at MAX_EMAILS_PER_PLATFORM (20); unknown platform -> [].
MECHANISM: read email["sender"] or fall back to email["from"], lowercase it,
           split on "@", take the last segment, strip a trailing ">" and
           whitespace, keep when the domain endswith any configured domain.
MUST-CATCH:
  - unknown platform short-circuits to [] (no domain matching attempted)
  - sender domain is matched by suffix against the platform's domain list,
    not against a different platform's domains
  - the "sender" field wins; "from" is only a fallback when sender is absent
  - matching is case-insensitive (.lower())
  - "GitHub <noreply@github.com>" form: split on "@", strip the trailing ">"
  - emails with no "@" in the sender are dropped (the `if "@" in sender` guard)
  - result is truncated to exactly MAX_EMAILS_PER_PLATFORM, not more

----------------------------------------------------------------------------
validate_username(username, platform) -> bool
EXPECTED: True iff a non-empty, non-"NOT_FOUND" username on a known platform
          matches that platform's regex (after stripping whitespace).
MUST-CATCH:
  - empty / "NOT_FOUND" -> False (the early guard)
  - unknown platform -> False
  - a username that violates the platform regex -> False (e.g. too long,
    leading hyphen on github)
  - leading/trailing whitespace is stripped before matching

----------------------------------------------------------------------------
build_profile_url(username, platform) -> str
EXPECTED: format the platform's url_template with the username; unknown
          platform -> "".
MUST-CATCH:
  - unknown platform -> "" (not a formatted URL)
  - the username is substituted into the real template (x.com/<u>,
    medium.com/@<u>, <u>.substack.com), not a constant

----------------------------------------------------------------------------
_filter_garbage_content(text) -> str
EXPECTED: strip HTML, fix encoding, and collapse runs of garbage characters,
          code fences, long bare URLs.
MUST-CATCH:
  - HTML tags are removed but the inner text survives
  - a run of >=6 identical non-alphanumeric chars is collapsed
  - ``` code fences and --- rules are removed
  - URLs of length >= 50 after the scheme are dropped

----------------------------------------------------------------------------
_deduplicate_emails(emails) -> list[dict]
EXPECTED: drop emails whose normalized body is >= the similarity threshold to
          an already-kept body; empty input -> []; if every body is empty,
          return the original list unchanged.
MUST-CATCH:
  - empty input -> [] (early return)
  - identical bodies collapse to one; distinct bodies are both kept
  - emails with empty/normalized-empty bodies are skipped
  - when nothing survives (all empty), the ORIGINAL list is returned, not []
  - similarity is compared with >= against the configured threshold

----------------------------------------------------------------------------
async extract_username_with_llm(platform, emails, user_name=None) -> str
EXPECTED: build a single prompt from deduplicated, cleaned emails, call the
          Gemini LLM, parse a UsernameExtraction, return the cleaned username;
          any failure or empty input -> "NOT_FOUND".
MECHANISM: init_llm(preferred_provider="gemini", fallback_enabled=True)
           .with_config(configurable={"model": PROFILE_EXTRACTION_LLM_MODEL});
           await llm.ainvoke(prompt); parse content (str or list of blocks);
           strip "@" and "\\n" from the username.
MUST-CATCH:
  - empty emails OR unknown platform -> "NOT_FOUND" without touching the LLM
  - init_llm is called with provider "gemini" and fallback_enabled=True
  - with_config receives the configured model id
  - the returned value is the LLM's parsed username, "@"-stripped
  - list-shaped content blocks are joined (Gemini multi-block responses)
  - any exception in the LLM path is swallowed -> "NOT_FOUND"
  - emails shorter than 20 chars after cleaning contribute no context, but a
    valid extraction still returns the username
  - user_name flows into the prompt as recipient context (vs the unknown default)

EQUIVALENT MUTANTS (justified survivors — behaviour-preserving, proven, excluded):
  - Docstring string-constants in every function (the `\"\"\"...\"\"\"` bodies): never
    executed, mutating to "" only blanks the docstring. Zero behavioural effect.
  - `log.info(...)` / `log.error(...)` f-string fragments and the `time.time() - start`
    `elapsed` computations that feed ONLY those log lines: a unit test asserting real
    behaviour cannot observe log text, and `elapsed` reaches no return value.
  - `json.dump(..., indent=2)` formatting constants: `json.loads` ignores indentation,
    so 2 -> 3 is byte-different on disk but value-identical when re-parsed.
  - The defensive `if not text1 or not text2: return 0.0` guard inside
    `_deduplicate_emails.calculate_similarity`: it is only ever called with two
    already-non-empty normalized bodies (each passed the `if not normalized: continue`
    check before being stored), so the guard is unreachable in production.
  - `content.replace("\\r\\n", " ").replace("\\n", " ")` (line 473): redundant with the
    subsequent `re.sub(r"\\s+", " ", content)` collapse — newlines are normalized to a
    single space either way, so removing the explicit replace is behaviour-preserving.
  - `os.makedirs(debug_dir, exist_ok=True)` -> `exist_ok=False`: in the single-pass debug
    test the directory does not pre-exist, so both raise nothing.
All other mutants in the live functions are killed by the tests below.
"""

import json
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
from app.constants.general import (
    MAX_EMAILS_PER_PLATFORM,
    PROFILE_EXTRACTION_LLM_MODEL,
    PROFILE_EXTRACTION_LLM_PROVIDER,
)

MODULE = "app.agents.memory.profile_extractor"


def _mock_llm(content: object) -> MagicMock:
    """An init_llm() return value whose ainvoke yields a response with `content`."""
    response = MagicMock()
    response.content = content
    llm = MagicMock()
    llm.with_config.return_value = llm
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


# ---------------------------------------------------------------------------
# filter_emails_by_platform
# ---------------------------------------------------------------------------


class TestFilterEmailsByPlatform:
    def test_keeps_only_platform_domains(self) -> None:
        emails = [
            {"sender": "noreply@github.com", "subject": "PR merged"},
            {"sender": "noreply@notifications.github.com", "subject": "New issue"},
            {"sender": "notify@twitter.com", "subject": "New follower"},
        ]
        result = filter_emails_by_platform(emails, "github")
        # Exactly the two github senders survive; the twitter one is dropped.
        assert [e["subject"] for e in result] == ["PR merged", "New issue"]

    def test_does_not_match_a_different_platforms_domain(self) -> None:
        # A twitter email must NOT match when filtering for github.
        emails = [{"sender": "notify@twitter.com", "subject": "x"}]
        assert filter_emails_by_platform(emails, "github") == []

    def test_unknown_platform_returns_empty(self) -> None:
        emails = [{"sender": "noreply@github.com"}]
        assert filter_emails_by_platform(emails, "unknown_platform") == []

    def test_sender_field_takes_precedence_over_from(self) -> None:
        # sender is a non-github domain; from is github. sender wins -> dropped.
        emails = [{"sender": "noreply@example.com", "from": "noreply@github.com"}]
        assert filter_emails_by_platform(emails, "github") == []

    def test_falls_back_to_from_when_sender_absent(self) -> None:
        emails = [{"from": "noreply@github.com", "subject": "Test"}]
        result = filter_emails_by_platform(emails, "github")
        assert len(result) == 1

    def test_missing_sender_and_from_is_dropped(self) -> None:
        emails = [{"subject": "No sender"}]
        assert filter_emails_by_platform(emails, "github") == []

    def test_sender_without_at_symbol_is_dropped(self) -> None:
        emails = [{"sender": "github.com"}]
        assert filter_emails_by_platform(emails, "github") == []

    def test_strips_trailing_angle_bracket(self) -> None:
        emails = [{"sender": "GitHub <noreply@github.com>"}]
        result = filter_emails_by_platform(emails, "github")
        assert len(result) == 1

    def test_case_insensitive_matching(self) -> None:
        emails = [{"sender": "NoReply@GitHub.COM"}]
        result = filter_emails_by_platform(emails, "github")
        assert len(result) == 1

    def test_truncates_to_max_per_platform(self) -> None:
        n = MAX_EMAILS_PER_PLATFORM + 7
        emails = [{"sender": "noreply@github.com", "subject": f"E{i}"} for i in range(n)]
        result = filter_emails_by_platform(emails, "github")
        assert len(result) == MAX_EMAILS_PER_PLATFORM
        # Truncation keeps the FIRST MAX_EMAILS_PER_PLATFORM (slice [:N]).
        assert result[0]["subject"] == "E0"
        assert result[-1]["subject"] == f"E{MAX_EMAILS_PER_PLATFORM - 1}"


# ---------------------------------------------------------------------------
# validate_username
# ---------------------------------------------------------------------------


class TestValidateUsername:
    def test_valid_github_username(self) -> None:
        assert validate_username("octocat", "github") is True

    def test_github_leading_hyphen_rejected(self) -> None:
        assert validate_username("-invalid", "github") is False

    def test_twitter_username_too_long_rejected(self) -> None:
        # twitter regex caps at 15 chars.
        assert validate_username("a" * 16, "twitter") is False

    def test_twitter_username_at_limit_accepted(self) -> None:
        assert validate_username("a" * 15, "twitter") is True

    def test_empty_username_rejected(self) -> None:
        assert validate_username("", "github") is False

    def test_not_found_sentinel_rejected(self) -> None:
        assert validate_username("NOT_FOUND", "github") is False

    def test_not_found_sentinel_rejected_even_when_regex_would_match(self) -> None:
        # reddit's regex (^[a-zA-Z0-9_-]{3,20}$) DOES match the literal string
        # "NOT_FOUND"; only the explicit sentinel guard (username == "NOT_FOUND")
        # keeps it out. This pins that guard.
        assert validate_username("NOT_FOUND", "reddit") is False

    def test_unknown_platform_rejected(self) -> None:
        assert validate_username("user", "unknown_platform") is False

    def test_strips_whitespace_before_matching(self) -> None:
        # Without .strip() the surrounding spaces would fail the ^...$ regex.
        assert validate_username("  jack  ", "twitter") is True

    def test_linkedin_allows_hyphen(self) -> None:
        assert validate_username("john-doe", "linkedin") is True

    def test_instagram_allows_period(self) -> None:
        assert validate_username("john.doe", "instagram") is True


# ---------------------------------------------------------------------------
# build_profile_url
# ---------------------------------------------------------------------------


class TestBuildProfileUrl:
    def test_github_url(self) -> None:
        assert build_profile_url("octocat", "github") == "https://github.com/octocat"

    def test_twitter_uses_x_domain(self) -> None:
        assert build_profile_url("jack", "twitter") == "https://x.com/jack"

    def test_substack_subdomain_template(self) -> None:
        assert build_profile_url("myblog", "substack") == "https://myblog.substack.com"

    def test_medium_at_prefixed_template(self) -> None:
        assert build_profile_url("user123", "medium") == "https://medium.com/@user123"

    def test_unknown_platform_returns_empty(self) -> None:
        assert build_profile_url("user", "unknown_platform") == ""


# ---------------------------------------------------------------------------
# _filter_garbage_content
# ---------------------------------------------------------------------------


class TestFilterGarbageContent:
    def test_strips_html_tags_and_separates_text_nodes(self) -> None:
        # bs4 get_text(separator=" ") joins the two text nodes with a space; the
        # exact output pins both the HTML strip and the separator (separator="" -> "HelloWorld").
        assert _filter_garbage_content("<p>Hello <b>World</b></p>") == "Hello  World"

    def test_collapses_long_run_of_special_chars(self) -> None:
        # A run of 10 '=' (>= 6) collapses to a single space; words survive verbatim.
        assert _filter_garbage_content("intro ========== outro") == "intro   outro"

    def test_short_run_of_special_chars_survives(self) -> None:
        # Only 3 '=' (< 6 trailing repeats) — left untouched (pins the {5,} bound).
        assert _filter_garbage_content("a === b") == "a === b"

    def test_removes_code_fences(self) -> None:
        # Exact output pins the ```lang fence removal; a no-op (empty-pattern) mutant
        # would leave space-separated backticks instead.
        assert _filter_garbage_content("```python\nprint(1)\n```") == " \nprint(1)\n "

    def test_removes_horizontal_rule_dashes(self) -> None:
        assert _filter_garbage_content("above ---- below") == "above   below"

    def test_drops_long_bare_url(self) -> None:
        # A URL whose path is >= 50 chars is replaced by a single space; exact output
        # pins the removal (an empty-pattern mutant would space out the whole URL).
        long_url = "https://example.com/" + "a" * 60
        assert _filter_garbage_content(f"see {long_url} now") == "see   now"

    def test_keeps_short_url_verbatim(self) -> None:
        # A URL under the 50-char path threshold is preserved exactly.
        assert _filter_garbage_content("see https://x.co/ab now") == "see https://x.co/ab now"


# ---------------------------------------------------------------------------
# _deduplicate_emails
# ---------------------------------------------------------------------------


class TestDeduplicateEmails:
    def test_empty_input_returns_empty(self) -> None:
        assert _deduplicate_emails([]) == []

    def test_distinct_bodies_both_kept(self) -> None:
        emails = [
            {"messageText": "Hello from GitHub about your pull request review"},
            {"messageText": "LinkedIn alert: a brand new professional connection"},
        ]
        assert len(_deduplicate_emails(emails)) == 2

    def test_identical_bodies_collapse_to_one(self) -> None:
        body = "Your pull request number was merged by the reviewer in the main repo"
        emails = [{"messageText": body}, {"messageText": body}]
        result = _deduplicate_emails(emails)
        assert len(result) == 1
        # The kept email is the first occurrence.
        assert result[0]["messageText"] == body

    def test_skips_email_with_empty_body(self) -> None:
        emails = [
            {"messageText": ""},
            {"messageText": "A valid platform notification with enough words to keep"},
        ]
        result = _deduplicate_emails(emails)
        assert len(result) == 1
        assert result[0]["messageText"].startswith("A valid")

    def test_all_empty_returns_original_list(self) -> None:
        emails = [{"messageText": ""}, {"messageText": "   "}]
        # Nothing survives normalization -> fall back to the original list, not [].
        assert _deduplicate_emails(emails) == emails

    def test_below_threshold_difference_keeps_both(self) -> None:
        # Two clearly different notifications stay distinct (similarity < 0.9).
        emails = [
            {"messageText": "Security alert detected suspicious sign in from a new device"},
            {"messageText": "Welcome aboard your starter guide is ready to explore today"},
        ]
        assert len(_deduplicate_emails(emails)) == 2

    def test_dedup_after_stripping_digits(self) -> None:
        # Bodies differ ONLY by long digit blocks; identical once digits are
        # stripped during normalization -> treated as one. (Pins the \d+ removal.)
        emails = [
            {"messageText": "123456789012345678901234567890 alpha beta gamma delta epsilon zeta"},
            {"messageText": "098765432109876543210987654321 alpha beta gamma delta epsilon zeta"},
        ]
        assert len(_deduplicate_emails(emails)) == 1

    def test_dedup_after_stripping_urls(self) -> None:
        # Identical once their long differing URLs are stripped. (Pins the URL removal.)
        emails = [
            {
                "messageText": "Please review your account at https://aaaaaaaaaaaaaaaaa.example.com/x now"
            },
            {
                "messageText": "Please review your account at https://bbbbbbbbbbbbbbbbb.example.org/y now"
            },
        ]
        assert len(_deduplicate_emails(emails)) == 1

    def test_dedup_after_stripping_email_addresses(self) -> None:
        # Identical once their differing email addresses are stripped. (Pins the \S+@\S+ removal.)
        emails = [
            {
                "messageText": "Message intended for aaaaaaaaaaaaaaaaa@aaaaaaaaaa.com regarding your digest"
            },
            {
                "messageText": "Message intended for bbbbbbbbbbbbbbbbb@bbbbbbbbbb.org regarding your digest"
            },
        ]
        assert len(_deduplicate_emails(emails)) == 1

    def test_dedup_after_stripping_punctuation(self) -> None:
        # Identical once punctuation is stripped. (Pins the [^\w\s] removal.)
        emails = [
            {
                "messageText": "Hello!!! Welcome,,, to the platform... enjoy your stay here today friend"
            },
            {
                "messageText": "Hello??? Welcome;;; to the platform!!! enjoy your stay here today friend"
            },
        ]
        assert len(_deduplicate_emails(emails)) == 1


# ---------------------------------------------------------------------------
# UsernameExtraction model
# ---------------------------------------------------------------------------


class TestUsernameExtraction:
    def test_round_trips_fields(self) -> None:
        extraction = UsernameExtraction(username="octocat", confidence="high")
        assert extraction.username == "octocat"
        assert extraction.confidence == "high"


# ---------------------------------------------------------------------------
# extract_username_with_llm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExtractUsernameWithLLM:
    async def test_empty_emails_returns_not_found_without_llm(self) -> None:
        with patch(f"{MODULE}.init_llm") as mock_init_llm:
            result = await extract_username_with_llm("github", [])
        assert result == "NOT_FOUND"
        mock_init_llm.assert_not_called()

    async def test_unknown_platform_returns_not_found_without_llm(self) -> None:
        with patch(f"{MODULE}.init_llm") as mock_init_llm:
            result = await extract_username_with_llm("unknown_platform", [{"messageText": "hi"}])
        assert result == "NOT_FOUND"
        mock_init_llm.assert_not_called()

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_returns_parsed_username_and_uses_gemini_config(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        llm = _mock_llm('{"username": "octocat", "confidence": "high"}')
        mock_init_llm.return_value = llm

        emails = [
            {
                "messageText": "Welcome back, @octocat! Your pull request has been merged today.",
                "subject": "PR merged",
            }
        ]
        result = await extract_username_with_llm("github", emails)

        assert result == "octocat"
        # LLM provider contract: gemini + fallback enabled, configured model id.
        mock_init_llm.assert_called_once_with(
            preferred_provider=PROFILE_EXTRACTION_LLM_PROVIDER, fallback_enabled=True
        )
        llm.with_config.assert_called_once_with(
            configurable={"model": PROFILE_EXTRACTION_LLM_MODEL}
        )

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_strips_at_symbol_from_username(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        mock_init_llm.return_value = _mock_llm('{"username": "@octocat", "confidence": "high"}')

        emails = [{"messageText": "Hello @octocat from GitHub notifications team", "subject": "x"}]
        result = await extract_username_with_llm("github", emails)
        assert result == "octocat"

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_strips_literal_backslash_n_from_username(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        # The model sometimes emits a literal "\\n" inside the handle; it must be
        # stripped (the .replace("\\n", "") step), not left in the returned username.
        mock_init_llm.return_value = _mock_llm(r'{"username": "oct\\nocat", "confidence": "high"}')

        emails = [{"messageText": "Hello @octocat from GitHub notifications team", "subject": "x"}]
        result = await extract_username_with_llm("github", emails)
        assert result == "octocat"

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_joins_list_content_blocks(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        # Gemini may return a list of content blocks that must be concatenated.
        blocks = [
            {"text": '{"username": "oct'},
            {"text": 'ocat", "confidence": "high"}'},
        ]
        mock_init_llm.return_value = _mock_llm(blocks)

        emails = [
            {"messageText": "Welcome back @octocat to GitHub, your PR merged.", "subject": "x"}
        ]
        result = await extract_username_with_llm("github", emails)
        assert result == "octocat"

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_llm_failure_is_swallowed_to_not_found(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        llm = MagicMock()
        llm.with_config.return_value = llm
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("LLM exploded"))
        mock_init_llm.return_value = llm

        emails = [
            {"messageText": "Hello from GitHub notifications about your account", "subject": "x"}
        ]
        result = await extract_username_with_llm("github", emails)
        assert result == "NOT_FOUND"

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_unparseable_content_is_swallowed_to_not_found(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        # Not valid JSON for the parser -> exception -> NOT_FOUND.
        mock_init_llm.return_value = _mock_llm("this is not structured output at all")

        emails = [
            {"messageText": "Hello from GitHub notifications about your account", "subject": "x"}
        ]
        result = await extract_username_with_llm("github", emails)
        assert result == "NOT_FOUND"

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_user_name_flows_into_prompt(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        llm = _mock_llm('{"username": "jdoe", "confidence": "high"}')
        mock_init_llm.return_value = llm

        emails = [
            {"messageText": "Welcome @jdoe to GitHub, your first PR was merged.", "subject": "x"}
        ]
        result = await extract_username_with_llm("github", emails, user_name="John Doe")

        assert result == "jdoe"
        # The recipient's real name must be embedded in the prompt sent to the LLM,
        # via the exact known-recipient phrasing (not the unknown-recipient default).
        prompt = llm.ainvoke.await_args.args[0]
        assert "The recipient's name is John Doe" in prompt
        assert "Look for usernames/handles associated with this person" in prompt
        assert "The recipient's name is unknown." not in prompt

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_unknown_recipient_default_context_when_no_user_name(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        llm = _mock_llm('{"username": "jdoe", "confidence": "high"}')
        mock_init_llm.return_value = llm

        emails = [
            {"messageText": "Welcome @jdoe to GitHub, your first PR was merged.", "subject": "x"}
        ]
        await extract_username_with_llm("github", emails)

        prompt = llm.ainvoke.await_args.args[0]
        assert "The recipient's name is unknown." in prompt

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_short_emails_excluded_from_prompt_context(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        llm = _mock_llm('{"username": "octocat", "confidence": "high"}')
        mock_init_llm.return_value = llm

        emails = [
            {"messageText": "hi", "subject": "tiny"},  # < 20 chars after cleaning -> skipped
            {
                "messageText": "Welcome back @octocat, your pull request has been merged successfully.",
                "subject": "real",
            },
        ]
        result = await extract_username_with_llm("github", emails)

        assert result == "octocat"
        prompt = llm.ainvoke.await_args.args[0]
        # The substantive email is included; the too-short one contributes no body.
        assert "your pull request has been merged successfully" in prompt
        assert "Content: hi" not in prompt
        # The enumerate index is assigned BEFORE the length-skip, so the kept
        # second email is "Email 2:" (the skipped "hi" consumed index 1). Its real
        # subject and extracted @mention appear on their labelled lines.
        assert "Email 2:" in prompt
        assert "Subject: real" in prompt
        assert "Mentions: @octocat" in prompt
        # The skipped short email's subject must NOT leak into the prompt.
        assert "tiny" not in prompt

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_content_at_length_boundary_is_kept(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        llm = _mock_llm('{"username": "bobby", "confidence": "high"}')
        mock_init_llm.return_value = llm

        # This body cleans to EXACTLY 20 chars; the guard is `len(content) < 20`,
        # so 20 is kept (a `< 21` mutant would wrongly drop it).
        emails = [{"messageText": "Hi @bobby see you ok", "subject": "x"}]
        await extract_username_with_llm("github", emails)

        prompt = llm.ainvoke.await_args.args[0]
        assert "Content: Hi @bobby see you ok" in prompt

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_missing_subject_uses_default_placeholder(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        llm = _mock_llm('{"username": "octocat", "confidence": "high"}')
        mock_init_llm.return_value = llm

        # No "subject" key -> the prompt uses the "[No Subject]" placeholder.
        emails = [{"messageText": "Welcome back @octocat, your pull request was just merged."}]
        await extract_username_with_llm("github", emails)

        prompt = llm.ainvoke.await_args.args[0]
        assert "Subject: [No Subject]" in prompt

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_no_mentions_renders_none_marker(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        llm = _mock_llm('{"username": "NOT_FOUND", "confidence": "low"}')
        mock_init_llm.return_value = llm

        # A body with no @mention -> the Mentions line is the literal "None".
        emails = [
            {
                "messageText": "Your weekly digest is ready with the latest community updates.",
                "subject": "x",
            }
        ]
        await extract_username_with_llm("github", emails)

        prompt = llm.ainvoke.await_args.args[0]
        assert "Mentions: None" in prompt

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_email_block_has_exact_labelled_layout(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        llm = _mock_llm('{"username": "octocat", "confidence": "high"}')
        mock_init_llm.return_value = llm

        emails = [
            {
                "messageText": "Welcome back @octocat, your pull request was merged by the team.",
                "subject": "PR merged",
            }
        ]
        await extract_username_with_llm("github", emails)

        prompt = llm.ainvoke.await_args.args[0]
        # The per-email block is newline-delimited in this exact order/labelling.
        expected_block = (
            "Email 1:\n"
            "Subject: PR merged\n"
            "Mentions: @octocat\n"
            "Content: Welcome back @octocat, your pull request was merged by the team.\n"
        )
        assert expected_block in prompt

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_multiple_mentions_listed_comma_separated(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        llm = _mock_llm('{"username": "octocat", "confidence": "high"}')
        mock_init_llm.return_value = llm

        emails = [
            {
                "messageText": "Thanks @octocat and @hubber for reviewing this pull request today.",
                "subject": "x",
            }
        ]
        await extract_username_with_llm("github", emails)

        prompt = llm.ainvoke.await_args.args[0]
        # Multiple @mentions are joined with ", " on the Mentions line.
        assert "Mentions: @octocat, @hubber" in prompt

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_multiple_emails_joined_with_separator(
        self, mock_init_llm: MagicMock, mock_settings: MagicMock
    ) -> None:
        mock_settings.DEBUG_EMAIL_PROCESSING = False
        llm = _mock_llm('{"username": "octocat", "confidence": "high"}')
        mock_init_llm.return_value = llm

        emails = [
            {
                "messageText": "First notice: your pull request was opened by the team lead.",
                "subject": "one",
            },
            {
                "messageText": "Second notice: a completely separate security review is pending now.",
                "subject": "two",
            },
        ]
        await extract_username_with_llm("github", emails)

        prompt = llm.ainvoke.await_args.args[0]
        # Two distinct emails are numbered and joined by the "---" separator block.
        assert "Email 1:" in prompt
        assert "Email 2:" in prompt
        assert "\n---\n" in prompt

    @patch(f"{MODULE}.settings")
    @patch(f"{MODULE}.init_llm")
    async def test_writes_debug_artifacts_when_enabled(
        self,
        mock_init_llm: MagicMock,
        mock_settings: MagicMock,
        tmp_path,
        monkeypatch,
    ) -> None:
        # Exercise the DEBUG_EMAIL_PROCESSING branches so their literals/keys are
        # covered by mutation. Redirect the module's __file__ dir into tmp_path so
        # debug_logs is written under the test sandbox.
        mock_settings.DEBUG_EMAIL_PROCESSING = True
        llm = _mock_llm('{"username": "octocat", "confidence": "high"}')
        mock_init_llm.return_value = llm

        fake_module_file = str(tmp_path / "profile_extractor.py")
        monkeypatch.setattr(f"{MODULE}.__file__", fake_module_file)

        emails = [
            {
                "messageText": "Welcome back @octocat, your pull request has been merged today.",
                "subject": "PR merged",
                "sender": "noreply@github.com",
            }
        ]
        result = await extract_username_with_llm("github", emails)

        assert result == "octocat"
        debug_dir = tmp_path / "debug_logs"
        dedup = json.loads((debug_dir / "github_deduplication.json").read_text())
        assert dedup["platform"] == "github"
        assert dedup["original_count"] == 1
        assert dedup["deduplicated_count"] == 1
        assert dedup["removed_count"] == 0
        # The per-email summary carries the real subject + sender of each kept email.
        assert dedup["unique_emails"] == [{"subject": "PR merged", "sender": "noreply@github.com"}]

        llm_input = json.loads((debug_dir / "github_llm_input.json").read_text())
        assert llm_input["platform"] == "github"
        assert llm_input["num_emails_sent"] == 1
        assert "your pull request has been merged today" in llm_input["emails_text"]
        # emails_text_length is the real character length of the assembled prompt body.
        assert llm_input["emails_text_length"] == len(llm_input["emails_text"])
        assert llm_input["emails_text_length"] > 0

        llm_output = json.loads((debug_dir / "github_llm_output.json").read_text())
        assert llm_output["platform"] == "github"
        assert llm_output["username"] == "octocat"
        assert llm_output["confidence"] == "high"
        # elapsed_seconds is a real non-negative timing; raw_response is the parsed JSON.
        assert llm_output["elapsed_seconds"] >= 0
        assert llm_output["raw_response"] == '{"username": "octocat", "confidence": "high"}'


# ---------------------------------------------------------------------------
# PLATFORM_CONFIG static contract (data integrity used by every function above)
# ---------------------------------------------------------------------------


class TestPlatformConfig:
    @pytest.mark.parametrize("platform", list(PLATFORM_CONFIG.keys()))
    def test_every_platform_is_fully_specified(self, platform: str) -> None:
        config = PLATFORM_CONFIG[platform]
        assert config["sender_domains"]
        # A valid {username} template and a usable regex are required by the
        # build/validate functions.
        assert "{username}" in config["url_template"]
        assert build_profile_url("testuser", platform).count("testuser") == 1
        assert validate_username("testuser", platform) is True
