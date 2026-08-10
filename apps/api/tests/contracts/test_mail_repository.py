"""Contract tests for MailRepository (analyzed-email summaries)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.mail import MailRepository
from app.models.mail_models import MailDocument


def _mail(**overrides: object) -> MailDocument:
    return MailDocument.model_validate({"user_id": "u1", "message_id": "m1", **overrides})


@pytest.fixture
def repo(raw_collection) -> MailRepository:
    return MailRepository()


class TestMailRepository:
    async def test_get_by_message_with_user_isolation(self, repo):
        await repo.create(_mail(user_id="owner", message_id="m1", is_important=True))
        got = await repo.get_by_message("owner", "m1")
        assert got is not None and got.is_important is True
        assert await repo.get_by_message("attacker", "m1") is None

    async def test_list_for_user_sorted_desc_and_important_filter(self, repo):
        now = datetime.now(UTC)
        await repo.create(
            _mail(user_id="u", message_id="old", analyzed_at=now - timedelta(hours=1))
        )
        await repo.create(_mail(user_id="u", message_id="new", analyzed_at=now, is_important=True))
        ordered = await repo.list_for_user("u")
        assert [m.message_id for m in ordered] == ["new", "old"]  # analyzed_at desc
        important = await repo.list_for_user("u", important_only=True)
        assert [m.message_id for m in important] == ["new"]

    async def test_list_by_message_ids(self, repo):
        for mid in ("a", "b", "c"):
            await repo.create(_mail(user_id="u", message_id=mid))
        got = await repo.list_by_message_ids("u", ["a", "c", "missing"])
        assert {m.message_id for m in got} == {"a", "c"}

    async def test_extra_allow_preserves_summary_fields(self, repo):
        await repo.create(_mail(user_id="u", message_id="m", summary="hi", score=9))
        dump = (await repo.get_by_message("u", "m")).model_dump()
        assert dump["summary"] == "hi" and dump["score"] == 9
