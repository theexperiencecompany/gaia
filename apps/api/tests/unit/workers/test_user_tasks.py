"""Unit tests for user_tasks ARQ worker."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.models.user_models import UserDocument
from app.workers.tasks.user_tasks import _should_send_inactive_email, check_inactive_users

_FIND = "app.workers.tasks.user_tasks.user_repository.find_inactive_email_candidates"
_RECORD = "app.workers.tasks.user_tasks.user_repository.record_inactive_email"


def _make_db_user(
    email: str = "user@example.com",
    name: str = "Test User",
    user_id: str = "507f1f77bcf86cd799439011",
    last_active_days_ago: int = 10,
) -> UserDocument:
    """Build a minimal user document as returned by the repository."""
    last_active = datetime.now(UTC) - timedelta(days=last_active_days_ago)
    return UserDocument(
        id=user_id,
        email=email,
        name=name,
        last_active_at=last_active.replace(tzinfo=None),
        is_active=True,
    )


@pytest.mark.unit
class TestShouldSendInactiveEmail:
    """Throttle policy: first email after 7 inactive days, second after 14, then stop."""

    def test_less_than_7_days_inactive(self):
        now = datetime.now(UTC)
        user = UserDocument(last_active_at=now - timedelta(days=3), last_inactive_email_sent=None)
        assert _should_send_inactive_email(user) is False

    def test_no_last_active(self):
        assert _should_send_inactive_email(UserDocument(last_inactive_email_sent=None)) is False

    def test_email_sent_recently(self):
        now = datetime.now(UTC)
        user = UserDocument(
            last_active_at=now - timedelta(days=10),
            last_inactive_email_sent=now - timedelta(days=2),
        )
        assert _should_send_inactive_email(user) is False

    def test_eligible_first_email(self):
        now = datetime.now(UTC)
        user = UserDocument(last_active_at=now - timedelta(days=10), last_inactive_email_sent=None)
        assert _should_send_inactive_email(user) is True

    def test_second_email_at_day_14(self):
        """Real-world timing: first email at day 7, second due at day 14."""
        now = datetime.now(UTC)
        user = UserDocument(
            last_active_at=now - timedelta(days=14),
            last_inactive_email_sent=now - timedelta(days=7),
        )
        assert _should_send_inactive_email(user) is True

    def test_overdue_second_email_still_sent(self):
        now = datetime.now(UTC)
        user = UserDocument(
            last_active_at=now - timedelta(days=15),
            last_inactive_email_sent=now - timedelta(days=8),
        )
        assert _should_send_inactive_email(user) is True

    def test_max_2_emails(self):
        now = datetime.now(UTC)
        user = UserDocument(
            last_active_at=now - timedelta(days=21),
            last_inactive_email_sent=now - timedelta(days=7),
            inactive_email_count=2,
        )
        assert _should_send_inactive_email(user) is False

    def test_legacy_doc_without_count_treated_as_one_send(self):
        """Docs from before the counter existed recorded their send via the timestamp only."""
        now = datetime.now(UTC)
        user = UserDocument(
            last_active_at=now - timedelta(days=14),
            last_inactive_email_sent=now - timedelta(days=7),
            inactive_email_count=0,
        )
        assert _should_send_inactive_email(user) is True

    def test_new_inactivity_episode_resets_count(self):
        """An email sent before the user's last activity belongs to a previous episode."""
        now = datetime.now(UTC)
        user = UserDocument(
            last_active_at=now - timedelta(days=10),
            last_inactive_email_sent=now - timedelta(days=90),
            inactive_email_count=2,
        )
        assert _should_send_inactive_email(user) is True

    def test_naive_last_active_handled(self):
        """MongoDB may return naive datetimes; the policy should handle them."""
        now = datetime.now(UTC)
        user = UserDocument(
            last_active_at=(now - timedelta(days=10)).replace(tzinfo=None),
            last_inactive_email_sent=None,
        )
        assert _should_send_inactive_email(user) is True

    def test_naive_last_email_sent_handled(self):
        now = datetime.now(UTC)
        user = UserDocument(
            last_active_at=now - timedelta(days=10),
            last_inactive_email_sent=(now - timedelta(days=2)).replace(tzinfo=None),
        )
        assert _should_send_inactive_email(user) is False


