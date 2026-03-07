"""Unit tests for user_tasks ARQ worker."""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.workers.tasks.user_tasks import check_inactive_users


def _make_db_user(
    email: str = "user@example.com",
    name: str = "Test User",
    user_id: str = "507f1f77bcf86cd799439011",
    last_active_days_ago: int = 10,
) -> dict:
    """Build a minimal user document as returned by MongoDB."""
    last_active = datetime.now(timezone.utc) - timedelta(days=last_active_days_ago)
    return {
        "_id": MagicMock(__str__=lambda s: user_id),
        "email": email,
        "name": name,
        "last_active_at": last_active.replace(tzinfo=None),
        "is_active": True,
    }


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
            patch("app.utils.email_utils.send_inactive_user_email") as mock_email,
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
                "app.utils.email_utils.send_inactive_user_email",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_email,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
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
                "app.utils.email_utils.send_inactive_user_email",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_email,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            await check_inactive_users(ctx)

        mock_email.assert_awaited_once_with(
            user_email="carol@example.com",
            user_name="Carol",
            user_id="id_carol",
        )

    async def test_failed_email_does_not_count_in_total(self, ctx):
        users = [
            _make_db_user("ok@example.com", "OK User", "id_ok"),
            _make_db_user("fail@example.com", "Fail User", "id_fail"),
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        async def selective_send(**kwargs):
            if kwargs["user_email"] == "ok@example.com":
                return True
            raise RuntimeError("SMTP error")

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch(
                "app.utils.email_utils.send_inactive_user_email",
                side_effect=selective_send,
            ),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await check_inactive_users(ctx)

        # Only 1 email successfully sent; 1 errored (swallowed per-user)
        assert "2 inactive users" in result
        assert "1 emails" in result

    async def test_email_returning_false_not_counted(self, ctx):
        user = _make_db_user("ghost@example.com", "Ghost", "id_ghost")
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[user])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch(
                "app.utils.email_utils.send_inactive_user_email",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await check_inactive_users(ctx)

        assert "0 emails" in result

    async def test_db_query_filters_seven_days_inactive(self, ctx):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch("app.utils.email_utils.send_inactive_user_email"),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            before_call = datetime.now(timezone.utc)
            await check_inactive_users(ctx)
            after_call = datetime.now(timezone.utc)

        query = mock_col.find.call_args[0][0]
        cutoff = query["last_active_at"]["$lt"]

        expected_lower = (before_call - timedelta(days=7)).replace(tzinfo=None)
        expected_upper = (after_call - timedelta(days=7)).replace(tzinfo=None)

        assert (
            expected_lower - timedelta(seconds=5)
            <= cutoff
            <= expected_upper + timedelta(seconds=5)
        )

    async def test_db_query_excludes_inactive_flagged_users(self, ctx):
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch("app.utils.email_utils.send_inactive_user_email"),
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
            patch("app.utils.email_utils.send_inactive_user_email"),
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            await check_inactive_users(ctx)

        query = mock_col.find.call_args[0][0]

        # The $or clause must be present to prevent duplicate emails.
        # Removing it from production code will cause this assertion to fail.
        assert "$or" in query, (
            "Query must contain a $or clause to avoid re-sending emails"
        )

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
        assert isinstance(lt_branch["$lt"], datetime), (
            "The $lt value must be a datetime"
        )

    async def test_db_exception_propagates(self, ctx):
        with patch("app.db.mongodb.collections.users_collection") as mock_col:
            mock_col.find = MagicMock(side_effect=RuntimeError("MongoDB down"))
            with pytest.raises(RuntimeError, match="MongoDB down"):
                await check_inactive_users(ctx)

    async def test_multiple_users_all_succeed_count_matches(self, ctx):
        count = 5
        users = [
            _make_db_user(f"user{i}@example.com", f"User {i}", f"id_{i}")
            for i in range(count)
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=users)

        with (
            patch("app.db.mongodb.collections.users_collection") as mock_col,
            patch(
                "app.utils.email_utils.send_inactive_user_email",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_email,
        ):
            mock_col.find = MagicMock(return_value=mock_cursor)
            result = await check_inactive_users(ctx)

        assert mock_email.await_count == count
        assert f"{count} inactive users" in result
        assert f"{count} emails" in result
