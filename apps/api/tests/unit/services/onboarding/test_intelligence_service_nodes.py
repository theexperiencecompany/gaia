"""Unit tests for the individual DAG nodes in intelligence_service.

Each `_run_*` node is a fail-soft wrapper: it must emit its stage and return a
usable default even when its dependency raises, because the pipeline gathers all
of them and a leaked exception would abort onboarding. These tests pin that
contract down, node by node, faking only the service/repository boundaries.

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
    CompletePayload,
    EmailSummary,
    InboxTriage,
    OnboardingTodoSummary,
    OnboardingTriggerPayload,
    OnboardingWorkflowSummary,
    SocialProfile,
    StagePayload,
    StatusTextPayload,
    TriageReadyPayload,
    WritingStyleExampleBlocks,
    WritingStyleProfile,
)
from app.models.workflow_models import TriggerType
from app.services.onboarding.intelligence_service import (
    InboxScanContext,
    OnboardingContext,
    OnboardingStage,
    _emit_stage,
    _fetch_onboarding_todos,
    _persist_profiles,
    _persist_social_profiles,
    _run_inbox_scanning,
    _run_provision_gmail,
    _run_social_profiles_background,
    _run_todos,
    _run_triage,
    _run_workflows,
    _run_writing_style,
    _safe_run,
    _seed_conversation,
)

MODULE = "app.services.onboarding.intelligence_service"
USER = "user-42"


def _ctx(**overrides: Any) -> OnboardingContext:
    defaults: dict[str, Any] = {
        "user_id": USER,
        "name": "Ann",
        "profession": "dev",
        "focus": "ship v2",
        "has_gmail": True,
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


def _workflow(workflow_id: str, title: str = "Daily") -> OnboardingWorkflowSummary:
    return OnboardingWorkflowSummary(
        id=workflow_id,
        title=title,
        description="d",
        categories=[],
        trigger=OnboardingTriggerPayload(type=TriggerType.SCHEDULE, cron_expression="0 9 * * *"),
    )


class StageSink:
    """Records every stage emission so tests can assert the pipeline's UI contract.

    Payloads are recorded as their wire dicts, not the models, so assertions here
    pin the JSON the frontend actually receives.
    """

    def __init__(self) -> None:
        self.emissions: list[tuple[OnboardingStage, dict]] = []

    async def __call__(
        self, user_id: str, stage: OnboardingStage, payload: StagePayload | None = None
    ) -> None:
        self.emissions.append((stage, payload.to_wire() if payload else {}))

    def stages(self) -> list[OnboardingStage]:
        return [stage for stage, _ in self.emissions]

    def payload_for(self, stage: OnboardingStage) -> dict:
        for emitted, payload in self.emissions:
            if emitted is stage:
                return payload
        raise AssertionError(f"{stage} was never emitted; got {self.stages()}")

    def all_payloads_for(self, stage: OnboardingStage) -> list[dict]:
        return [payload for emitted, payload in self.emissions if emitted is stage]


@pytest.fixture
def stages() -> Any:
    sink = StageSink()
    with patch(f"{MODULE}._emit_stage", sink):
        yield sink


@pytest.fixture(autouse=True)
def quiet_logs() -> Any:
    with patch(f"{MODULE}.log", MagicMock()):
        yield


# ---------------------------------------------------------------------------
# _emit_stage
# ---------------------------------------------------------------------------


class TestEmitStage:
    async def test_broadcasts_the_stage_envelope(self) -> None:
        manager = MagicMock()
        manager.broadcast_to_user = AsyncMock()
        with patch(f"{MODULE}.websocket_manager", manager):
            await _emit_stage(
                USER,
                OnboardingStage.TRIAGE_READY,
                TriageReadyPayload(
                    total_scanned=4,
                    total_unread=0,
                    summary=None,
                    patterns=[],
                    important_emails=[],
                ),
            )

        kwargs = manager.broadcast_to_user.await_args.kwargs
        assert kwargs["user_id"] == USER
        assert kwargs["message"] == {
            "type": "onboarding_stage",
            "data": {
                "stage": "triage_ready",
                "payload": {
                    "total_scanned": 4,
                    "total_unread": 0,
                    "summary": None,
                    "patterns": [],
                    "important_emails": [],
                },
            },
        }

    async def test_stage_is_sent_as_its_wire_value(self) -> None:
        # The frontend switches on these strings; an enum repr would match nothing.
        manager = MagicMock()
        manager.broadcast_to_user = AsyncMock()
        with patch(f"{MODULE}.websocket_manager", manager):
            await _emit_stage(USER, OnboardingStage.COMPLETE)

        stage = manager.broadcast_to_user.await_args.kwargs["message"]["data"]["stage"]
        assert stage == "complete"

    async def test_missing_payload_becomes_an_empty_dict(self) -> None:
        manager = MagicMock()
        manager.broadcast_to_user = AsyncMock()
        with patch(f"{MODULE}.websocket_manager", manager):
            await _emit_stage(USER, OnboardingStage.HOLO_READY, None)

        assert manager.broadcast_to_user.await_args.kwargs["message"]["data"]["payload"] == {}

    async def test_a_dead_socket_does_not_abort_the_pipeline(self) -> None:
        # Users close the tab mid-onboarding; the DAG must keep running.
        manager = MagicMock()
        manager.broadcast_to_user = AsyncMock(side_effect=ConnectionError("socket gone"))
        with patch(f"{MODULE}.websocket_manager", manager):
            await _emit_stage(USER, OnboardingStage.COMPLETE)

    async def test_status_text_is_logged_with_the_stage(self) -> None:
        # These lines are how a stalled onboarding is diagnosed from the logs, so
        # the status the user saw has to appear next to the stage.
        manager = MagicMock()
        manager.broadcast_to_user = AsyncMock()
        with patch(f"{MODULE}.websocket_manager", manager), patch(f"{MODULE}.log") as log:
            await _emit_stage(
                USER,
                OnboardingStage.INBOX_SCANNING,
                StatusTextPayload(status_text="Connecting to Gmail"),
            )

        line = log.info.call_args.args[0]
        kwargs = log.info.call_args.kwargs
        assert "stage" in line
        assert kwargs.get("stage_value") == OnboardingStage.INBOX_SCANNING.value
        assert kwargs.get("status_text") == "Connecting to Gmail"

    async def test_a_payload_without_status_text_logs_only_the_stage(self) -> None:
        manager = MagicMock()
        manager.broadcast_to_user = AsyncMock()
        with patch(f"{MODULE}.websocket_manager", manager), patch(f"{MODULE}.log") as log:
            await _emit_stage(USER, OnboardingStage.COMPLETE, CompletePayload(conversation_id="c1"))

        line = log.info.call_args.args[0]
        kwargs = log.info.call_args.kwargs
        assert "stage" in line
        assert kwargs.get("stage_value") == OnboardingStage.COMPLETE.value
        assert kwargs.get("status_text") is None


# ---------------------------------------------------------------------------
# _safe_run
# ---------------------------------------------------------------------------


class TestSafeRun:
    async def test_passes_the_result_through(self) -> None:
        async def ok() -> str:
            return "value"

        assert await _safe_run("node", ok(), default="fallback") == "value"

    async def test_returns_the_default_when_the_node_raises(self) -> None:
        async def boom() -> str:
            raise RuntimeError("node failed")

        assert await _safe_run("node", boom(), default="fallback") == "fallback"

    async def test_a_falsy_result_is_not_replaced_by_the_default(self) -> None:
        # Returning the default for an empty-but-valid result would mask real data.
        async def empty() -> list[str]:
            return []

        assert await _safe_run("node", empty(), default=["fallback"]) == []

    async def test_cancellation_is_not_swallowed(self) -> None:
        # CancelledError must propagate so shutdown actually cancels the DAG.
        async def cancelled() -> str:
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await _safe_run("node", cancelled(), default="fallback")


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
    async def test_a_cache_hit_short_circuits_the_fetch(self, stages: Any, scan_cache: Any) -> None:
        scan_cache.get = AsyncMock(return_value=[{"id": "1"}, {"id": "2"}])
        ctx = InboxScanContext()
        fetch = AsyncMock()

        with patch(f"{MODULE}.fetch_emails_for_onboarding", fetch):
            await _run_inbox_scanning(USER, ctx)

        assert fetch.await_count == 0
        assert ctx.emails == [{"id": "1"}, {"id": "2"}]
        assert ctx.first_batch_ready.is_set()
        assert ctx.done.is_set()

    async def test_a_cache_hit_is_not_written_back(self, stages: Any, scan_cache: Any) -> None:
        scan_cache.get = AsyncMock(return_value=[{"id": "1"}])
        with patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock()):
            await _run_inbox_scanning(USER, InboxScanContext())

        assert scan_cache.put.await_count == 0

    async def test_fetched_emails_are_cached(self, stages: Any, scan_cache: Any) -> None:
        async def fetch(user_id: str, **kwargs: Any) -> None:
            kwargs["into"].append({"id": "1"})

        with patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(side_effect=fetch)):
            await _run_inbox_scanning(USER, InboxScanContext())

        assert scan_cache.put.await_args.args[:2] == (USER, "metadata")
        assert scan_cache.put.await_args.args[2] == [{"id": "1"}]

    async def test_fetch_is_scoped_to_the_onboarding_window(
        self, stages: Any, scan_cache: Any
    ) -> None:
        fetch = AsyncMock()
        ctx = InboxScanContext()
        with patch(f"{MODULE}.fetch_emails_for_onboarding", fetch):
            await _run_inbox_scanning(USER, ctx)

        kwargs = fetch.await_args.kwargs
        assert kwargs["months"] == 1
        assert kwargs["max_total"] == ONBOARDING_EMAIL_SCAN_LIMIT
        assert kwargs["into"] is ctx.emails

    async def test_events_are_set_even_when_the_fetch_raises(
        self, stages: Any, scan_cache: Any
    ) -> None:
        # Triage waits on first_batch_ready; leaving it unset would hang the DAG.
        ctx = InboxScanContext()
        with patch(
            f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(side_effect=RuntimeError("gmail"))
        ):
            await _run_inbox_scanning(USER, ctx)

        assert ctx.first_batch_ready.is_set()
        assert ctx.done.is_set()

    async def test_a_failed_fetch_is_not_cached(self, stages: Any, scan_cache: Any) -> None:
        # Caching a partial scan would make the retry reuse the truncated result.
        with patch(
            f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(side_effect=RuntimeError("gmail"))
        ):
            await _run_inbox_scanning(USER, InboxScanContext())

        assert scan_cache.put.await_count == 0

    # BUG: the closing "inbox_scanning done" line hardcoded outcome="ok", so a
    # failed Gmail fetch looked successful in the wide-event stream.
    async def test_failure_is_reported_as_failed_not_ok(self, stages: Any, scan_cache: Any) -> None:
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

    async def test_success_is_reported_as_ok(self, stages: Any, scan_cache: Any) -> None:
        with (
            patch(f"{MODULE}.log") as log,
            patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock()),
        ):
            await _run_inbox_scanning(USER, InboxScanContext())

        done = [c for c in log.info.call_args_list if "inbox_scanning done" in str(c)]
        assert done[-1].kwargs["outcome"] == "ok"

    async def test_batch_callback_releases_triage_at_the_threshold(
        self, stages: Any, scan_cache: Any
    ) -> None:
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

    async def test_batch_status_names_the_latest_sender(self, stages: Any, scan_cache: Any) -> None:
        async def fetch(user_id: str, **kwargs: Any) -> None:
            await kwargs["on_batch"](5, "ann@x.com")

        with patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(side_effect=fetch)):
            await _run_inbox_scanning(USER, InboxScanContext())

        texts = [
            p.get("status_text") for p in stages.all_payloads_for(OnboardingStage.INBOX_SCANNING)
        ]
        assert "Fetched 5 emails — ann@x.com" in texts

    async def test_batch_status_omits_an_unknown_sender(self, stages: Any, scan_cache: Any) -> None:
        async def fetch(user_id: str, **kwargs: Any) -> None:
            await kwargs["on_batch"](5, None)

        with patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(side_effect=fetch)):
            await _run_inbox_scanning(USER, InboxScanContext())

        texts = [
            p.get("status_text") for p in stages.all_payloads_for(OnboardingStage.INBOX_SCANNING)
        ]
        assert "Fetched 5 emails" in texts


# ---------------------------------------------------------------------------
# _run_provision_gmail
# ---------------------------------------------------------------------------


class TestRunProvisionGmail:
    async def test_provisions_the_gmail_system_workflows(self) -> None:
        provision = AsyncMock()
        with patch(f"{MODULE}.provision_system_workflows", provision):
            await _run_provision_gmail(USER)

        assert provision.await_args.args == (USER, "gmail", "Gmail")
        # notify=False: these are background system workflows, not user-visible news.
        assert provision.await_args.kwargs["notify"] is False

    async def test_failure_is_swallowed(self) -> None:
        # This runs detached from the critical path; it must never surface.
        with patch(
            f"{MODULE}.provision_system_workflows", AsyncMock(side_effect=RuntimeError("boom"))
        ):
            await _run_provision_gmail(USER)


# ---------------------------------------------------------------------------
# _run_writing_style
# ---------------------------------------------------------------------------


class TestRunWritingStyle:
    async def test_without_gmail_the_node_is_skipped_entirely(self, stages: Any) -> None:
        learn = AsyncMock()
        with patch(f"{MODULE}.learn_writing_style", learn):
            assert await _run_writing_style(USER, has_gmail=False, profession="dev") is None

        assert learn.await_count == 0
        # No READY stage either — the card must not appear for a no-Gmail user.
        assert stages.stages() == []

    async def test_learned_style_is_returned_and_announced(self, stages: Any) -> None:
        style = _style()
        with patch(f"{MODULE}.learn_writing_style", AsyncMock(return_value=style)):
            assert await _run_writing_style(USER, has_gmail=True, profession="dev") is style

        payload = stages.payload_for(OnboardingStage.WRITING_STYLE_READY)
        assert payload["style_summary"] == "Terse"
        assert payload["example"] == style.example.model_dump()

    async def test_profession_reaches_the_learner(self, stages: Any) -> None:
        learn = AsyncMock(return_value=None)
        with patch(f"{MODULE}.learn_writing_style", learn):
            await _run_writing_style(USER, has_gmail=True, profession="lawyer")

        assert learn.await_args.args[0] == USER
        assert learn.await_args.kwargs["profession"] == "lawyer"

    async def test_progress_callback_emits_a_progress_stage(self, stages: Any) -> None:
        async def learn(user_id: str, **kwargs: Any) -> None:
            await kwargs["on_status"]("Reading sent mail")

        with patch(f"{MODULE}.learn_writing_style", AsyncMock(side_effect=learn)):
            await _run_writing_style(USER, has_gmail=True, profession="dev")

        assert stages.payload_for(OnboardingStage.WRITING_STYLE_PROGRESS) == {
            "status_text": "Reading sent mail"
        }

    async def test_a_failure_still_announces_readiness(self, stages: Any) -> None:
        # The frontend blocks its reveal on this stage; skipping it would hang the UI.
        with patch(f"{MODULE}.learn_writing_style", AsyncMock(side_effect=RuntimeError("llm"))):
            assert await _run_writing_style(USER, has_gmail=True, profession="dev") is None

        assert stages.payload_for(OnboardingStage.WRITING_STYLE_READY) == {
            "style_summary": None,
            "example": None,
        }

    async def test_a_style_without_a_summary_reports_none(self, stages: Any) -> None:
        style = WritingStyleProfile(summary="", example=WritingStyleExampleBlocks(body=["x"]))
        with patch(f"{MODULE}.learn_writing_style", AsyncMock(return_value=style)):
            await _run_writing_style(USER, has_gmail=True, profession="dev")

        assert stages.payload_for(OnboardingStage.WRITING_STYLE_READY)["style_summary"] is None


# ---------------------------------------------------------------------------
# _run_triage
# ---------------------------------------------------------------------------


class TestRunTriage:
    async def test_no_inbox_context_skips_triage(self, stages: Any) -> None:
        triage_inbox = AsyncMock()
        with patch(f"{MODULE}.triage_inbox", triage_inbox):
            assert await _run_triage(USER, None, "dev", "focus") is None

        assert triage_inbox.await_count == 0
        assert stages.stages() == []

    async def test_waits_for_the_first_batch_before_triaging(self, stages: Any) -> None:
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

    async def test_an_empty_inbox_skips_triage(self, stages: Any) -> None:
        ctx = InboxScanContext()
        ctx.first_batch_ready.set()
        triage_inbox = AsyncMock()

        with patch(f"{MODULE}.triage_inbox", triage_inbox):
            assert await _run_triage(USER, ctx, "dev", "") is None

        assert triage_inbox.await_count == 0

    async def test_emails_profession_and_focus_reach_the_triager(self, stages: Any) -> None:
        ctx = InboxScanContext()
        ctx.emails.append({"id": "1"})
        ctx.first_batch_ready.set()
        triage_inbox = AsyncMock(return_value=_triage())

        with patch(f"{MODULE}.triage_inbox", triage_inbox):
            await _run_triage(USER, ctx, "lawyer", "close deals")

        assert triage_inbox.await_args.args[0] == USER
        assert triage_inbox.await_args.args[1] == [{"id": "1"}]
        assert triage_inbox.await_args.kwargs == {"profession": "lawyer", "focus": "close deals"}

    async def test_triage_reads_a_snapshot_not_the_live_buffer(self, stages: Any) -> None:
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

    async def test_ready_payload_carries_the_triage_summary(self, stages: Any) -> None:
        ctx = InboxScanContext()
        ctx.emails.append({"id": "1"})
        ctx.first_batch_ready.set()

        with patch(f"{MODULE}.triage_inbox", AsyncMock(return_value=_triage())):
            await _run_triage(USER, ctx, "dev", "")

        payload = stages.payload_for(OnboardingStage.TRIAGE_READY)
        assert payload["total_scanned"] == 100
        assert payload["total_unread"] == 12
        assert payload["summary"] == "Busy inbox"
        assert payload["patterns"] == ["newsletters"]
        assert payload["important_emails"] == [
            {"sender": "a@x.com", "subject": "Contract", "why_important": "deadline"}
        ]

    async def test_important_emails_are_capped_at_five(self, stages: Any) -> None:
        ctx = InboxScanContext()
        ctx.emails.append({"id": "1"})
        ctx.first_batch_ready.set()
        triage = _triage(
            important_emails=[
                EmailSummary(sender=f"s{i}@x.com", subject="s", why_important="w") for i in range(9)
            ]
        )

        with patch(f"{MODULE}.triage_inbox", AsyncMock(return_value=triage)):
            await _run_triage(USER, ctx, "dev", "")

        assert len(stages.payload_for(OnboardingStage.TRIAGE_READY)["important_emails"]) == 5

    async def test_a_failure_still_announces_readiness_with_scanned_count(
        self, stages: Any
    ) -> None:
        ctx = InboxScanContext()
        ctx.emails.extend([{"id": "1"}, {"id": "2"}])
        ctx.first_batch_ready.set()

        with patch(f"{MODULE}.triage_inbox", AsyncMock(side_effect=RuntimeError("llm"))):
            assert await _run_triage(USER, ctx, "dev", "") is None

        payload = stages.payload_for(OnboardingStage.TRIAGE_READY)
        assert payload["total_scanned"] == 2
        assert payload["summary"] is None
        assert payload["important_emails"] == []

    @pytest.mark.parametrize(
        ("count", "expected"), [(1, "Found 1 important thread"), (3, "Found 3 important threads")]
    )
    async def test_important_thread_count_is_pluralized(
        self, stages: Any, count: int, expected: str
    ) -> None:
        ctx = InboxScanContext()
        ctx.emails.append({"id": "1"})
        ctx.first_batch_ready.set()
        triage = _triage(
            important_emails=[
                EmailSummary(sender=f"s{i}@x.com", subject="s", why_important="w")
                for i in range(count)
            ]
        )

        with patch(f"{MODULE}.triage_inbox", AsyncMock(return_value=triage)):
            await _run_triage(USER, ctx, "dev", "")

        texts = [
            p.get("status_text") for p in stages.all_payloads_for(OnboardingStage.TRIAGE_ANALYZING)
        ]
        assert expected in texts


# ---------------------------------------------------------------------------
# _run_social_profiles_background
# ---------------------------------------------------------------------------


class TestRunSocialProfilesBackground:
    async def test_extracts_dedupes_persists_and_announces(
        self, stages: Any, scan_cache: Any
    ) -> None:
        raw = [SocialProfile(platform="x", url="u1"), SocialProfile(platform="x", url="u2")]
        deduped = [SocialProfile(platform="x", url="u1")]

        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(return_value=[{"id": "1"}])),
            patch(f"{MODULE}.extract_social_profiles_from_emails", AsyncMock(return_value=raw)),
            patch(f"{MODULE}.dedup_profiles_by_platform", return_value=deduped),
            patch(f"{MODULE}._persist_social_profiles", AsyncMock()) as persist,
        ):
            result = await _run_social_profiles_background(USER, "Ann", "a@x.com")

        assert result == deduped
        assert persist.await_args.args == (USER, deduped)
        assert stages.payload_for(OnboardingStage.SOCIAL_PROFILES_READY) == {
            "profiles": [{"platform": "x", "url": "u1"}]
        }

    async def test_full_bodies_are_fetched_including_sent_mail(
        self, stages: Any, scan_cache: Any
    ) -> None:
        fetch = AsyncMock(return_value=[{"id": "1"}])
        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", fetch),
            patch(f"{MODULE}.extract_social_profiles_from_emails", AsyncMock(return_value=[])),
            patch(f"{MODULE}.dedup_profiles_by_platform", return_value=[]),
        ):
            await _run_social_profiles_background(USER, "Ann", "a@x.com")

        opts = fetch.await_args.kwargs["options"]
        assert isinstance(opts, OnboardingFetchOptions)
        assert opts.fmt == "full"
        assert opts.include_sent is True

    async def test_a_cached_body_fetch_is_reused(self, stages: Any, scan_cache: Any) -> None:
        scan_cache.get = AsyncMock(return_value=[{"id": "cached"}])
        fetch = AsyncMock()
        extract = AsyncMock(return_value=[])

        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", fetch),
            patch(f"{MODULE}.extract_social_profiles_from_emails", extract),
            patch(f"{MODULE}.dedup_profiles_by_platform", return_value=[]),
        ):
            await _run_social_profiles_background(USER, "Ann", "a@x.com")

        assert fetch.await_count == 0
        assert extract.await_args.args[0] == [{"id": "cached"}]

    # BUG: an empty fetch was written to the cache. A cached [] is not None, so
    # every later run skipped both the fetch and the extraction, leaving the user
    # with no social profiles permanently — including the onboarding retry path.
    async def test_an_empty_fetch_is_not_cached(self, stages: Any, scan_cache: Any) -> None:
        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(return_value=[])),
            patch(f"{MODULE}.extract_social_profiles_from_emails", AsyncMock(return_value=[])),
            patch(f"{MODULE}.dedup_profiles_by_platform", return_value=[]),
        ):
            await _run_social_profiles_background(USER, "Ann", "a@x.com")

        assert scan_cache.put.await_count == 0

    async def test_a_non_empty_fetch_is_cached(self, stages: Any, scan_cache: Any) -> None:
        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(return_value=[{"id": "1"}])),
            patch(f"{MODULE}.extract_social_profiles_from_emails", AsyncMock(return_value=[])),
            patch(f"{MODULE}.dedup_profiles_by_platform", return_value=[]),
        ):
            await _run_social_profiles_background(USER, "Ann", "a@x.com")

        assert scan_cache.put.await_args.args[:2] == (USER, "full")

    async def test_no_emails_means_no_extraction(self, stages: Any, scan_cache: Any) -> None:
        extract = AsyncMock()
        with (
            patch(f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(return_value=[])),
            patch(f"{MODULE}.extract_social_profiles_from_emails", extract),
        ):
            assert await _run_social_profiles_background(USER, "Ann", "a@x.com") == []

        assert extract.await_count == 0

    async def test_a_failure_still_announces_readiness(self, stages: Any, scan_cache: Any) -> None:
        with patch(
            f"{MODULE}.fetch_emails_for_onboarding", AsyncMock(side_effect=RuntimeError("gmail"))
        ):
            assert await _run_social_profiles_background(USER, "Ann", "a@x.com") == []

        assert stages.payload_for(OnboardingStage.SOCIAL_PROFILES_READY) == {"profiles": []}


# ---------------------------------------------------------------------------
# _run_todos
# ---------------------------------------------------------------------------


async def _resolved(value: Any) -> Any:
    return value


class TestRunTodos:
    async def test_gmail_with_important_emails_uses_the_triage_path(self, stages: Any) -> None:
        triage = _triage()
        created = [{"id": "t1", "title": "Reply"}]

        with (
            patch(
                f"{MODULE}._create_todos_from_triage", AsyncMock(return_value=created)
            ) as from_triage,
            patch(f"{MODULE}._create_focus_todos", AsyncMock()) as from_focus,
        ):
            result = await _run_todos(_ctx(), asyncio.ensure_future(_resolved(triage)))

        assert result == created
        assert from_triage.await_args.args == (USER, triage)
        assert from_focus.await_count == 0

    async def test_gmail_without_important_emails_falls_back_to_focus(self, stages: Any) -> None:
        triage = _triage(important_emails=[])
        created = [{"id": "t1", "title": "Plan"}]

        with (
            patch(f"{MODULE}._create_todos_from_triage", AsyncMock()) as from_triage,
            patch(f"{MODULE}._create_focus_todos", AsyncMock(return_value=created)) as from_focus,
        ):
            result = await _run_todos(_ctx(), asyncio.ensure_future(_resolved(triage)))

        assert result == created
        assert from_triage.await_count == 0
        # Same call as the no-Gmail branch below and just as easy to under-fill:
        # a dropped name/profession/focus makes the LLM draft generic todos.
        assert from_focus.await_args.args == (USER, "Ann", "dev", "ship v2", [])

    async def test_gmail_with_no_triage_and_no_focus_creates_nothing(self, stages: Any) -> None:
        with (
            patch(f"{MODULE}._create_todos_from_triage", AsyncMock()) as from_triage,
            patch(f"{MODULE}._create_focus_todos", AsyncMock()) as from_focus,
        ):
            result = await _run_todos(_ctx(focus=""), asyncio.ensure_future(_resolved(None)))

        assert result == []
        assert from_triage.await_count == from_focus.await_count == 0

    async def test_without_gmail_focus_drives_the_todos(self, stages: Any) -> None:
        created = [{"id": "t1", "title": "Plan"}]
        with patch(f"{MODULE}._create_focus_todos", AsyncMock(return_value=created)) as from_focus:
            result = await _run_todos(_ctx(has_gmail=False), asyncio.ensure_future(_resolved(None)))

        assert result == created
        assert from_focus.await_args.args == (USER, "Ann", "dev", "ship v2", [])

    async def test_without_gmail_and_without_focus_creates_nothing(self, stages: Any) -> None:
        with patch(f"{MODULE}._create_focus_todos", AsyncMock()) as from_focus:
            result = await _run_todos(
                _ctx(has_gmail=False, focus=""), asyncio.ensure_future(_resolved(None))
            )

        assert result == []
        assert from_focus.await_count == 0

    async def test_a_creation_failure_degrades_to_an_empty_list(self, stages: Any) -> None:
        with patch(f"{MODULE}._create_focus_todos", AsyncMock(side_effect=RuntimeError("llm"))):
            result = await _run_todos(_ctx(has_gmail=False), asyncio.ensure_future(_resolved(None)))

        assert result == []
        assert stages.payload_for(OnboardingStage.TODOS_READY)["todos"] == []

    @pytest.mark.parametrize(
        ("count", "expected"),
        [(0, "No todos to save"), (1, "Saved 1 todo"), (2, "Saved 2 todos")],
    )
    async def test_ready_status_is_pluralized(self, stages: Any, count: int, expected: str) -> None:
        created = [OnboardingTodoSummary(id=f"t{i}", title="x") for i in range(count)]
        with patch(f"{MODULE}._create_focus_todos", AsyncMock(return_value=created)):
            await _run_todos(_ctx(has_gmail=False), asyncio.ensure_future(_resolved(None)))

        assert stages.payload_for(OnboardingStage.TODOS_READY)["status_text"] == expected


# ---------------------------------------------------------------------------
# _run_workflows
# ---------------------------------------------------------------------------


class TestRunWorkflows:
    async def test_created_workflows_are_returned_and_announced(self, stages: Any) -> None:
        created = [_workflow("w1", title="Daily")]
        with (
            patch(f"{MODULE}._create_onboarding_workflows", AsyncMock(return_value=created)),
            patch(f"{MODULE}.user_repository") as repo,
        ):
            repo.set_suggested_workflows = AsyncMock()
            result = await _run_workflows(_ctx())

        assert result == created
        assert stages.payload_for(OnboardingStage.WORKFLOWS_READY)["workflows"] == [
            w.model_dump(mode="json", exclude_none=True) for w in created
        ]

    async def test_workflow_ids_are_persisted_as_suggestions(self, stages: Any) -> None:
        created = [_workflow("w1"), _workflow("w2")]
        with (
            patch(f"{MODULE}._create_onboarding_workflows", AsyncMock(return_value=created)),
            patch(f"{MODULE}.user_repository") as repo,
        ):
            repo.set_suggested_workflows = AsyncMock()
            await _run_workflows(_ctx())

        assert repo.set_suggested_workflows.await_args.args == (USER, ["w1", "w2"])

    async def test_workflows_without_an_id_are_not_persisted(self, stages: Any) -> None:
        with (
            patch(
                f"{MODULE}._create_onboarding_workflows",
                AsyncMock(return_value=[_workflow("")]),
            ),
            patch(f"{MODULE}.user_repository") as repo,
        ):
            repo.set_suggested_workflows = AsyncMock()
            await _run_workflows(_ctx())

        assert repo.set_suggested_workflows.await_count == 0

    async def test_a_persistence_failure_does_not_lose_the_workflows(self, stages: Any) -> None:
        # The workflows exist in Mongo either way; only the suggestion list is lost.
        created = [_workflow("w1")]
        with (
            patch(f"{MODULE}._create_onboarding_workflows", AsyncMock(return_value=created)),
            patch(f"{MODULE}.user_repository") as repo,
        ):
            repo.set_suggested_workflows = AsyncMock(side_effect=RuntimeError("mongo"))
            assert await _run_workflows(_ctx()) == created

    async def test_a_creation_failure_degrades_to_an_empty_list(self, stages: Any) -> None:
        with patch(
            f"{MODULE}._create_onboarding_workflows", AsyncMock(side_effect=RuntimeError("llm"))
        ):
            assert await _run_workflows(_ctx()) == []

        assert stages.payload_for(OnboardingStage.WORKFLOWS_READY)["workflows"] == []

    async def test_context_is_forwarded_to_the_creator(self, stages: Any) -> None:
        triage, style = _triage(), _style()
        with (
            patch(f"{MODULE}._create_onboarding_workflows", AsyncMock(return_value=[])) as create,
            patch(f"{MODULE}.user_repository"),
        ):
            ctx = OnboardingContext(
                user_id=USER,
                name="Ann",
                profession="dev",
                focus="ship v2",
                has_gmail=True,
                user_timezone="Europe/London",
                triage=triage,
                writing_style=style,
                clarify_answers=[{"kind": "scope", "value": "a"}],
            )
            await _run_workflows(ctx, ["slack"])

        assert create.await_args.args == (ctx, ["slack"])

    @pytest.mark.parametrize(
        ("count", "expected"),
        [(0, "No workflows to save"), (1, "Saved 1 workflow"), (2, "Saved 2 workflows")],
    )
    async def test_ready_status_is_pluralized(self, stages: Any, count: int, expected: str) -> None:
        created = [_workflow(f"w{i}") for i in range(count)]
        with (
            patch(f"{MODULE}._create_onboarding_workflows", AsyncMock(return_value=created)),
            patch(f"{MODULE}.user_repository"),
        ):
            await _run_workflows(_ctx())

        assert stages.payload_for(OnboardingStage.WORKFLOWS_READY)["status_text"] == expected


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


class TestSeedConversation:
    async def test_returns_the_seeded_conversation_id(self) -> None:
        with patch(f"{MODULE}.seed_onboarding_conversation", AsyncMock(return_value="c1")):
            assert await _seed_conversation(USER) == "c1"

    async def test_a_failure_returns_none_rather_than_raising(self) -> None:
        # The caller still needs to persist completion and emit COMPLETE.
        with patch(
            f"{MODULE}.seed_onboarding_conversation", AsyncMock(side_effect=RuntimeError("mongo"))
        ):
            assert await _seed_conversation(USER) is None


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


class TestFetchOnboardingTodos:
    async def test_maps_todos_to_id_and_title(self) -> None:
        todo = MagicMock()
        todo.id, todo.title = "t1", "Reply to Ann"
        with patch(f"{MODULE}.todo_repository") as repo:
            repo.list_onboarding_todos = AsyncMock(return_value=[todo])
            assert await _fetch_onboarding_todos(USER) == [
                OnboardingTodoSummary(id="t1", title="Reply to Ann")
            ]

    async def test_a_missing_title_becomes_an_empty_string(self) -> None:
        todo = MagicMock()
        todo.id, todo.title = "t1", None
        with patch(f"{MODULE}.todo_repository") as repo:
            repo.list_onboarding_todos = AsyncMock(return_value=[todo])
            assert await _fetch_onboarding_todos(USER) == [OnboardingTodoSummary(id="t1", title="")]
