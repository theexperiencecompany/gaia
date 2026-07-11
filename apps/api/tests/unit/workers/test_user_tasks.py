"""Unit tests for user_tasks ARQ worker."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.tasks.user_tasks import _should_send_inactive_email, check_inactive_users


def _make_db_user(
    email: str = "user@example.com",
    name: str = "Test User",
    user_id: str = "507f1f77bcf86cd799439011",
    last_active_days_ago: int = 10,
) -> dict:
    """Build a minimal user document as returned by MongoDB."""
    last_active = datetime.now(UTC) - timedelta(days=last_active_days_ago)
    return {
        "_id": MagicMock(__str__=lambda s: user_id),
        "email": email,
        "name": name,
        "last_active_at": last_active.replace(tzinfo=None),
        "is_active": True,
    }


@pytest.mark.unit
class TestShouldSendInactiveEmail:
    """Throttle policy: first email after 7 inactive days, second after 14, then stop."""

    def test_less_than_7_days_inactive(self):
        now = datetime.now(UTC)
        user = {"last_active_at": now - timedelta(days=3), "last_inactive_email_sent": None}
        assert _should_send_inactive_email(user) is False

    def test_no_last_active(self):
        assert _should_send_inactive_email({"last_inactive_email_sent": None}) is False

    def test_email_sent_recently(self):
        now = datetime.now(UTC)
        user = {
            "last_active_at": now - timedelta(days=10),
            "last_inactive_email_sent": now - timedelta(days=2),
        }
        assert _should_send_inactive_email(user) is False

    def test_eligible_first_email(self):
        now = datetime.now(UTC)
        user = {"last_active_at": now - timedelta(days=10), "last_inactive_email_sent": None}
        assert _should_send_inactive_email(user) is True

    def test_second_email_at_day_14(self):
        """Real-world timing: first email at day 7, second due at day 14."""
        now = datetime.now(UTC)
        user = {
            "last_active_at": now - timedelta(days=14),
            "last_inactive_email_sent": now - timedelta(days=7),
        }
        assert _should_send_inactive_email(user) is True

    def test_overdue_second_email_still_sent(self):
        now = datetime.now(UTC)
        user = {
            "last_active_at": now - timedelta(days=15),
            "last_inactive_email_sent": now - timedelta(days=8),
        }
        assert _should_send_inactive_email(user) is True

    def test_max_2_emails(self):
        now = datetime.now(UTC)
        user = {
            "last_active_at": now - timedelta(days=21),
            "last_inactive_email_sent": now - timedelta(days=7),
            "inactive_email_count": 2,
        }
        assert _should_send_inactive_email(user) is False

    def test_legacy_doc_without_count_treated_as_one_send(self):
        """Docs from before the counter existed recorded their send via the timestamp only."""
        now = datetime.now(UTC)
        user = {
            "last_active_at": now - timedelta(days=14),
            "last_inactive_email_sent": now - timedelta(days=7),
            "inactive_email_count": 0,
        }
        assert _should_send_inactive_email(user) is True

    def test_new_inactivity_episode_resets_count(self):
        """An email sent before the user's last activity belongs to a previous episode."""
        now = datetime.now(UTC)
        user = {
            "last_active_at": now - timedelta(days=10),
            "last_inactive_email_sent": now - timedelta(days=90),
            "inactive_email_count": 2,
        }
        assert _should_send_inactive_email(user) is True

    def test_naive_last_active_handled(self):
        """MongoDB may return naive datetimes; the policy should handle them."""
        now = datetime.now(UTC)
        user = {
            "last_active_at": (now - timedelta(days=10)).replace(tzinfo=None),
            "last_inactive_email_sent": None,
        }
        assert _should_send_inactive_email(user) is True

    def test_naive_last_email_sent_handled(self):
        now = datetime.now(UTC)
        user = {
            "last_active_at": now - timedelta(days=10),
            "last_inactive_email_sent": (now - timedelta(days=2)).replace(tzinfo=None),
        }
        assert _should_send_inactive_email(user) is False


