"""Unit tests for the onboarding social profile extraction service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.llm.exceptions import LLMNotConfiguredError
from app.models.onboarding_models import SocialProfile, SocialProfileFilterOutput
from app.services.onboarding import social_profile_service as svc
from app.services.onboarding.social_profile_service import (
    _canonicalize_social_url,
    _extract_handle,
    _extract_urls_from_text,
    _is_generic_url,
    _is_tracking_url,
    _match_platform,
    dedup_profiles_by_platform,
    extract_social_profiles_from_emails,
    save_confirmed_profiles,
)


class _LLMStub:
    """Records what the service sent to the LLM and controls what comes back."""

    def __init__(self) -> None:
        self.owned_profiles: list[dict] = []
        self.error: Exception | None = None
        self.prompt: str = ""
        self.label: str | None = None
        self.structured_output_schema: type | None = None
        self.called = False


@pytest.fixture
def llm(monkeypatch):
    stub = _LLMStub()

    def fake_get_helper_llm():
        client = MagicMock()

        def with_structured_output(schema):
            stub.structured_output_schema = schema
            return "structured-llm"

        client.with_structured_output = with_structured_output
        return client

    async def fake_ainvoke_llm(structured_llm, messages, label=None):
        stub.called = True
        stub.prompt = messages[0].content
        stub.label = label
        if stub.error is not None:
            raise stub.error
        return SocialProfileFilterOutput(owned_profiles=stub.owned_profiles)

    monkeypatch.setattr(svc, "get_helper_llm", fake_get_helper_llm)
    monkeypatch.setattr(svc, "ainvoke_llm", fake_ainvoke_llm)
    return stub


@pytest.fixture
def no_llm(monkeypatch):
    def raise_not_configured():
        raise LLMNotConfiguredError("no llm configured")

    monkeypatch.setattr(svc, "get_helper_llm", raise_not_configured)


def _email(body: str, **overrides) -> dict:
    email = {"body": body, "sender": "friend@example.com", "subject": "hello"}
    email.update(overrides)
    return email


class TestIsTrackingUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://twitter.com/bob?utm_source=newsletter",
            "https://twitter.com/bob?UTM_MEDIUM=email",
            "https://twitter.com/bob?x=1&utm_campaign=spring",
        ],
    )
    def test_marketing_links_are_tracking(self, url):
        assert _is_tracking_url(url) is True

    def test_plain_profile_link_is_not_tracking(self):
        assert _is_tracking_url("https://twitter.com/bob?lang=en") is False


class TestExtractUrlsFromText:
    def test_finds_both_schemes(self):
        text = "see https://example.com/alice and http://example.com/bob"
        assert set(_extract_urls_from_text(text)) == {
            "https://example.com/alice",
            "http://example.com/bob",
        }

    @pytest.mark.parametrize(
        "delimiter", [" ", "\n", "\r", "\t", '"', "'", "<", ">", ")", "]", "}"]
    )
    def test_stops_at_delimiter(self, delimiter):
        text = f"link https://example.com/alice{delimiter}rest"
        assert _extract_urls_from_text(text) == ["https://example.com/alice"]

    def test_strips_trailing_sentence_punctuation(self):
        assert _extract_urls_from_text("go to https://example.com/alice.") == [
            "https://example.com/alice"
        ]

    def test_finds_every_occurrence(self):
        text = "https://example.com/a https://example.com/b https://example.com/c"
        assert _extract_urls_from_text(text) == [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]

    def test_rejects_url_too_short_to_be_real(self):
        assert _extract_urls_from_text("https://a.bcd") == []

    def test_keeps_url_just_over_the_minimum(self):
        assert _extract_urls_from_text("https://a.bcde") == ["https://a.bcde"]

    def test_bare_scheme_is_not_a_url(self):
        assert _extract_urls_from_text("https:// http://") == []


class TestMatchPlatform:
    @pytest.mark.parametrize(
        ("url", "platform", "handle"),
        [
            ("https://twitter.com/johnsmith", "twitter", "johnsmith"),
            ("https://x.com/johnsmith", "twitter", "johnsmith"),
            # The handle lives after /in/ — taking the first path segment would yield "in".
            ("https://www.linkedin.com/in/john-smith-123", "linkedin", "john-smith-123"),
            ("https://linkedin.com/company/acme", "linkedin", "acme"),
            ("https://github.com/octocat", "github", "octocat"),
            ("https://instagram.com/jane", "instagram", "jane"),
            ("https://facebook.com/jane", "facebook", "jane"),
            ("https://youtube.com/@creator", "youtube", "creator"),
            ("https://youtube.com/c/creator", "youtube", "creator"),
            ("https://youtube.com/channel/uc123", "youtube", "uc123"),
            ("https://medium.com/@writer", "medium", "writer"),
            ("https://tiktok.com/@dancer", "tiktok", "dancer"),
            ("https://mastodon.social/@fedi", "mastodon", "fedi"),
            ("https://bsky.app/profile/alice.bsky.social", "bluesky", "alice.bsky.social"),
            ("https://threads.net/@poster", "threads", "poster"),
        ],
    )
    def test_platform_and_handle_for_every_supported_domain(self, url, platform, handle):
        matched = _match_platform(url)
        assert matched is not None
        assert matched[0] == platform
        assert _extract_handle(matched[1]) == handle

    def test_unknown_domain_is_not_a_platform(self):
        assert _match_platform("https://example.com/alice") is None

    def test_handle_is_lowercased_for_stable_dedup(self):
        matched = _match_platform("https://twitter.com/JohnSmith")
        assert matched is not None
        assert _extract_handle(matched[1]) == "johnsmith"

    def test_deeper_path_is_dropped_from_handle(self):
        matched = _match_platform("https://github.com/octocat/hello-world")
        assert matched is not None
        assert _extract_handle(matched[1]) == "octocat"


class TestIsGenericUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://twitter.com/search",
            "https://twitter.com/intent/follow",
            "https://twitter.com/hashtag/python",
            "https://github.com/orgs/foo/settings",
            "https://medium.com/@about",
            "https://linkedin.com/jobs",
        ],
    )
    def test_navigation_urls_are_generic(self, url):
        assert _is_generic_url(url) is True

    def test_domain_without_path_is_generic(self):
        assert _is_generic_url("https://twitter.com") is True

    @pytest.mark.parametrize(
        "url",
        [
            # Each of these merely *contains* a generic word; none is a generic path.
            "https://github.com/homer",
            "https://github.com/explorer",
            "https://instagram.com/jobsmith",
            "https://x.com/help_desk",
            "https://twitter.com/sharon",
            "https://linkedin.com/in/aboutface",
        ],
    )
    def test_handles_that_merely_contain_a_generic_word_are_kept(self, url):
        assert _is_generic_url(url) is False

    def test_unparseable_url_is_treated_as_generic(self):
        assert _is_generic_url("https://[::1/twitter.com/bob") is True


class TestExtractHandle:
    def test_empty_remainder_has_no_handle(self):
        assert _extract_handle("") is None

    def test_handle_at_the_length_limit_is_kept(self):
        assert _extract_handle("a" * 60) == "a" * 60

    def test_handle_over_the_length_limit_is_rejected(self):
        assert _extract_handle("a" * 61) is None


class TestCanonicalizeSocialUrl:
    def test_strips_query_fragment_trailing_slash_and_lowercases_host(self):
        assert (
            _canonicalize_social_url("https://Twitter.COM/bob/?utm_source=x#bio")
            == "https://twitter.com/bob"
        )

    def test_unparseable_url_falls_back_to_trimmed_input(self):
        assert _canonicalize_social_url("https://[::1/bob/") == "https://[::1/bob"


class TestDedupProfilesByPlatform:
    def test_keeps_only_the_first_profile_per_platform(self):
        profiles = [
            SocialProfile(platform="twitter", url="https://twitter.com/first"),
            SocialProfile(platform="twitter", url="https://twitter.com/second"),
            SocialProfile(platform="github", url="https://github.com/first"),
        ]
        assert dedup_profiles_by_platform(profiles) == [
            SocialProfile(platform="twitter", url="https://twitter.com/first"),
            SocialProfile(platform="github", url="https://github.com/first"),
        ]

    def test_empty_input_returns_empty(self):
        assert dedup_profiles_by_platform([]) == []


class TestExtractSocialProfilesFromEmails:
    async def test_no_emails_yields_no_profiles_and_never_calls_the_llm(self, llm):
        assert await extract_social_profiles_from_emails([], "Bob", "bob@x.com") == []
        assert llm.called is False

    async def test_emails_without_social_links_yield_nothing(self, llm):
        emails = [_email("just a note about https://example.com/blog/post")]
        assert await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com") == []
        assert llm.called is False

    async def test_blank_email_is_skipped(self, llm):
        emails = [{"body": "", "sender": "", "subject": ""}]
        assert await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com") == []
        assert llm.called is False

    async def test_linkedin_profile_survives_extraction(self, llm):
        llm.owned_profiles = [{"platform": "linkedin", "handle": "john-smith-123"}]
        emails = [_email("resume: https://www.linkedin.com/in/john-smith-123")]

        result = await extract_social_profiles_from_emails(emails, "John", "john@x.com")

        assert result == [
            SocialProfile(platform="linkedin", url="https://www.linkedin.com/in/john-smith-123")
        ]
        assert "Handle: john-smith-123" in llm.prompt

    async def test_llm_receives_the_structured_schema_and_label(self, llm):
        await extract_social_profiles_from_emails(
            [_email("https://twitter.com/bob")], "Bob", "bob@x.com"
        )
        assert llm.structured_output_schema is SocialProfileFilterOutput
        assert llm.label == "onboarding_social_profile"

    async def test_prompt_carries_user_identity(self, llm):
        await extract_social_profiles_from_emails(
            [_email("https://twitter.com/bob")], "Bob Jones", "bob@x.com"
        )
        assert "Bob Jones" in llm.prompt
        assert "bob@x.com" in llm.prompt

    async def test_missing_user_identity_falls_back_to_unknown(self, llm):
        await extract_social_profiles_from_emails([_email("https://twitter.com/bob")], None, None)
        assert "User: Unknown (Unknown)" in llm.prompt

    async def test_repeated_link_in_one_email_counts_as_one_email(self, llm):
        body = "sig https://twitter.com/bob\n> quoted https://twitter.com/bob"
        await extract_social_profiles_from_emails([_email(body)], "Bob", "bob@x.com")

        assert "Appeared in 1 email(s)" in llm.prompt
        assert llm.prompt.count("Context 1") == 1
        assert "Context 2" not in llm.prompt

    async def test_link_across_distinct_emails_accumulates_frequency(self, llm):
        emails = [_email("https://twitter.com/bob") for _ in range(3)]
        await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")
        assert "Appeared in 3 email(s)" in llm.prompt

    async def test_context_list_is_capped(self, llm):
        emails = [
            _email("https://twitter.com/bob", snippet=f"snippet {i}", subject=f"subject {i}")
            for i in range(7)
        ]
        await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        assert "Appeared in 7 email(s)" in llm.prompt
        assert "Context 5" in llm.prompt
        assert "Context 6" not in llm.prompt

    async def test_context_fields_are_truncated(self, llm):
        emails = [
            _email(
                "https://twitter.com/bob",
                sender="s" * 200,
                subject="j" * 200,
                snippet="p" * 200,
            )
        ]
        await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        assert "s" * 100 in llm.prompt
        assert "s" * 101 not in llm.prompt
        assert "j" * 100 in llm.prompt
        assert "j" * 101 not in llm.prompt
        assert "p" * 120 in llm.prompt
        assert "p" * 121 not in llm.prompt

    async def test_generic_platform_links_are_not_candidates(self, llm):
        emails = [_email("trending on https://twitter.com/search and https://twitter.com/explore")]
        assert await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com") == []
        assert llm.called is False

    async def test_absurdly_long_handles_are_not_candidates(self, llm):
        emails = [_email(f"https://twitter.com/{'a' * 61}")]
        assert await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com") == []
        assert llm.called is False

    async def test_tracking_links_are_not_candidates(self, llm):
        emails = [_email("newsletter https://twitter.com/brand?utm_source=mailchimp")]
        assert await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com") == []
        assert llm.called is False

    async def test_sent_label_is_reported_to_the_llm(self, llm):
        emails = [_email("https://twitter.com/bob", labelIds=["SENT", "INBOX"])]
        await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")
        assert "Sent email: yes" in llm.prompt

    async def test_received_email_is_not_marked_sent(self, llm):
        emails = [_email("https://twitter.com/bob", labelIds=["INBOX"])]
        await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")
        assert "Sent email: no" in llm.prompt

    async def test_snake_case_label_key_is_understood(self, llm):
        emails = [_email("https://twitter.com/bob", label_ids=["SENT"])]
        await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")
        assert "Sent email: yes" in llm.prompt

    async def test_null_labels_do_not_crash_extraction(self, llm):
        llm.owned_profiles = [{"platform": "twitter", "handle": "bob"}]
        emails = [_email("https://twitter.com/bob", labelIds=None)]

        result = await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        assert result == [SocialProfile(platform="twitter", url="https://twitter.com/bob")]

    async def test_body_falls_back_to_snippet_then_message_text(self, llm):
        emails = [
            {"body": "", "snippet": "https://twitter.com/fromsnippet"},
            {"body": "", "snippet": "", "messageText": "https://github.com/fromtext"},
        ]
        await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        assert "Handle: fromsnippet" in llm.prompt
        assert "Handle: fromtext" in llm.prompt

    async def test_sender_and_subject_are_searched_for_links(self, llm):
        emails = [
            {"body": "no links here", "sender": "https://twitter.com/insender", "subject": ""},
            {"body": "no links here", "sender": "", "subject": "https://github.com/insubject"},
        ]
        await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        assert "Handle: insender" in llm.prompt
        assert "Handle: insubject" in llm.prompt

    async def test_candidates_are_capped_per_platform(self, llm):
        emails = [_email(f"https://github.com/user{i}") for i in range(10)]
        await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        kept = [f"user{i}" for i in range(10) if f"Handle: user{i} " in llm.prompt]
        assert len(kept) == 8

    async def test_sent_candidates_win_the_per_platform_cap(self, llm):
        emails = [_email(f"https://github.com/user{i}") for i in range(8) for _ in range(3)]
        emails.append(_email("https://github.com/mine", labelIds=["SENT"]))

        await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        assert "Handle: mine " in llm.prompt

    async def test_platforms_are_capped_independently(self, llm):
        emails = [_email(f"https://github.com/g{i} https://twitter.com/t{i}") for i in range(10)]
        await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        github_kept = sum(1 for i in range(10) if f"Handle: g{i} " in llm.prompt)
        twitter_kept = sum(1 for i in range(10) if f"Handle: t{i} " in llm.prompt)
        assert (github_kept, twitter_kept) == (8, 8)

    async def test_only_profiles_the_llm_owns_are_returned(self, llm):
        llm.owned_profiles = [{"platform": "twitter", "handle": "bob"}]
        emails = [_email("https://twitter.com/bob and https://twitter.com/someoneelse")]

        result = await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        assert result == [SocialProfile(platform="twitter", url="https://twitter.com/bob")]

    async def test_llm_choice_with_different_casing_still_resolves(self, llm):
        llm.owned_profiles = [{"platform": "Twitter", "handle": " Bob "}]
        emails = [_email("https://twitter.com/bob")]

        result = await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        assert result == [SocialProfile(platform="twitter", url="https://twitter.com/bob")]

    async def test_hallucinated_handle_is_discarded(self, llm):
        llm.owned_profiles = [{"platform": "twitter", "handle": "never-seen"}]
        emails = [_email("https://twitter.com/bob")]

        assert await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com") == []

    async def test_llm_item_missing_fields_is_discarded(self, llm):
        llm.owned_profiles = [{"platform": None, "handle": None}, {}]
        emails = [_email("https://twitter.com/bob")]

        assert await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com") == []

    async def test_owned_profiles_are_deduped_by_platform(self, llm):
        llm.owned_profiles = [
            {"platform": "twitter", "handle": "bob"},
            {"platform": "twitter", "handle": "bobby"},
        ]
        emails = [_email("https://twitter.com/bob https://twitter.com/bobby")]

        result = await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        assert result == [SocialProfile(platform="twitter", url="https://twitter.com/bob")]

    async def test_llm_failure_falls_back_to_sent_email_profiles(self, llm):
        llm.error = RuntimeError("llm exploded")
        emails = [
            _email("https://twitter.com/bob", labelIds=["SENT"]),
            _email("https://github.com/stranger", labelIds=["INBOX"]),
        ]

        result = await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        assert result == [SocialProfile(platform="twitter", url="https://twitter.com/bob")]

    async def test_llm_failure_without_sent_emails_yields_nothing(self, llm):
        llm.error = RuntimeError("llm exploded")
        emails = [_email("https://twitter.com/bob", labelIds=["INBOX"])]

        assert await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com") == []

    async def test_unconfigured_llm_falls_back_to_sent_email_profiles(self, no_llm):
        emails = [_email("https://twitter.com/bob", labelIds=["SENT"])]

        result = await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com")

        assert result == [SocialProfile(platform="twitter", url="https://twitter.com/bob")]

    async def test_llm_returning_nothing_owned_yields_nothing(self, llm):
        llm.owned_profiles = []
        emails = [_email("https://twitter.com/bob")]

        assert await extract_social_profiles_from_emails(emails, "Bob", "bob@x.com") == []


class TestSaveConfirmedProfiles:
    async def test_persists_profiles_for_the_user(self):
        profiles = [SocialProfile(platform="twitter", url="https://twitter.com/bob")]
        with patch.object(
            svc.user_repository, "set_social_profiles", new_callable=AsyncMock
        ) as set_profiles:
            await save_confirmed_profiles("user-1", profiles)

        set_profiles.assert_awaited_once_with(
            "user-1", [SocialProfile(platform="twitter", url="https://twitter.com/bob")]
        )

    async def test_persists_an_empty_list_to_clear_profiles(self):
        with patch.object(
            svc.user_repository, "set_social_profiles", new_callable=AsyncMock
        ) as set_profiles:
            await save_confirmed_profiles("user-1", [])

        set_profiles.assert_awaited_once_with("user-1", [])
