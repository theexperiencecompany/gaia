"""Unit tests for the subscription-plan seed script.

Two behaviors decide whether a production run is safe: the script must not
rewrite a plan whose content already matches (so --dry-run predicts the real
run), and a failure to clear the plan cache must surface rather than print a
success the API contradicts.

No regression markers here — every symbol under test is introduced by this
change, so these tests cannot run against the base revision at all, and an
import error is not proof of anything. The mutation check that backs them is
in the PR: reverting either behavior turns these red.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from dodopayments.types.price import OneTimePrice, RecurringPrice
import pytest
from scripts.payment_setup import (
    ProductPrice,
    build_plan_catalogue,
    catalogue_fields,
    deactivate_free_plan,
    fetch_product_price,
    invalidate_plan_cache,
    reconcile_plan,
    setup_payment_plans,
)

from app.models.payment_models import PlanDuration, PlanTier

MONTHLY = ProductPrice(product_id="monthly-id", amount=3000, currency="USD")
YEARLY = ProductPrice(product_id="yearly-id", amount=30000, currency="USD")


def _dodo_with(price: RecurringPrice | OneTimePrice) -> MagicMock:
    client = MagicMock()
    client.products.retrieve.return_value = SimpleNamespace(price=price)
    return client


def _recurring(
    interval: str, amount: int = 57284, currency: str = "ZAR", count: int = 1
) -> RecurringPrice:
    return RecurringPrice.model_validate(
        {
            "currency": currency,
            "discount": 0,
            "payment_frequency_count": count,
            "payment_frequency_interval": interval,
            "price": amount,
            "purchasing_power_parity": False,
            "subscription_period_count": 10,
            "subscription_period_interval": "Year",
            "type": "recurring_price",
        }
    )


def _stored_document(plan, **overrides):
    """Build the catalogue plan as Mongo would hand it back, with an older timestamp."""
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
    plan = build_plan_catalogue(MONTHLY, YEARLY)[1]
    collection = AsyncMock()
    collection.find_one.return_value = _stored_document(plan)

    outcome = await reconcile_plan(collection, plan, dry_run=False)

    assert outcome == "unchanged"
    collection.update_one.assert_not_awaited()


async def test_dry_run_and_write_agree_on_whether_a_plan_changes() -> None:
    """Whatever the dry run reports for a plan, the real run must do."""
    plan = build_plan_catalogue(MONTHLY, YEARLY)[1]
    collection = AsyncMock()
    collection.find_one.return_value = _stored_document(plan)

    previewed = await reconcile_plan(collection, plan, dry_run=True)
    applied = await reconcile_plan(collection, plan, dry_run=False)

    assert previewed == applied


async def test_reconcile_updates_a_plan_whose_price_drifted() -> None:
    """A differing catalogue field is written, with a fresh updated_at."""
    plan = build_plan_catalogue(MONTHLY, YEARLY)[1]
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
    plan = build_plan_catalogue(MONTHLY, YEARLY)[0]
    collection = AsyncMock()
    collection.find_one.return_value = None

    outcome = await reconcile_plan(collection, plan, dry_run=False)

    assert outcome == "created"
    collection.insert_one.assert_awaited_once()


async def test_dry_run_writes_nothing_for_a_missing_plan() -> None:
    """The preview of a create touches neither insert nor update."""
    plan = build_plan_catalogue(MONTHLY, YEARLY)[0]
    collection = AsyncMock()
    collection.find_one.return_value = None

    outcome = await reconcile_plan(collection, plan, dry_run=True)

    assert outcome == "created"
    collection.insert_one.assert_not_awaited()
    collection.update_one.assert_not_awaited()


def test_catalogue_has_no_free_plan() -> None:
    """GAIA is paid-only — the seed script must not build a $0 Free row."""
    catalogue = build_plan_catalogue(MONTHLY, YEARLY)
    assert all(plan.amount > 0 or plan.name != "Free" for plan in catalogue)
    assert not any(plan.name == "Free" for plan in catalogue)


async def test_deactivate_free_plan_marks_an_existing_active_free_row_inactive() -> None:
    """A leftover Free row is turned off, not deleted, so the historical record survives."""
    collection = AsyncMock()
    collection.find_one.return_value = {"_id": "free-id", "name": "Free", "is_active": True}

    changed = await deactivate_free_plan(collection, dry_run=False)

    assert changed is True
    written = collection.update_one.await_args.args[1]["$set"]
    assert written["is_active"] is False
    assert written["plan_type"] == "free"
    assert collection.update_one.await_args.args[0] == {"_id": "free-id"}


async def test_deactivate_free_plan_dry_run_writes_nothing() -> None:
    collection = AsyncMock()
    collection.find_one.return_value = {"_id": "free-id", "name": "Free", "is_active": True}

    changed = await deactivate_free_plan(collection, dry_run=True)

    assert changed is True
    collection.update_one.assert_not_awaited()


async def test_deactivate_free_plan_is_a_noop_when_no_active_free_row_exists() -> None:
    """Idempotent: a second run, or a catalogue that never had Free, does nothing rather than erroring."""
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


async def test_apply_clears_the_cached_catalogue_even_when_an_untagged_row_fails_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new prices are already written, so a stale cache would serve the old ones for an hour."""
    monkeypatch.setenv("DODO_PAYMENTS_API_KEY", "key")
    price = ProductPrice(product_id="pdt_1", amount=3000, currency="USD")
    invalidate = AsyncMock()
    with (
        patch("scripts.payment_setup.payment_service"),
        patch("scripts.payment_setup.fetch_product_price", return_value=price),
        patch("scripts.payment_setup.AsyncIOMotorClient"),
        patch("scripts.payment_setup.cleanup_old_indexes", new=AsyncMock()),
        patch("scripts.payment_setup.reconcile_plan", new=AsyncMock(return_value="unchanged")),
        patch("scripts.payment_setup.deactivate_free_plan", new=AsyncMock(return_value=False)),
        patch("scripts.payment_setup.count_untagged_plans", new=AsyncMock(return_value=1)),
        patch("scripts.payment_setup.invalidate_plan_cache", new=invalidate),
        pytest.raises(RuntimeError, match="1 plan row"),
    ):
        await setup_payment_plans("pdt_m", "pdt_y", dry_run=False)

    invalidate.assert_awaited_once_with()


