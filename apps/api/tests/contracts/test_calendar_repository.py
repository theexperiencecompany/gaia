"""Contract tests for CalendarRepository (global, per-user calendar preferences)."""

from __future__ import annotations

import uuid

import pytest

from app.db.repositories.calendar import CalendarRepository


@pytest.fixture
def repo(raw_collection) -> CalendarRepository:
    return CalendarRepository()


class TestCalendarRepository:
    async def test_get_for_user_miss_then_hit(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        assert await repo.get_for_user(user) is None

        changed = await repo.set_selected_calendars(user, ["primary", "work@x.com"])
        assert changed is True

        doc = await repo.get_for_user(user)
        assert doc is not None
        assert doc.user_id == user
        assert doc.selected_calendars == ["primary", "work@x.com"]

    async def test_set_is_upsert_then_update(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await repo.set_selected_calendars(user, ["a"])
        changed = await repo.set_selected_calendars(user, ["a", "b"])
        assert changed is True
        assert (await repo.get_for_user(user)).selected_calendars == ["a", "b"]

    async def test_set_identical_reports_no_change(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await repo.set_selected_calendars(user, ["primary"])
        # Same value → no write, mirrors the old modified_count==0 "no changes" path.
        assert await repo.set_selected_calendars(user, ["primary"]) is False

    async def test_preferences_are_user_scoped(self, repo):
        a = f"u-{uuid.uuid4().hex}"
        b = f"u-{uuid.uuid4().hex}"
        await repo.set_selected_calendars(a, ["cal-a"])
        await repo.set_selected_calendars(b, ["cal-b"])

        assert (await repo.get_for_user(a)).selected_calendars == ["cal-a"]
        assert (await repo.get_for_user(b)).selected_calendars == ["cal-b"]

    async def test_repair_rewrites_the_selection_the_read_loaded(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await repo.set_selected_calendars(user, ["primary"])

        await repo.repair_selected_calendars(user, ["primary"], ["me@x.com"])

        assert (await repo.get_for_user(user)).selected_calendars == ["me@x.com"]

    async def test_repair_keeps_a_selection_saved_after_the_read_loaded(self, repo):
        user = f"u-{uuid.uuid4().hex}"
        await repo.set_selected_calendars(user, ["primary"])
        await repo.set_selected_calendars(user, ["team@x.com"])

        await repo.repair_selected_calendars(user, ["primary"], ["me@x.com"])

        assert (await repo.get_for_user(user)).selected_calendars == ["team@x.com"]

    async def test_repair_of_a_missing_selection_inserts_it(self, repo):
        user = f"u-{uuid.uuid4().hex}"

        await repo.repair_selected_calendars(user, None, ["a", "b"])

        assert (await repo.get_for_user(user)).selected_calendars == ["a", "b"]

    async def test_repair_of_a_missing_selection_keeps_one_saved_since(self, repo, raw_collection):
        user = f"u-{uuid.uuid4().hex}"
        await repo.set_selected_calendars(user, ["team@x.com"])

        await repo.repair_selected_calendars(user, None, ["a", "b"])

        assert (await repo.get_for_user(user)).selected_calendars == ["team@x.com"]
        assert await raw_collection.count_documents({"user_id": user}) == 1
