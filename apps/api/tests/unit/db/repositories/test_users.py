"""Hermetic unit tests for ``UserRepository``'s raw-update writes — the write-miss
cache eviction, and the activation checklist's collapse.

A user document deleted from Mongo while its entity cache entry was still live
kept authenticating: reads were served from cache while every write matched no
document (``PATCH /onboarding/preferences`` answered 404 "user not found"). The
base raw-update seam now evicts the targeted entity key when the write matches
nothing, so the next auth read misses, re-reads Mongo and 401s honestly. The
driver is mocked at ``app.db.repositories.base.get_async_collection``, the single
seam every read and write in the base repository goes through.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from pymongo import ReturnDocument
import pytest

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.constants.first_steps import (
    FIRST_STEPS_COLLAPSED_AT_FIELD,
    FIRST_STEPS_COLLAPSED_FIELD,
)
from app.db.repositories.users import UserRepository
from app.models.user_models import OnboardingPreferences
from tests.helpers import captured_wide_event

USER_ID = "68d1f8a2c3b4a5d6e7f80912"
NOW = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def _raw() -> dict[str, Any]:
    return {
        "_id": ObjectId(USER_ID),
        "email": "deleted@example.com",
        "created_at": NOW,
        "updated_at": NOW,
    }


@pytest.fixture
def collection() -> Iterator[MagicMock]:
    mock = MagicMock()
    mock.find_one_and_update = AsyncMock(return_value=None)
    with patch("app.db.repositories.base.get_async_collection", return_value=mock):
        yield mock


@pytest.fixture
def repo() -> UserRepository:
    return UserRepository()


def _evict_spy(repo: UserRepository) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def _cache_evict(scope: str, doc_id: str) -> None:
        calls.append((scope, doc_id))

    repo._cache_evict = _cache_evict  # type: ignore[method-assign]  # test observes the invalidation seam
    return calls


class TestUpdateOnboardingPreferences:
    async def test_a_write_matching_no_user_evicts_that_user_s_cache_entry(
        self, repo: UserRepository, collection: MagicMock
    ) -> None:
        evictions = _evict_spy(repo)

        result = await repo.update_onboarding_preferences(
            USER_ID, OnboardingPreferences(profession="engineer")
        )

        assert result is None
        assert evictions == [(REPO_GLOBAL_SCOPE, USER_ID)]

    async def test_a_matching_write_does_not_evict_the_entity_key(
        self, repo: UserRepository, collection: MagicMock
    ) -> None:
        collection.find_one_and_update = AsyncMock(return_value=_raw())
        evictions = _evict_spy(repo)

        result = await repo.update_onboarding_preferences(
            USER_ID, OnboardingPreferences(profession="engineer")
        )

        assert result is not None
        assert evictions == []


def _update_call(collection: MagicMock) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The single ``find_one_and_update`` call's filter, update document and kwargs."""
    collection.find_one_and_update.assert_awaited_once()
    args, kwargs = collection.find_one_and_update.await_args
    return args[0], args[1], kwargs


