"""Unit tests for the subscription-plan seed script.

Two behaviors decide whether a production run is safe: the script must not
rewrite a plan whose content already matches (so `--dry-run` predicts the real
run), and a failure to clear the plan cache must surface rather than print a
success the API contradicts.

No `regression` markers here — every symbol under test is introduced by this
change, so these tests cannot run against the base revision at all, and an
import error is not proof of anything. The mutation check that backs them is
in the PR: reverting either behavior turns these red.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from scripts.payment_setup import (
    build_plan_catalogue,
    catalogue_fields,
    deactivate_free_plan,
    invalidate_plan_cache,
    reconcile_plan,
)


def _stored_document(plan, **overrides):
    """The catalogue plan as Mongo would hand it back, with an older timestamp."""
    stored = {
        "_id": "plan-id",
        **catalogue_fields(plan),
        "created_at": datetime(2020, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2020, 1, 1, tzinfo=UTC),
    }
    stored.update(overrides)
    return stored


async def test_reconcile_leaves_an_already_matching_plan_untouched() -> None:
    """A plan whose content matches is not rewritten just to move updated_at."""
    plan = build_plan_catalogue("monthly-id", "yearly-id")[1]
    collection = AsyncMock()
    collection.find_one.return_value = _stored_document(plan)

    outcome = await reconcile_plan(collection, plan, dry_run=False)

    assert outcome == "unchanged"
    collection.update_one.assert_not_awaited()


async def test_dry_run_and_write_agree_on_whether_a_plan_changes() -> None:
    """Whatever the dry run reports for a plan, the real run must do."""
    plan = build_plan_catalogue("monthly-id", "yearly-id")[1]
    collection = AsyncMock()
    collection.find_one.return_value = _stored_document(plan)

    previewed = await reconcile_plan(collection, plan, dry_run=True)
    applied = await reconcile_plan(collection, plan, dry_run=False)

    assert previewed == applied


async def test_reconcile_updates_a_plan_whose_price_drifted() -> None:
    """A differing catalogue field is written, with a fresh updated_at."""
    plan = build_plan_catalogue("monthly-id", "yearly-id")[1]
    collection = AsyncMock()
    collection.find_one.return_value = _stored_document(plan, amount=plan.amount + 500)
    before = datetime.now(UTC) - timedelta(seconds=1)

    outcome = await reconcile_plan(collection, plan, dry_run=False)

    assert outcome == "updated"
    written = collection.update_one.await_args.args[1]["$set"]
    assert written["amount"] == plan.amount
    assert written["updated_at"] > before


async def test_reconcile_creates_a_missing_plan() -> None:
    """A plan with no stored counterpart is inserted."""
    plan = build_plan_catalogue("monthly-id", "yearly-id")[0]
    collection = AsyncMock()
    collection.find_one.return_value = None

    outcome = await reconcile_plan(collection, plan, dry_run=False)

    assert outcome == "created"
    collection.insert_one.assert_awaited_once()


async def test_dry_run_writes_nothing_for_a_missing_plan() -> None:
    """The preview of a create touches neither insert nor update."""
    plan = build_plan_catalogue("monthly-id", "yearly-id")[0]
    collection = AsyncMock()
    collection.find_one.return_value = None

    outcome = await reconcile_plan(collection, plan, dry_run=True)

    assert outcome == "created"
    collection.insert_one.assert_not_awaited()
    collection.update_one.assert_not_awaited()


def test_catalogue_has_no_free_plan() -> None:
    """GAIA is paid-only — the seed script must not build a $0 Free row."""
    catalogue = build_plan_catalogue("monthly-id", "yearly-id")
    assert all(plan.amount > 0 or plan.name != "Free" for plan in catalogue)
    assert not any(plan.name == "Free" for plan in catalogue)


async def test_deactivate_free_plan_marks_an_existing_active_free_row_inactive() -> None:
    """A Free row left over from before the paid-only cutover is turned off,
    not deleted — so the historical record survives."""
    collection = AsyncMock()
    collection.find_one.return_value = {"_id": "free-id", "name": "Free", "is_active": True}

    changed = await deactivate_free_plan(collection, dry_run=False)

    assert changed is True
    written = collection.update_one.await_args.args[1]["$set"]
    assert written["is_active"] is False
    assert collection.update_one.await_args.args[0] == {"_id": "free-id"}


async def test_deactivate_free_plan_dry_run_writes_nothing() -> None:
    collection = AsyncMock()
    collection.find_one.return_value = {"_id": "free-id", "name": "Free", "is_active": True}

    changed = await deactivate_free_plan(collection, dry_run=True)

    assert changed is True
    collection.update_one.assert_not_awaited()


async def test_deactivate_free_plan_is_a_noop_when_no_active_free_row_exists() -> None:
    """Idempotent: a second run (or a catalogue that never had Free) does
    nothing rather than erroring."""
    collection = AsyncMock()
    collection.find_one.return_value = None

    changed = await deactivate_free_plan(collection, dry_run=False)

    assert changed is False
    collection.update_one.assert_not_awaited()


async def test_invalidate_plan_cache_drops_every_key() -> None:
    """Both catalogue keys are deleted in one command."""
    client = MagicMock()
    client.delete = AsyncMock(return_value=2)

    with patch("scripts.payment_setup.redis_cache") as cache:
        cache.client = client
        await invalidate_plan_cache()

    assert set(client.delete.await_args.args) == {"plans:active", "plans:all"}


async def test_invalidate_plan_cache_propagates_a_redis_failure() -> None:
    """A cache the API still reads from must fail the run, not print success."""
    client = MagicMock()
    client.delete = AsyncMock(side_effect=ConnectionError("redis down"))

    with patch("scripts.payment_setup.redis_cache") as cache:
        cache.client = client
        with pytest.raises(ConnectionError):
            await invalidate_plan_cache()