async def test_invalidate_plan_cache_propagates_a_redis_failure() -> None:
    """A cache the API still reads from must fail the run, not print success."""
    client = MagicMock()
    client.delete = AsyncMock(side_effect=ConnectionError("redis down"))

    with patch("scripts.payment_setup.redis_cache") as cache:
        cache.client = client
        with pytest.raises(ConnectionError):
            await invalidate_plan_cache()


def test_catalogue_prices_pro_from_the_dodo_products() -> None:
    """The Pro rows carry what Dodo charges, never a hand-typed copy."""
    monthly = ProductPrice(product_id="m", amount=57284, currency="ZAR")
    yearly = ProductPrice(product_id="y", amount=572840, currency="ZAR")

    catalogue = build_plan_catalogue(monthly, yearly)

    assert [(p.dodo_product_id, p.amount, p.currency, p.plan_type) for p in catalogue] == [
        ("m", 57284, "ZAR", PlanTier.PRO),
        ("y", 572840, "ZAR", PlanTier.PRO),
        ("", 0, "USD", PlanTier.ENTERPRISE),
    ]


def test_fetch_product_price_reads_the_recurring_price() -> None:
    client = _dodo_with(_recurring("Month"))

    price = fetch_product_price(client, "pdt_1", PlanDuration.MONTHLY)

    assert price == ProductPrice(product_id="pdt_1", amount=57284, currency="ZAR")
    client.products.retrieve.assert_called_once_with("pdt_1")


