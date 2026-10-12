"""purge_retired_integrations: selection of what to delete, against real repositories.

Only the Motor collection is faked, and the fake evaluates equality and $exists, so
the tools-only-stub filter itself is exercised: a full Integration document with the
same id must survive. Real Mongo proves the same filter in tests/contracts.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from fakeredis.aioredis import FakeRedis
import pytest

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.db.repositories.integrations import integration_repository
from app.scripts import purge_retired_integrations as script

RETIRED = "browserbase"
LIVE_ID = OAUTH_INTEGRATIONS[0].id
TOOLS = [{"name": "navigate", "description": "Open a page"}]

STUB = {"integration_id": RETIRED, "tools": TOOLS}
FULL_DOCUMENT = {
    "integration_id": RETIRED,
    "tools": TOOLS,
    "name": "Browserbase",
    "description": "Cloud browsers",
    "category": "developer",
    "managed_by": "mcp",
}


def _matches(document: dict[str, Any], filter_: dict[str, Any]) -> bool:
    for field, condition in filter_.items():
        if isinstance(condition, dict) and "$exists" in condition:
            if (field in document) != condition["$exists"]:
                return False
        elif isinstance(condition, dict) and "$in" in condition:
            if document.get(field) not in condition["$in"]:
                return False
        elif document.get(field) != condition:
            return False
    return True


class _Result:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class _Collection:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self.documents = documents

    async def distinct(self, field: str, filter_: dict[str, Any] | None = None) -> list[Any]:
        found = [d[field] for d in self.documents if _matches(d, filter_ or {})]
        return list(dict.fromkeys(found))

    async def delete_one(self, filter_: dict[str, Any]) -> _Result:
        for document in self.documents:
            if _matches(document, filter_):
                self.documents.remove(document)
                return _Result(1)
        return _Result(0)


@contextmanager
def _mongo(
    integrations: list[dict[str, Any]], user_rows: list[dict[str, Any]]
) -> Iterator[dict[str, _Collection]]:
    collections = {
        "integrations": _Collection(integrations),
        "user_integrations": _Collection(user_rows),
    }
    with patch(
        "app.db.repositories.base.get_async_collection", side_effect=collections.__getitem__
    ):
        yield collections


def _rows(integration_id: str, *user_ids: str) -> list[dict[str, Any]]:
    return [
        {"user_id": user_id, "integration_id": integration_id, "status": "connected"}
        for user_id in user_ids
    ]


def _args(**overrides: Any) -> argparse.Namespace:
    return argparse.Namespace(**{"apply": False, "retired_ids": [RETIRED], **overrides})


@pytest.mark.unit
class TestPurgeRetiredIntegrations:
    async def test_a_dry_run_reports_and_deletes_nothing(
        self, fake_redis: FakeRedis, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _mongo([dict(STUB)], _rows(RETIRED, "u1", "u2")) as db:
            await script._run(_args())

        assert db["integrations"].documents == [STUB]
        assert len(db["user_integrations"].documents) == 2
        out = capsys.readouterr().out
        assert f"{RETIRED}: 2 user row(s), tools-only stub: yes" in out
        assert "dry run: nothing deleted" in out

    async def test_apply_deletes_the_rows_and_the_stub(
        self, fake_redis: FakeRedis, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _mongo([dict(STUB)], _rows(RETIRED, "u1", "u2") + _rows(LIVE_ID, "u1")) as db:
            await script._run(_args(apply=True))

        assert db["integrations"].documents == []
        assert db["user_integrations"].documents == _rows(LIVE_ID, "u1")
        assert "deleted 2 user row(s), stub deleted: yes" in capsys.readouterr().out

    async def test_a_full_integration_document_with_the_same_id_is_never_deleted(
        self, fake_redis: FakeRedis
    ) -> None:
        with _mongo([dict(FULL_DOCUMENT)], []) as db:
            assert await script.purge(script.RetiredIntegration(RETIRED, [], True)) == (0, False)
            assert await integration_repository.tools_stub_ids() == []

        assert db["integrations"].documents == [FULL_DOCUMENT]

    async def test_running_twice_finds_nothing_the_second_time(
        self, fake_redis: FakeRedis, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _mongo([dict(STUB)], _rows(RETIRED, "u1")):
            await script._run(_args(apply=True))
            capsys.readouterr()
            await script._run(_args(apply=True))

        assert f"{RETIRED}: 0 user row(s), tools-only stub: no" in capsys.readouterr().out

    async def test_apply_reports_when_there_was_no_stub_to_delete(
        self, fake_redis: FakeRedis, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _mongo([], _rows(RETIRED, "u1")):
            await script._run(_args(apply=True))

        assert "  deleted 1 user row(s), stub deleted: no\n" in capsys.readouterr().out

    async def test_the_dry_run_ends_with_the_exact_apply_hint(
        self, fake_redis: FakeRedis, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with _mongo([dict(STUB)], []):
            await script._run(_args())

        assert capsys.readouterr().out.endswith(
            "\ndry run: nothing deleted. Re-run with --apply.\n"
        )

    async def test_an_id_with_a_full_document_is_refused_and_nothing_is_deleted(
        self, fake_redis: FakeRedis
    ) -> None:
        with _mongo([dict(FULL_DOCUMENT)], _rows(RETIRED, "u1")) as db:
            with pytest.raises(ValueError) as refused:
                await script._run(_args(apply=True))

        assert str(refused.value) == (
            f"still have a full integration document, not retired: {RETIRED}"
        )
        assert db["integrations"].documents == [FULL_DOCUMENT]
        assert db["user_integrations"].documents == _rows(RETIRED, "u1")

    async def test_the_dry_run_refuses_a_full_document_too(self, fake_redis: FakeRedis) -> None:
        with _mongo([dict(FULL_DOCUMENT)], []):
            with pytest.raises(ValueError, match="full integration document"):
                await script._run(_args())

    async def test_only_the_ids_with_a_full_document_are_named(self, fake_redis: FakeRedis) -> None:
        other = {**FULL_DOCUMENT, "integration_id": "other-full"}
        stub_only = {"integration_id": "stub-only", "tools": TOOLS}
        with _mongo([dict(FULL_DOCUMENT), other, stub_only], []):
            with pytest.raises(ValueError) as refused:
                await script._run(_args(retired_ids=[RETIRED, "stub-only", "other-full"]))

        assert str(refused.value).endswith(f": {RETIRED}, other-full")

    async def test_a_stub_only_id_is_accepted(self, fake_redis: FakeRedis) -> None:
        with _mongo([dict(STUB)], []):
            await script.require_retired([RETIRED])

    async def test_every_live_id_is_named_in_the_refusal(self) -> None:
        first, second = OAUTH_INTEGRATIONS[0].id, OAUTH_INTEGRATIONS[1].id
        with _mongo([], []):
            with pytest.raises(ValueError) as refused:
                await script._run(_args(retired_ids=[first, RETIRED, second]))

        assert str(refused.value) == (
            f"still in OAUTH_INTEGRATIONS, not retired: {first}, {second}"
        )

    async def test_an_id_still_in_the_catalog_is_refused_before_anything_is_read(self) -> None:
        with _mongo([], []) as db:
            with pytest.raises(ValueError, match=LIVE_ID):
                await script._run(_args(retired_ids=[RETIRED, LIVE_ID]))
        assert db["integrations"].documents == []

    async def test_apply_busts_the_per_user_and_global_tool_caches(
        self, fake_redis: FakeRedis
    ) -> None:
        keys = ["tools:user:u1:integration_capabilities", "tool_namespaces:u1", "mcp:tools:all"]
        for key in keys:
            await fake_redis.set(key, "stale")

        with _mongo([dict(STUB)], _rows(RETIRED, "u1")):
            await script._run(_args(apply=True))

        assert [await fake_redis.exists(key) for key in keys] == [0, 0, 0]


@pytest.mark.unit
class TestOrphanStubReport:
    async def test_only_stubs_outside_the_catalog_are_reported_with_their_user_counts(
        self, fake_redis: FakeRedis
    ) -> None:
        live_stub = {"integration_id": LIVE_ID, "tools": TOOLS}
        with _mongo([live_stub, dict(STUB)], _rows(RETIRED, "u1", "u2") + _rows(LIVE_ID, "u3")):
            orphans = await script.find_orphan_stubs()

        assert orphans == [script.OrphanStub(RETIRED, 2)]

    async def test_a_live_stub_does_not_stop_the_scan_for_later_orphans(
        self, fake_redis: FakeRedis
    ) -> None:
        live_stub = {"integration_id": LIVE_ID, "tools": TOOLS}
        late_orphan = {"integration_id": "~retired-last", "tools": TOOLS}
        with _mongo([live_stub, late_orphan], []):
            orphans = await script.find_orphan_stubs()

        assert orphans == [script.OrphanStub("~retired-last", 0)]

    async def test_the_dry_run_lists_orphans_beyond_the_ids_named(
        self, fake_redis: FakeRedis, capsys: pytest.CaptureFixture[str]
    ) -> None:
        other = {"integration_id": "gone-too", "tools": TOOLS}
        with _mongo([dict(STUB), other], _rows("gone-too", "u9")) as db:
            await script._run(_args())

        assert other in db["integrations"].documents
        out = capsys.readouterr().out
        assert "tools-only stubs outside OAUTH_INTEGRATIONS: 2" in out
        assert "gone-too: 1 user row(s)" in out