@pytest.mark.unit
class TestCheckInactiveUsers:
    """Tests for check_inactive_users ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_no_inactive_users_sends_no_emails(self, ctx):
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[]),
            patch("app.services.email.send_inactive_user_email") as mock_email,
        ):
            result = await check_inactive_users(ctx)

        mock_email.assert_not_called()
        assert "0 inactive users" in result
        assert "0 emails" in result

    async def test_sends_email_for_each_inactive_user(self, ctx):
        users = [
            _make_db_user("alice@example.com", "Alice", "id_1"),
            _make_db_user("bob@example.com", "Bob", "id_2"),
        ]
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=users),
            patch(_RECORD, new_callable=AsyncMock),
            patch(
                "app.services.email.send_inactive_user_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            result = await check_inactive_users(ctx)

        assert mock_email.await_count == 2
        assert "2 inactive users" in result
        assert "2 emails" in result

    async def test_email_called_with_correct_arguments(self, ctx):
        user = _make_db_user("carol@example.com", "Carol", "id_carol")
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[user]),
            patch(_RECORD, new_callable=AsyncMock),
            patch(
                "app.services.email.send_inactive_user_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            await check_inactive_users(ctx)

        mock_email.assert_awaited_once_with("carol@example.com", "id_carol", "Carol")

    async def test_sent_email_records_tracking(self, ctx):
        user = _make_db_user("carol@example.com", "Carol", "id_carol")
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[user]),
            patch(_RECORD, new_callable=AsyncMock) as mock_record,
            patch("app.services.email.send_inactive_user_email", new_callable=AsyncMock),
        ):
            await check_inactive_users(ctx)

        # First send in a fresh episode → counter set to 1.
        mock_record.assert_awaited_once_with("id_carol", 1)

    async def test_legacy_user_second_send_sets_count_to_two(self, ctx):
        """A pre-counter doc (timestamp only) counts as one send, so the next send stores 2."""
        user = _make_db_user("legacy@example.com", "Legacy", "id_legacy", last_active_days_ago=14)
        user.last_inactive_email_sent = (datetime.now(UTC) - timedelta(days=7)).replace(tzinfo=None)
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[user]),
            patch(_RECORD, new_callable=AsyncMock) as mock_record,
            patch("app.services.email.send_inactive_user_email", new_callable=AsyncMock),
        ):
            await check_inactive_users(ctx)

        mock_record.assert_awaited_once_with("id_legacy", 2)

    async def test_failed_email_does_not_count_in_total(self, ctx):
        users = [
            _make_db_user("ok@example.com", "OK User", "id_ok"),
            _make_db_user("fail@example.com", "Fail User", "id_fail"),
        ]

        async def selective_send(user_email, user_id, user_name=None):
            if user_email != "ok@example.com":
                raise RuntimeError("SMTP error")

        with (
            patch(_FIND, new_callable=AsyncMock, return_value=users),
            patch(_RECORD, new_callable=AsyncMock),
            patch(
                "app.services.email.send_inactive_user_email",
                side_effect=selective_send,
            ),
        ):
            result = await check_inactive_users(ctx)

        # Only 1 email successfully sent; 1 errored (swallowed per-user)
        assert "2 inactive users" in result
        assert "1 emails" in result

    async def test_recently_emailed_user_skipped(self, ctx):
        """A user who got an inactive email 2 days ago is skipped by the throttle."""
        user = _make_db_user("ghost@example.com", "Ghost", "id_ghost")
        user.last_inactive_email_sent = (datetime.now(UTC) - timedelta(days=2)).replace(tzinfo=None)
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[user]),
            patch(
                "app.services.email.send_inactive_user_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            result = await check_inactive_users(ctx)

        mock_email.assert_not_awaited()
        assert "0 emails" in result

    async def test_finder_called_with_seven_day_cutoff(self, ctx):
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=[]) as mock_find,
            patch("app.services.email.send_inactive_user_email"),
        ):
            before_call = datetime.now(UTC)
            await check_inactive_users(ctx)
            after_call = datetime.now(UTC)

        cutoff = mock_find.call_args.args[0]
        expected_lower = (before_call - timedelta(days=7)).replace(tzinfo=None)
        expected_upper = (after_call - timedelta(days=7)).replace(tzinfo=None)
        assert (
            expected_lower - timedelta(seconds=5) <= cutoff <= expected_upper + timedelta(seconds=5)
        )

    async def test_db_exception_propagates(self, ctx):
        with patch(_FIND, new_callable=AsyncMock, side_effect=RuntimeError("MongoDB down")):
            with pytest.raises(RuntimeError, match="MongoDB down"):
                await check_inactive_users(ctx)

    async def test_multiple_users_all_succeed_count_matches(self, ctx):
        count = 5
        users = [
            _make_db_user(f"user{i}@example.com", f"User {i}", f"id_{i}") for i in range(count)
        ]
        with (
            patch(_FIND, new_callable=AsyncMock, return_value=users),
            patch(_RECORD, new_callable=AsyncMock),
            patch(
                "app.services.email.send_inactive_user_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            result = await check_inactive_users(ctx)

        assert mock_email.await_count == count
        assert f"{count} inactive users" in result
        assert f"{count} emails" in result
