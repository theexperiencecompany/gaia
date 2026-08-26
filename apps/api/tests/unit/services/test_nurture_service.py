"""Unit tests for the nurture sequence service (app/services/nurture/service.py).

The service decides who gets a nurture email, when, and how often — the
frequency caps and step-selection logic are pure and fully pinned here; the
send path is verified with the email/analytics boundaries mocked.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.constants.nurture import (
    NURTURE_BACKFILL_GRACE_DAYS,
    NURTURE_MIN_DAYS_BETWEEN_EMAILS,
    NurtureStep,
)
from app.models.user_models import UserDocument
from app.services.nurture.service import (
    _process_user,
    _select_step,
    _send_step,
    _step_pending,
    _within_frequency_caps,
    run_nurture_sequence,
)

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _step(**overrides) -> NurtureStep:
    fields = dict(
        key="first_win",
        day_offset=1,
        template="nurture_first_win.html",
        subject="Subject",
        enabled=True,
        requires_onboarding=False,
    )
    fields.update(overrides)
    return NurtureStep(**fields)


class TestWithinFrequencyCaps:
    def test_empty_history_allows_send(self) -> None:
        assert _within_frequency_caps([], NOW) is True

    def test_ignores_non_sent_entries(self) -> None:
        history = [{"status": "skipped", "at": NOW.replace(tzinfo=None)}]
        assert _within_frequency_caps(history, NOW) is True

    def test_blocks_after_weekly_cap(self) -> None:
        history = [
            {"status": "sent", "at": (NOW - timedelta(days=d)).replace(tzinfo=None)}
            for d in (1, 2, 3)
        ]
        assert _within_frequency_caps(history, NOW) is False

    def test_allows_under_weekly_cap_but_blocks_recent_send(self) -> None:
        history = [{"status": "sent", "at": (NOW - timedelta(hours=1)).replace(tzinfo=None)}]
        assert _within_frequency_caps(history, NOW) is False

    def test_allows_when_last_send_is_old_enough(self) -> None:
        history = [
            {
                "status": "sent",
                "at": (NOW - timedelta(days=NURTURE_MIN_DAYS_BETWEEN_EMAILS)).replace(tzinfo=None),
            }
        ]
        assert _within_frequency_caps(history, NOW) is True


class TestStepPending:
    def test_disabled_step_is_not_pending(self) -> None:
        assert _step_pending(_step(enabled=False), 1, set(), True) is False

    def test_completed_step_is_not_pending(self) -> None:
        assert _step_pending(_step(), 1, {"first_win"}, True) is False

    def test_outside_window_is_not_pending(self) -> None:
        assert _step_pending(_step(day_offset=1), 0, set(), True) is False
        assert (
            _step_pending(_step(day_offset=1), 1 + NURTURE_BACKFILL_GRACE_DAYS + 1, set(), True)
            is False
        )

    def test_within_window_is_pending(self) -> None:
        assert _step_pending(_step(day_offset=1), 1, set(), True) is True
        assert (
            _step_pending(_step(day_offset=1), 1 + NURTURE_BACKFILL_GRACE_DAYS, set(), True) is True
        )

    def test_onboarding_gate_holds_when_not_onboarded(self) -> None:
        step = _step(requires_onboarding=True)
        assert _step_pending(step, 1, set(), False) is False
        assert _step_pending(step, 1, set(), True) is True

    def test_non_onboarding_step_pending_even_unonboarded(self) -> None:
        assert _step_pending(_step(requires_onboarding=False), 1, set(), False) is True


class TestSelectStep:
    # The real SKIP_PREDICATES hit repository boundaries — keep them quiet
    # so selection runs against a clean slate.
    @patch(
        "app.services.nurture.predicates.conversation_repository.count_non_onboarding",
        new_callable=AsyncMock,
        return_value=0,
    )
    @patch(
        "app.services.nurture.predicates.todo_repository.count_for_user",
        new_callable=AsyncMock,
        return_value=0,
    )
    @patch(
        "app.services.nurture.predicates.workflow_repository.count_for_user",
        new_callable=AsyncMock,
        return_value=0,
    )
    @patch(
        "app.services.nurture.predicates.check_multiple_integrations_status",
        new_callable=AsyncMock,
        return_value={},
    )
    async def test_returns_first_pending_step(self, *mocks) -> None:
        user = UserDocument(id="u-1", email="u@example.com")
        step = await _select_step(user, days_since_signup=1, completed=set(), now=NOW)
        assert step is not None
        assert step.key == "first_win"

    async def test_skipped_predicate_records_and_moves_on(self) -> None:
        user = UserDocument(id="u-1", email="u@example.com")
        with (
            patch(
                "app.services.nurture.service.SKIP_PREDICATES",
                {"used_chat": AsyncMock(return_value=True)},
            ),
            patch(
                "app.services.nurture.service._record_step", new_callable=AsyncMock
            ) as mock_record,
            patch(
                "app.services.nurture.service.NURTURE_STEPS",
                [
                    _step(key="step_a", day_offset=1, skip_predicate="used_chat"),
                    _step(key="step_b", day_offset=2, skip_predicate=None),
                ],
            ),
        ):
            step = await _select_step(user, days_since_signup=2, completed=set(), now=NOW)

        assert step is not None and step.key == "step_b"
        mock_record.assert_awaited_once_with("u-1", "step_a", NOW, status="skipped")

    async def test_returns_none_when_every_step_blocked(self) -> None:
        user = UserDocument(id="u-1", email="u@example.com")
        with (
            patch(
                "app.services.nurture.service.NURTURE_STEPS",
                [_step(key="step_a", day_offset=1, skip_predicate="used_chat")],
            ),
            patch(
                "app.services.nurture.service.SKIP_PREDICATES",
                {"used_chat": AsyncMock(return_value=True)},
            ),
            patch("app.services.nurture.service._record_step", new_callable=AsyncMock),
        ):
            step = await _select_step(user, days_since_signup=1, completed=set(), now=NOW)

        assert step is None


class TestSendStep:
    async def test_sends_email_with_utm_url(self) -> None:
        user = UserDocument(id="u-1", email="u@example.com", name="A")
        step = _step(cta_path="/c", cta_label="Go")
        with (
            patch("app.services.nurture.service.send_email", new_callable=AsyncMock) as mock_send,
            patch(
                "app.services.nurture.service.render_email_template", return_value="<html>"
            ) as mock_render,
            patch("app.services.nurture.service.settings") as mock_settings,
        ):
            mock_settings.FRONTEND_URL = "https://app.example.com"
            await _send_step(user, step)

        message = mock_send.await_args.args[0]
        assert message.to == ["u@example.com"]
        assert message.subject == "Subject"
        render_kwargs = mock_render.call_args.kwargs
        assert "utm_source" in render_kwargs["cta_url"]
        assert "utm_campaign" in render_kwargs["cta_url"]
        assert render_kwargs["cta_url"].startswith("https://app.example.com/c?")
        assert render_kwargs["cta_label"] == "Go"

    async def test_context_builder_overrides_cta_label(self) -> None:
        user = UserDocument(id="u-1", email="u@example.com")
        step = _step(cta_path="/c", cta_label="Default", context_builder="google_connection_status")
        with (
            patch("app.services.nurture.service.send_email", new_callable=AsyncMock) as mock_send,
            patch("app.services.nurture.service.render_email_template", return_value="<html>"),
            patch(
                "app.services.nurture.service.CONTEXT_BUILDERS",
                {
                    "google_connection_status": AsyncMock(
                        return_value={"cta_label": "Connect Gmail"}
                    )
                },
            ),
        ):
            await _send_step(user, step)

        rendered = mock_send.await_args.args[0].html
        assert rendered == "<html>"


class TestProcessUser:
    def _user(self, **overrides) -> UserDocument:
        fields = dict(
            id="u-1",
            email="u@example.com",
            created_at="2026-05-30T12:00:00Z",
            notification_channel_prefs={},
        )
        fields.update(overrides)
        return UserDocument(**fields)

    async def test_returns_false_outside_send_hour(self) -> None:
        with patch("app.services.nurture.service.is_within_local_daytime", return_value=False):
            assert await _process_user(self._user(), NOW) is False

    async def test_returns_false_without_email(self) -> None:
        with patch("app.services.nurture.service.is_within_local_daytime", return_value=True):
            assert await _process_user(self._user(email=None), NOW) is False

    async def test_sends_and_records_on_success(self) -> None:
        user = self._user()
        with (
            patch("app.services.nurture.service.is_within_local_daytime", return_value=True),
            patch(
                "app.services.nurture.service.normalize_channel_preferences",
                return_value={"email": True},
            ),
            patch("app.services.nurture.service._within_frequency_caps", return_value=True),
            patch(
                "app.services.nurture.service._select_step",
                new_callable=AsyncMock,
                return_value=_step(),
            ),
            patch("app.services.nurture.service._send_step", new_callable=AsyncMock) as mock_send,
            patch(
                "app.services.nurture.service._record_step", new_callable=AsyncMock
            ) as mock_record,
            patch("app.services.nurture.service.capture_event") as mock_capture,
        ):
            result = await _process_user(user, NOW)

        assert result is True
        mock_send.assert_awaited_once()
        mock_record.assert_awaited_once()
        mock_capture.assert_called_once()


class TestRunNurtureSequence:
    async def test_skips_when_email_not_configured(self) -> None:
        with (
            patch("app.services.nurture.service.settings") as mock_settings,
            patch(
                "app.services.nurture.service.resolve_resend_config",
                new=AsyncMock(return_value=None),
            ),
            patch("app.services.nurture.service.log"),
        ):
            mock_settings.RESEND_API_KEY = None
            mock_settings.EMAIL_UNSUBSCRIBE_SECRET = "s"
            assert await run_nurture_sequence() == "skipped: email not configured"

    async def test_counts_sent_and_checked(self) -> None:
        users = [self._user(f"u-{i}") for i in range(2)]
        with (
            patch("app.services.nurture.service.settings") as mock_settings,
            patch(
                "app.services.nurture.service.resolve_resend_config",
                new=AsyncMock(
                    return_value={
                        "api_key": "re-stored",
                        "base_url": None,
                        "model": None,
                        "preset": None,
                    }
                ),
            ),
            patch(
                "app.services.nurture.service.user_repository.find_nurture_candidates",
                new_callable=AsyncMock,
                return_value=users,
            ) as mock_find,
            patch(
                "app.services.nurture.service._process_user",
                new_callable=AsyncMock,
                side_effect=[True, False],
            ),
            patch("app.services.nurture.service.log"),
        ):
            mock_settings.EMAIL_UNSUBSCRIBE_SECRET = "s"
            result = await run_nurture_sequence()

        assert result == "nurture: sent 1 of 2 candidates"
        mock_find.assert_awaited_once()

    def _user(self, user_id: str) -> UserDocument:
        return UserDocument(id=user_id, email=f"{user_id}@example.com")