class TestSetFirstStepsCollapsed:
    """``set_first_steps_collapsed`` — the checklist's only persisted state.

    The service tier mocks this method away, so what it writes and what its
    boolean means are only visible here. The return value is the 404 signal:
    it says whether a user document was there to write to, not whether the
    stored value changed — collapsing an already-collapsed checklist is a
    success, not a miss.
    """

    async def test_stamps_the_collapse_and_when_it_happened(
        self, repo: UserRepository, collection: MagicMock
    ) -> None:
        """The stamp is tz-aware UTC. Mongo stores a BSON date as UTC and reads
        a naive one back as though it already were, so a local-clock stamp lands
        in the document silently shifted by the writing machine's offset."""
        collection.find_one_and_update = AsyncMock(return_value=_raw())

        await repo.set_first_steps_collapsed(USER_ID, True)

        filter_, update, _kwargs = _update_call(collection)
        assert filter_ == {"_id": ObjectId(USER_ID)}
        assert update["$set"][FIRST_STEPS_COLLAPSED_FIELD] is True
        stamped = update["$set"][FIRST_STEPS_COLLAPSED_AT_FIELD]
        assert isinstance(stamped, datetime)
        assert stamped.tzinfo is UTC

    async def test_expanding_clears_the_timestamp_rather_than_leaving_the_old_one(
        self, repo: UserRepository, collection: MagicMock
    ) -> None:
        """A stale ``collapsed_at`` under ``collapsed: False`` would read as a
        checklist collapsed at a time it was open."""
        collection.find_one_and_update = AsyncMock(return_value=_raw())

        await repo.set_first_steps_collapsed(USER_ID, False)

        _filter, update, _kwargs = _update_call(collection)
        assert update["$set"][FIRST_STEPS_COLLAPSED_FIELD] is False
        assert update["$set"][FIRST_STEPS_COLLAPSED_AT_FIELD] is None

    async def test_touches_nothing_but_the_collapse_and_the_write_clock(
        self, repo: UserRepository, collection: MagicMock
    ) -> None:
        collection.find_one_and_update = AsyncMock(return_value=_raw())

        await repo.set_first_steps_collapsed(USER_ID, True)

        _filter, update, _kwargs = _update_call(collection)
        assert set(update) == {"$set"}
        assert set(update["$set"]) == {
            FIRST_STEPS_COLLAPSED_FIELD,
            FIRST_STEPS_COLLAPSED_AT_FIELD,
            "updated_at",
        }

    async def test_reads_back_the_before_image_so_the_cache_is_never_seeded(
        self, repo: UserRepository, collection: MagicMock
    ) -> None:
        """The base treats an AFTER read-back as cacheable and stores it. This
        write reads the BEFORE image precisely so the entity key is evicted
        instead — an authenticated read must not be served the document this
        write produced without going through the read path."""
        collection.find_one_and_update = AsyncMock(return_value=_raw())
        evictions = _evict_spy(repo)

        await repo.set_first_steps_collapsed(USER_ID, True)

        _filter, _update, kwargs = _update_call(collection)
        assert kwargs["return_document"] is ReturnDocument.BEFORE
        assert evictions == [(REPO_GLOBAL_SCOPE, USER_ID)]

    async def test_asks_the_base_for_the_before_image_with_a_real_boolean(
        self, repo: UserRepository, collection: MagicMock
    ) -> None:
        """``_apply_raw_update`` declares ``return_document: bool`` and branches on
        it twice — the image the driver returns, and store-vs-evict on the entity
        cache. A non-boolean rides on those two branches happening to agree about
        truthiness, which is not what the signature promises and not what the
        sibling writes in this repository pass."""
        seen: dict[str, object] = {}

        async def _spy(*_args: object, **kwargs: object) -> None:
            seen.update(kwargs)

        repo._apply_raw_update = _spy  # type: ignore[method-assign]  # test observes the base seam

        await repo.set_first_steps_collapsed(USER_ID, True)

        assert seen["return_document"] is False
        assert seen["scope"] == REPO_GLOBAL_SCOPE

    async def test_reports_the_user_was_there_to_write_to(
        self, repo: UserRepository, collection: MagicMock
    ) -> None:
        collection.find_one_and_update = AsyncMock(return_value=_raw())

        assert await repo.set_first_steps_collapsed(USER_ID, True) is True

    async def test_reports_a_missing_user_so_the_endpoint_can_404(
        self, repo: UserRepository, collection: MagicMock
    ) -> None:
        assert await repo.set_first_steps_collapsed(USER_ID, True) is False


class _Cursor:
    """A Motor cursor over raw documents: chainable, awaitable to a list,
    async-iterable — the shapes ``_find`` and ``_find_lenient`` each use."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs

    def sort(self, *_: object) -> _Cursor:
        return self

    def skip(self, *_: object) -> _Cursor:
        return self

    def limit(self, *_: object) -> _Cursor:
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return self._docs

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[dict[str, Any]]:
        for doc in self._docs:
            yield doc


def _good(email: str) -> dict[str, Any]:
    return {
        "_id": ObjectId(),
        "email": email,
        "created_at": NOW,
        "updated_at": NOW,
        "last_active_at": NOW,
    }


@pytest.mark.parametrize(
    "read",
    [
        lambda repo: repo.find_nurture_candidates(NOW),
        lambda repo: repo.find_inactive_email_candidates(NOW),
        lambda repo: repo.find_dormant_since(NOW),
        lambda repo: repo.find_stuck_personalization(NOW),
    ],
    ids=["nurture", "inactive_email", "dormant", "stuck_personalization"],
)
async def test_a_cohort_read_skips_one_malformed_row_and_keeps_the_rest(
    repo: UserRepository, collection: MagicMock, read: Callable[[UserRepository], Awaitable[Any]]
) -> None:
    """A legacy ``onboarding`` value of the wrong type raised inside the
    repository call — above every per-user try/except in the nurture and
    inactivity sweeps — so one bad row meant nobody in the cohort got mail."""
    legacy = {**_good("legacy@example.com"), "onboarding": "completed"}
    collection.find = MagicMock(
        return_value=_Cursor([_good("a@example.com"), legacy, _good("b@example.com")])
    )

    async with captured_wide_event() as wide:
        found = await read(repo)

    assert [user.email for user in found] == ["a@example.com", "b@example.com"]
    (warning,) = wide["warnings"]
    assert warning["collection"] == "users"
    assert warning["document_id"] == legacy["_id"]