def test_fetch_product_price_refuses_a_product_billed_on_another_cycle() -> None:
    """A yearly id passed as the monthly one would price the monthly row at a year's charge."""
    with pytest.raises(ValueError) as excinfo:
        fetch_product_price(_dodo_with(_recurring("Year")), "pdt_1", PlanDuration.MONTHLY)

    assert str(excinfo.value) == (
        "Dodo product pdt_1 bills every 1 Year, not the monthly plan's 1 Month"
    )


@pytest.mark.parametrize(
    ("interval", "duration"), [("Month", PlanDuration.MONTHLY), ("Year", PlanDuration.YEARLY)]
)
def test_fetch_product_price_refuses_a_product_billed_every_several_periods(
    interval: str, duration: PlanDuration
) -> None:
    """A quarterly charge stored as the monthly row would show three months' price as one month's."""
    with pytest.raises(ValueError) as excinfo:
        fetch_product_price(_dodo_with(_recurring(interval, count=3)), "pdt_1", duration)

    assert str(excinfo.value) == (
        f"Dodo product pdt_1 bills every 3 {interval}, not the {duration} plan's 1 {interval}"
    )


def test_fetch_product_price_refuses_a_one_time_product() -> None:
    one_time = OneTimePrice.model_validate(
        {
            "currency": "USD",
            "discount": 0,
            "price": 3000,
            "purchasing_power_parity": False,
            "type": "one_time_price",
        }
    )
    with pytest.raises(ValueError, match="not a subscription"):
        fetch_product_price(_dodo_with(one_time), "pdt_1", PlanDuration.MONTHLY)


async def test_deactivate_free_plan_tags_an_already_inactive_untagged_row() -> None:
    """The API reads inactive rows too, so a retired Free row still needs its tier."""
    collection = AsyncMock()
    collection.find_one.return_value = {"_id": "free-id", "name": "Free", "is_active": False}

    changed = await deactivate_free_plan(collection, dry_run=False)

    assert changed is True
    assert collection.update_one.await_args.args[1]["$set"]["plan_type"] == "free"


@pytest.mark.parametrize(
    "dodo_monthly",
    [
        ProductPrice(product_id="pdt_m", amount=4000, currency="USD"),
        ProductPrice(product_id="pdt_m", amount=3000, currency="EUR"),
    ],
)
async def test_setup_refuses_a_monthly_price_the_marketing_copy_does_not_advertise(
    monkeypatch: pytest.MonkeyPatch, dodo_monthly: ProductPrice
) -> None:
    """Static marketing pages quote the shared advertised price, so a catalogue that disagrees must not be written."""
    monkeypatch.setenv("DODO_PAYMENTS_API_KEY", "key")
    mongo = MagicMock()
    with (
        patch("scripts.payment_setup.payment_service"),
        patch("scripts.payment_setup.fetch_product_price", side_effect=[dodo_monthly, YEARLY]),
        patch("scripts.payment_setup.AsyncIOMotorClient", new=mongo),
        pytest.raises(ValueError, match="the marketing pages advertise"),
    ):
        await setup_payment_plans("pdt_m", "pdt_y", dry_run=False)

    mongo.assert_not_called()


async def test_setup_accepts_the_advertised_monthly_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DODO_PAYMENTS_API_KEY", "key")
    with (
        patch("scripts.payment_setup.payment_service"),
        patch("scripts.payment_setup.fetch_product_price", side_effect=[MONTHLY, YEARLY]),
        patch("scripts.payment_setup.AsyncIOMotorClient"),
        patch("scripts.payment_setup.reconcile_plan", new=AsyncMock(return_value="unchanged")),
        patch("scripts.payment_setup.deactivate_free_plan", new=AsyncMock(return_value=False)),
        patch("scripts.payment_setup.count_untagged_plans", new=AsyncMock(return_value=0)),
        patch("scripts.payment_setup.print_active_plans", new=AsyncMock()),
    ):
        assert await setup_payment_plans("pdt_m", "pdt_y", dry_run=True) is True