@pytest.mark.unit
class TestCheckInactiveUsers:
    """Tests for check_inactive_users ARQ task."""

    @pytest.fixture
    def ctx(self) -> dict:
        return {}

    async def test_no_inactive_users_sends_no_emails(self, ctx):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch("app.services.email.send_inactive_user_email") as mock_email,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await check_inactive_users(ctx)

        mock_email.assert_not_called()
        assert "0 inactive users" in result
        assert "0 emails" in result

    async def test_sends_email_for_each_inactive_user(self, ctx):
        users = [
            _make_db_user("alice@example.com", "Alice", "id_1"),
            _make_db_user("bob@example.com", "Bob", "id_2"),
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch(
                "app.services.email.send_inactive_user_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_col.update_one = AsyncMock()
            result = await check_inactive_users(ctx)

        assert mock_email.await_count == 2
        assert "2 inactive users" in result
        assert "2 emails" in result

    async def test_email_called_with_correct_arguments(self, ctx):
        user = _make_db_user("carol@example.com", "Carol", "id_carol")
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[user])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch(
                "app.services.email.send_inactive_user_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_col.update_one = AsyncMock()
            await check_inactive_users(ctx)

        mock_email.assert_awaited_once_with("carol@example.com", "Carol")

    async def test_sent_email_updates_tracking(self, ctx):
        user = _make_db_user("carol@example.com", "Carol", "id_carol")
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[user])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch("app.services.email.send_inactive_user_email", new_callable=AsyncMock),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_col.update_one = AsyncMock()
            await check_inactive_users(ctx)

        mock_col.update_one.assert_awaited_once()
        query, update = mock_col.update_one.call_args[0]
        assert query == {"_id": user["_id"]}
        assert isinstance(update["$set"]["last_inactive_email_sent"], datetime)
        assert update["$set"]["inactive_email_count"] == 1

    async def test_legacy_user_second_send_sets_count_to_two(self, ctx):
        """A pre-counter doc (timestamp only) counts as one send, so the next send stores 2."""
        user = _make_db_user("legacy@example.com", "Legacy", "id_legacy", last_active_days_ago=14)
        user["last_inactive_email_sent"] = (datetime.now(UTC) - timedelta(days=7)).replace(
            tzinfo=None
        )
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[user])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch("app.services.email.send_inactive_user_email", new_callable=AsyncMock),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_col.update_one = AsyncMock()
            await check_inactive_users(ctx)

        update = mock_col.update_one.call_args[0][1]
        assert update["$set"]["inactive_email_count"] == 2

    async def test_failed_email_does_not_count_in_total(self, ctx):
        users = [
            _make_db_user("ok@example.com", "OK User", "id_ok"),
            _make_db_user("fail@example.com", "Fail User", "id_fail"),
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        async def selective_send(user_email, user_name=None):
            if user_email != "ok@example.com":
                raise RuntimeError("SMTP error")

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch(
                "app.services.email.send_inactive_user_email",
                side_effect=selective_send,
            ),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_col.update_one = AsyncMock()
            result = await check_inactive_users(ctx)

        # Only 1 email successfully sent; 1 errored (swallowed per-user)
        assert "2 inactive users" in result
        assert "1 emails" in result

    async def test_recently_emailed_user_skipped(self, ctx):
        """A user who got an inactive email 2 days ago is skipped by the throttle."""
        user = _make_db_user("ghost@example.com", "Ghost", "id_ghost")
        user["last_inactive_email_sent"] = (datetime.now(UTC) - timedelta(days=2)).replace(
            tzinfo=None
        )
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[user])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch(
                "app.services.email.send_inactive_user_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await check_inactive_users(ctx)

        mock_email.assert_not_awaited()
        assert "0 emails" in result

    async def test_db_query_filters_seven_days_inactive(self, ctx):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch("app.services.email.send_inactive_user_email"),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            before_call = datetime.now(UTC)
            await check_inactive_users(ctx)
            after_call = datetime.now(UTC)

        query = mock_col.find.call_args[0][0]
        cutoff = query["last_active_at"]["$lt"]

        expected_lower = (before_call - timedelta(days=7)).replace(tzinfo=None)
        expected_upper = (after_call - timedelta(days=7)).replace(tzinfo=None)

        assert (
            expected_lower - timedelta(seconds=5) <= cutoff <= expected_upper + timedelta(seconds=5)
        )

    async def test_db_query_excludes_inactive_flagged_users(self, ctx):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch("app.services.email.send_inactive_user_email"),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            await check_inactive_users(ctx)

        query = mock_col.find.call_args[0][0]
        assert query["is_active"] == {"$ne": False}

    async def test_query_excludes_recently_emailed_users(self, ctx):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch("app.services.email.send_inactive_user_email"),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            await check_inactive_users(ctx)

        query = mock_col.find.call_args[0][0]

        # The $or clause must be present to prevent duplicate emails.
        # Removing it from production code will cause this assertion to fail.
        assert "$or" in query, "Query must contain a $or clause to avoid re-sending emails"

        or_conditions = query["$or"]
        assert isinstance(or_conditions, list) and len(or_conditions) >= 2, (
            "$or must have at least two conditions"
        )

        # Collect all top-level field names referenced across $or branches
        field_names = [list(cond.keys())[0] for cond in or_conditions]
        assert field_names.count("last_inactive_email_sent") == 2, (
            "Both $or branches must reference last_inactive_email_sent"
        )

        # One branch must check that the field is absent
        exists_branch = next(
            (
                cond["last_inactive_email_sent"]
                for cond in or_conditions
                if cond.get("last_inactive_email_sent") == {"$exists": False}
            ),
            None,
        )
        assert exists_branch is not None, (
            "One $or branch must check {$exists: False} for last_inactive_email_sent"
        )

        # The other branch must check that the field is older than the cutoff
        lt_branch = next(
            (
                cond["last_inactive_email_sent"]
                for cond in or_conditions
                if "$lt" in cond.get("last_inactive_email_sent", {})
            ),
            None,
        )
        assert lt_branch is not None, (
            "One $or branch must check {$lt: <cutoff>} for last_inactive_email_sent"
        )
        assert isinstance(lt_branch["$lt"], datetime), "The $lt value must be a datetime"

    async def test_db_exception_propagates(self, ctx):
        with patch("app.db.mongodb.collections.users_collection") as mock_col:
            mock_col.find = MagicMock(side_effect=RuntimeError("MongoDB down"))
            with pytest.raises(RuntimeError, match="MongoDB down"):
                await check_inactive_users(ctx)

    async def test_multiple_users_all_succeed_count_matches(self, ctx):
        count = 5
        users = [
            _make_db_user(f"user{i}@example.com", f"User {i}", f"id_{i}") for i in range(count)
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch(
                "app.services.email.send_inactive_user_email",
                new_callable=AsyncMock,
            ) as mock_email,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            mock_col.update_one = AsyncMock()
            result = await check_inactive_users(ctx)

        assert mock_email.await_count == count
        assert f"{count} inactive users" in result
        assert f"{count} emails" in result
