"""Unit tests for the individual DAG nodes in intelligence_service.

Each _run_* node is a fail-soft wrapper: it must emit its stage and return a
usable default even when its dependency raises, because the pipeline gathers all
of them and a leaked exception would abort the personalization run. These tests
pin that contract down, node by node, faking only the service/repository
boundaries.

Production bugs found while writing these tests and fixed at the root are marked
with a "BUG:" comment.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.memory.email_processor import OnboardingFetchOptions
from app.constants.email import ONBOARDING_EMAIL_SCAN_LIMIT
from app.constants.onboarding import TRIAGE_EARLY_THRESHOLD
from app.models.onboarding_models import (
    EmailSummary,
    InboxTriage,
    ProfileCardDesign,
    SocialProfile,
    UserProfileMetadata,
    WritingStyleExampleBlocks,
    WritingStyleProfile,
)
from app.models.user_models import BioStatus, UserDocument
from app.services.onboarding.intelligence_service import (
    InboxScanContext,
    OnboardingContext,
    _persist_profiles,
    _persist_social_profiles,
    _run_holo_card,
    _run_inbox_scanning,
    _run_social_profiles,
    _run_triage,
    _run_writing_style,
)

MODULE = "app.services.onboarding.intelligence_service"
USER = "user-42"


def _ctx(**overrides: Any) -> OnboardingContext:
    defaults: dict[str, Any] = {
        "user_id": USER,
        "name": "Ann",
        "profession": "dev",
        "focus": "ship v2",
    }
    defaults.update(overrides)
    return OnboardingContext(**defaults)


def _triage(**overrides: Any) -> InboxTriage:
    payload: dict[str, Any] = {
        "total_scanned": 100,
        "total_unread": 12,
        "summary": "Busy inbox",
        "important_emails": [
            EmailSummary(sender="a@x.com", subject="Contract", why_important="deadline")
        ],
        "patterns": ["newsletters"],
    }
    payload.update(overrides)
    return InboxTriage(**payload)


def _style() -> WritingStyleProfile:
    return WritingStyleProfile(summary="Terse", example=WritingStyleExampleBlocks(body=["Thanks."]))


@pytest.fixture(autouse=True)
def quiet_logs() -> Any:
    with patch(f"{MODULE}.log", MagicMock()):
        yield


# ---------------------------------------------------------------------------
# _emit_stage
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _run_inbox_scanning
# ---------------------------------------------------------------------------


@pytest.fixture
def scan_cache() -> Any:
    with patch(f"{MODULE}.inbox_scan_cache") as cache:
        cache.get = AsyncMock(return_value=None)
        cache.put = AsyncMock()
        yield cache


class TestRunInboxScanning:
    async def test_a_cache_hit_short_circuits_the_fetch(self, scan_cache: Any) -> None:
        scan_cache.get = AsyncMock(return_value=[{"id": "1"}, {"id": "2"}])
        ctx = InboxScanContext()
        fetch = AsyncMock()

        with patch(f"{MODULE}.fetch_emails_for_onboarding", fetch):
            await _run_inbox_scanning(USER, ctx)

        assert fetch.await_count == 0
        assert ctx.emails == [{"id": "1"}, {"id": "2"}]
        assert ctx.first_batch_ready.is_set()
        assert ctx.done.is_set()

    async def test_a_cache_hit_is_not_written_back(self, scan_cache: Any) -> None:
        scan_cache.get = AsyncMock(return_value=[{"id": "1"}])
        with patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock()):
            await _run_inbox_scanning(USER, InboxScanContext())

        assert scan_cache.put.await_count == 0

    async def test_fetched_emails_are_cached(self, scan_cache: Any) -> None:
        async def fetch(user_id: str, **kwargs: Any) -> None:
            kwargs["into"].append({"id": "1"})

        with patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(side_effect=fetch)):
            await _run_inbox_scanning(USER, InboxScanContext())

        assert scan_cache.put.await_args.args[:2] == (USER, "metadata")
        assert scan_cache.put.await_args.args[2] == [{"id": "1"}]

    async def test_fetch_is_scoped_to_the_onboarding_window(self, scan_cache: Any) -> None:
        fetch = AsyncMock()
        ctx = InboxScanContext()
        with patch(f"{MODULE}.fetch_emails_for_onboarding", fetch):
            await _run_inbox_scanning(USER, ctx)

        kwargs = fetch.await_args.kwargs
        assert kwargs["months"] == 1
        assert kwargs["max_total"] == ONBOARDING_EMAIL_SCAN_LIMIT
        assert kwargs["into"] is ctx.emails

    async def test_events_are_set_even_when_the_fetch_raises(self, scan_cache: Any) -> None:
        # Triage waits on first_batch_ready; leaving it unset would hang the DAG.
        ctx = InboxScanContext()
        with patch(
            f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(side_effect=RuntimeError("gmail"))
        ):
            await _run_inbox_scanning(USER, ctx)

        assert ctx.first_batch_ready.is_set()
        assert ctx.done.is_set()

    async def test_a_failed_fetch_is_not_cached(self, scan_cache: Any) -> None:
        # Caching a partial scan would make the retry reuse the truncated result.
        with patch(
            f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(side_effect=RuntimeError("gmail"))
        ):
            await _run_inbox_scanning(USER, InboxScanContext())

        assert scan_cache.put.await_count == 0

    # BUG: the closing "inbox_scanning done" line hardcoded outcome="ok", so a
    # failed Gmail fetch looked successful in the wide-event stream.
    async def test_failure_is_reported_as_failed_not_ok(self, scan_cache: Any) -> None:
        with (
            patch(f"{MODULE}.log") as log,
            patch(
                f"{MODULE}.fetch_emails_for_onboarding",
                AsyncMock(side_effect=RuntimeError("gmail")),
            ),
        ):
            await _run_inbox_scanning(USER, InboxScanContext())

        done = [c for c in log.info.call_args_list if "inbox_scanning done" in str(c)]
        assert done, "no completion line emitted"
        assert done[-1].kwargs["outcome"] == "failed"

    async def test_success_is_reported_as_ok(self, scan_cache: Any) -> None:
        with (
            patch(f"{MODULE}.log") as log,
            patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock()),
        ):
            await _run_inbox_scanning(USER, InboxScanContext())

        done = [c for c in log.info.call_args_list if "inbox_scanning done" in str(c)]
        assert done[-1].kwargs["outcome"] == "ok"

    async def test_batch_callback_releases_triage_at_the_threshold(self, scan_cache: Any) -> None:
        ctx = InboxScanContext()
        seen: list[bool] = []

        async def fetch(user_id: str, **kwargs: Any) -> None:
            on_batch = kwargs["on_batch"]
            await on_batch(TRIAGE_EARLY_THRESHOLD - 1, "a@x.com")
            seen.append(ctx.first_batch_ready.is_set())
            await on_batch(TRIAGE_EARLY_THRESHOLD, "b@x.com")
            seen.append(ctx.first_batch_ready.is_set())

        with patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(side_effect=fetch)):
            await _run_inbox_scanning(USER, ctx)

        assert seen == [False, True]


# ---------------------------------------------------------------------------
# _run_writing_style
# ---------------------------------------------------------------------------


class TestRunWritingStyle:
    async def test_profession_reaches_the_learner(self) -> None:
        learn = AsyncMock(return_value=None)
        with patch(f"{MODULE}.learn_writing_style", learn):
            await _run_writing_style(USER, profession="lawyer")

        assert learn.await_args.args[0] == USER
        assert learn.await_args.kwargs["profession"] == "lawyer"


# ---------------------------------------------------------------------------
# _run_triage
# ---------------------------------------------------------------------------


class TestRunTriage:
    async def test_waits_for_the_first_batch_before_triaging(self) -> None:
        ctx = InboxScanContext()
        started = asyncio.Event()

        async def triage_inbox(*args: Any, **kwargs: Any) -> InboxTriage:
            started.set()
            return _triage()

        with patch(f"{MODULE}.triage_inbox", AsyncMock(side_effect=triage_inbox)):
            task = asyncio.create_task(_run_triage(USER, ctx, "dev", ""))
            await asyncio.sleep(0)
            assert not started.is_set(), "triage ran before the first batch was ready"

            ctx.emails.append({"id": "1"})
            ctx.first_batch_ready.set()
            await task

        assert started.is_set()

    async def test_an_empty_inbox_skips_triage(self) -> None:
        ctx = InboxScanContext()
        ctx.first_batch_ready.set()
        triage_inbox = AsyncMock()

        with patch(f"{MODULE}.triage_inbox", triage_inbox):
            assert await _run_triage(USER, ctx, "dev", "") is None

        assert triage_inbox.await_count == 0

    async def test_emails_profession_and_focus_reach_the_triager(self) -> None:
        ctx = InboxScanContext()
        ctx.emails.append({"id": "1"})
        ctx.first_batch_ready.set()
        triage_inbox = AsyncMock(return_value=_triage())

        with patch(f"{MODULE}.triage_inbox", triage_inbox):
            await _run_triage(USER, ctx, "lawyer", "close deals")

        assert triage_inbox.await_args.args[0] == USER
        assert triage_inbox.await_args.args[1] == [{"id": "1"}]
        assert triage_inbox.await_args.kwargs == {"profession": "lawyer", "focus": "close deals"}

    async def test_triage_reads_a_snapshot_not_the_live_buffer(self) -> None:
        # The scan keeps appending; the triager must not see the list mutate.
        ctx = InboxScanContext()
        ctx.emails.append({"id": "1"})
        ctx.first_batch_ready.set()
        captured: list[list[dict]] = []

        async def triage_inbox(user_id: str, emails: list[dict], **kwargs: Any) -> InboxTriage:
            captured.append(emails)
            return _triage()

        with patch(f"{MODULE}.triage_inbox", AsyncMock(side_effect=triage_inbox)):
            await _run_triage(USER, ctx, "dev", "")

        ctx.emails.append({"id": "2"})
        assert captured[0] == [{"id": "1"}]


# ---------------------------------------------------------------------------
# _run_social_profiles
# ---------------------------------------------------------------------------


class TestRunSocialProfiles:
    async def test_extracts_dedupes_and_persists(self, scan_cache: Any) -> None:
        raw = [SocialProfile(platform="x", url="u1"), SocialProfile(platform="x", url="u2")]
        deduped = [SocialProfile(platform="x", url="u1")]

        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(return_value=[{"id": "1"}])),
            patch(f"{MODULE}.extract_social_profiles_from_emails", AsyncMock(return_value=raw)),
            patch(f"{MODULE}.dedup_profiles_by_platform", return_value=deduped),
            patch(f"{MODULE}._persist_social_profiles", AsyncMock()) as persist,
        ):
            result = await _run_social_profiles(USER, "Ann", "a@x.com")

        assert result == deduped
        assert persist.await_args.args == (USER, deduped)

    async def test_full_bodies_are_fetched_including_sent_mail(self, scan_cache: Any) -> None:
        fetch = AsyncMock(return_value=[{"id": "1"}])
        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", fetch),
            patch(f"{MODULE}.extract_social_profiles_from_emails", AsyncMock(return_value=[])),
            patch(f"{MODULE}.dedup_profiles_by_platform", return_value=[]),
        ):
            await _run_social_profiles(USER, "Ann", "a@x.com")

        opts = fetch.await_args.kwargs["options"]
        assert isinstance(opts, OnboardingFetchOptions)
        assert opts.fmt == "full"
        assert opts.include_sent is True

    async def test_a_cached_body_fetch_is_reused(self, scan_cache: Any) -> None:
        scan_cache.get = AsyncMock(return_value=[{"id": "cached"}])
        fetch = AsyncMock()
        extract = AsyncMock(return_value=[])

        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", fetch),
            patch(f"{MODULE}.extract_social_profiles_from_emails", extract),
            patch(f"{MODULE}.dedup_profiles_by_platform", return_value=[]),
        ):
            await _run_social_profiles(USER, "Ann", "a@x.com")

        assert fetch.await_count == 0
        assert extract.await_args.args[0] == [{"id": "cached"}]

    # BUG: an empty fetch was written to the cache. A cached [] is not None, so
    # every later run skipped both the fetch and the extraction, leaving the user
    # with no social profiles permanently — including the onboarding retry path.
    async def test_an_empty_fetch_is_not_cached(self, scan_cache: Any) -> None:
        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(return_value=[])),
            patch(f"{MODULE}.extract_social_profiles_from_emails", AsyncMock(return_value=[])),
            patch(f"{MODULE}.dedup_profiles_by_platform", return_value=[]),
        ):
            await _run_social_profiles(USER, "Ann", "a@x.com")

        assert scan_cache.put.await_count == 0

    async def test_a_non_empty_fetch_is_cached(self, scan_cache: Any) -> None:
        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(return_value=[{"id": "1"}])),
            patch(f"{MODULE}.extract_social_profiles_from_emails", AsyncMock(return_value=[])),
            patch(f"{MODULE}.dedup_profiles_by_platform", return_value=[]),
        ):
            await _run_social_profiles(USER, "Ann", "a@x.com")

        assert scan_cache.put.await_args.args[:2] == (USER, "full")

    async def test_no_emails_means_no_extraction(self, scan_cache: Any) -> None:
        extract = AsyncMock()
        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(return_value=[])),
            patch(f"{MODULE}.extract_social_profiles_from_emails", extract),
        ):
            assert await _run_social_profiles(USER, "Ann", "a@x.com") == []

        assert extract.await_count == 0


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


class TestPersistSocialProfiles:
    async def test_writes_profiles_as_models(self) -> None:
        # The repository takes SocialProfile models and does the model_dump itself.
        profiles = [SocialProfile(platform="x", url="u1")]
        with patch(f"{MODULE}.user_repository") as repo:
            repo.set_social_profiles_if_unset = AsyncMock()
            await _persist_social_profiles(USER, profiles)

        assert repo.set_social_profiles_if_unset.await_args.args == (
            USER,
            [SocialProfile(platform="x", url="u1")],
        )

    async def test_an_empty_list_is_not_written(self) -> None:
        # Writing [] would mark the field as set and block a later real extraction.
        with patch(f"{MODULE}.user_repository") as repo:
            repo.set_social_profiles_if_unset = AsyncMock()
            await _persist_social_profiles(USER, [])

        assert repo.set_social_profiles_if_unset.await_count == 0

    async def test_a_write_failure_is_swallowed(self) -> None:
        with patch(f"{MODULE}.user_repository") as repo:
            repo.set_social_profiles_if_unset = AsyncMock(side_effect=RuntimeError("mongo"))
            await _persist_social_profiles(USER, [SocialProfile(platform="x", url="u")])


class TestPersistProfiles:
    async def test_writes_style_and_triage_summary(self) -> None:
        with patch(f"{MODULE}.user_repository") as repo:
            repo.set_writing_style_and_triage = AsyncMock()
            await _persist_profiles(USER, _style(), _triage())

        kwargs = repo.set_writing_style_and_triage.await_args.kwargs
        assert kwargs["writing_style_summary"] == "Terse"
        assert kwargs["triage_summary"].total_scanned == 100
        assert [e.model_dump() for e in kwargs["triage_summary"].important_emails] == [
            {"sender": "a@x.com", "subject": "Contract", "why_important": "deadline"}
        ]

    async def test_triage_important_emails_are_capped_at_five(self) -> None:
        triage = _triage(
            important_emails=[
                EmailSummary(sender=f"s{i}@x.com", subject="s", why_important="w") for i in range(9)
            ]
        )
        with patch(f"{MODULE}.user_repository") as repo:
            repo.set_writing_style_and_triage = AsyncMock()
            await _persist_profiles(USER, None, triage)

        kwargs = repo.set_writing_style_and_triage.await_args.kwargs
        assert len(kwargs["triage_summary"].important_emails) == 5

    async def test_nothing_is_written_when_both_are_absent(self) -> None:
        with patch(f"{MODULE}.user_repository") as repo:
            repo.set_writing_style_and_triage = AsyncMock()
            await _persist_profiles(USER, None, None)

        assert repo.set_writing_style_and_triage.await_count == 0

    async def test_style_alone_is_written_with_a_null_triage(self) -> None:
        with patch(f"{MODULE}.user_repository") as repo:
            repo.set_writing_style_and_triage = AsyncMock()
            await _persist_profiles(USER, _style(), None)

        kwargs = repo.set_writing_style_and_triage.await_args.kwargs
        assert kwargs["writing_style_summary"] == "Terse"
        assert kwargs["triage_summary"] is None

    async def test_a_write_failure_is_swallowed(self) -> None:
        with patch(f"{MODULE}.user_repository") as repo:
            repo.set_writing_style_and_triage = AsyncMock(side_effect=RuntimeError("mongo"))
            await _persist_profiles(USER, _style(), None)


# ---------------------------------------------------------------------------
# _run_holo_card
# ---------------------------------------------------------------------------


@pytest.fixture
def holo_stack() -> Any:
    with (
        patch(
            f"{MODULE}.get_user_metadata",
            AsyncMock(return_value=UserProfileMetadata(account_number=1, member_since="2026")),
        ),
        patch(
            f"{MODULE}.generate_profile_card_design",
            return_value=ProfileCardDesign(
                house="mistgrove", overlay_color="#fff", overlay_opacity=20
            ),
        ),
        patch(
            f"{MODULE}.generate_holo_card_content",
            AsyncMock(return_value=("a phrase", "a bio", BioStatus.COMPLETED)),
        ) as content,
        patch(f"{MODULE}.user_repository.save_personalization", AsyncMock()) as save,
    ):
        yield content, save


class TestRunHoloCard:
    async def test_saves_the_generated_card(self, holo_stack: Any) -> None:
        _, save = holo_stack
        user = UserDocument(id=USER)
        with patch(
            f"{MODULE}.get_user_metadata",
            AsyncMock(return_value=UserProfileMetadata(account_number=1, member_since="2026")),
        ) as metadata:
            assert await _run_holo_card(_ctx(focus="focus"), user, []) is True

        args = save.await_args.args
        assert args[0] == USER
        assert args[1].house == "mistgrove"
        assert args[1].personality_phrase == "a phrase"
        # Both the id and the already-loaded document: without the document the
        # lookup re-reads Mongo, without the id it reads the wrong person.
        metadata.assert_awaited_once_with(USER, user=user)

    async def test_done_line_reports_each_phase_duration(self, holo_stack: Any) -> None:
        """Each duration is the rounded difference of its own bracket, the only trace of where time goes."""
        clock = [0.0, 10.0, 10.5, 20.0, 21.2345, 30.0, 30.75, 31.0]
        with (
            patch(f"{MODULE}.time.monotonic", side_effect=clock),
            patch(f"{MODULE}.log") as log,
        ):
            assert await _run_holo_card(_ctx(), UserDocument(id=USER), []) is True

        done = [c for c in log.info.call_args_list if "holo_card done" in c.args[0]]
        assert len(done) == 1
        kwargs = done[0].kwargs
        assert kwargs["meta_duration_s"] == 0.5
        assert kwargs["phrase_bio_duration_s"] == 1.23
        assert kwargs["save_duration_s"] == 0.75
        assert kwargs["duration_s"] == 31.0

    async def test_context_summary_gathers_every_available_signal(self, holo_stack: Any) -> None:
        content, _ = holo_stack
        await _run_holo_card(
            OnboardingContext(
                user_id=USER,
                name="Ann",
                focus="ship v2",
                triage=_triage(
                    important_emails=[
                        EmailSummary(sender="ann@x.com", subject="Contract", why_important="d"),
                        EmailSummary(sender="bob@x.com", subject="Invoice", why_important="d"),
                    ],
                    patterns=["newsletters", "receipts"],
                ),
                writing_style=WritingStyleProfile(
                    summary="Terse", example=WritingStyleExampleBlocks(body=["x"])
                ),
                clarify_answers=[{"kind": "goal", "value": "grow the team"}],
            ),
            UserDocument(id=USER),
            [SocialProfile(platform="x", url="u1")],
        )

        summary = content.await_args.args[1]
        assert "Busy inbox" in summary
        # Exact separators, from multi-element lists: with one element a wrong
        # join string never appears in the output at all.
        assert "Inbox patterns: newsletters; receipts" in summary
        assert "Key contacts: ann@x.com, bob@x.com" in summary
        assert "Terse" in summary
        assert "x: u1" in summary
        assert "ship v2" in summary
        assert "Goal: grow the team" in summary

    async def test_only_the_top_five_contacts_reach_the_card(self, holo_stack: Any) -> None:
        """Slipping the cap by one is invisible in every fixture with fewer than six important emails."""
        content, _ = holo_stack
        emails = [
            EmailSummary(sender=f"s{i}@x.com", subject="s", why_important="w") for i in range(6)
        ]
        await _run_holo_card(
            _ctx(focus="", triage=_triage(important_emails=emails)), UserDocument(id=USER), []
        )

        summary = content.await_args.args[1]
        assert "Key contacts: s0@x.com, s1@x.com, s2@x.com, s3@x.com, s4@x.com" in summary
        assert "s5@x.com" not in summary

    async def test_blank_clarify_answers_are_skipped(self, holo_stack: Any) -> None:
        content, _ = holo_stack
        await _run_holo_card(
            _ctx(focus="", clarify_answers=[{"kind": "goal", "value": "   "}]),
            UserDocument(id=USER),
            [],
        )

        assert "Goal" not in content.await_args.args[1]

    async def test_a_clarify_answer_without_a_kind_defaults_to_context(
        self, holo_stack: Any
    ) -> None:
        content, _ = holo_stack
        await _run_holo_card(
            _ctx(focus="", clarify_answers=[{"value": "some note"}]), UserDocument(id=USER), []
        )

        assert "Context: some note" in content.await_args.args[1]

    async def test_absent_signals_produce_an_empty_summary(self, holo_stack: Any) -> None:
        content, _ = holo_stack
        await _run_holo_card(_ctx(focus=""), UserDocument(id=USER), [])

        assert content.await_args.args[1] == ""

    async def test_a_failed_card_reports_itself_as_not_viewable(self, holo_stack: Any) -> None:
        # The caller links the public card page off this; a card that never got
        # persisted 404s there.
        with patch(f"{MODULE}.get_user_metadata", AsyncMock(side_effect=RuntimeError("mongo"))):
            assert await _run_holo_card(_ctx(focus=""), UserDocument(id=USER), []) is False

    async def test_a_failed_save_reports_itself_as_not_viewable(self, holo_stack: Any) -> None:
        # The card only becomes viewable once its content lands in Mongo.
        with patch(
            f"{MODULE}.user_repository.save_personalization",
            AsyncMock(side_effect=RuntimeError("mongo")),
        ):
            assert await _run_holo_card(_ctx(focus=""), UserDocument(id=USER), []) is False
