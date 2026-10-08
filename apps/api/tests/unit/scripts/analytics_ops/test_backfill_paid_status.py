"""Paid-state person properties from Mongo subscriptions: the projection, the newest row, the idempotent resend."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from scripts.analytics_ops.backfill_paid_status import (
    PERSON_STATE_HOGQL,
    apply,
    latest_states,
    stale_states,
)
from scripts.analytics_ops.posthog_api import Sender

from tests.unit.scripts.analytics_ops.conftest import FakeReader

ALICE = "6ac74a19fa5dfaf1f5770471"
BOB = "6ac74a19fa5dfaf1f5770472"


def _row(
    user_id: str, status: str, *, updated: int = 1, amount: int = 2000, **extra: object
) -> dict[str, object]:
    return {
        "dodo_subscription_id": f"sub_{user_id}_{updated}",
        "user_id": user_id,
        "status": status,
        "recurring_pre_tax_amount": amount,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, updated, tzinfo=UTC),
        **extra,
    }


class TestProjection:
    @pytest.mark.parametrize(
        ("status", "plan", "subscribed"),
        [
            ("active", "pro", True),
            ("cancelled", "free", False),
            ("on_hold", "free", False),
            ("failed", "free", False),
            ("expired", "free", False),
        ],
    )
    def test_each_status_maps_to_its_plan_and_subscribed_flag(
        self, status: str, plan: str, subscribed: bool
    ) -> None:
        [state] = latest_states([_row(ALICE, status)])

        assert state.properties == {
            "plan": plan,
            "is_subscribed": subscribed,
            "subscription_status": status,
            "subscription_cancel_at_period_end": False,
        }

    def test_a_zero_dollar_discount_code_subscriber_is_subscribed(self) -> None:
        [state] = latest_states([_row(ALICE, "active", amount=0)])

        assert (state.properties["is_subscribed"], state.properties["plan"]) == (True, "pro")

    def test_a_scheduled_cancel_keeps_pro_and_says_so(self) -> None:
        [state] = latest_states([_row(ALICE, "active", cancel_at_next_billing_date=True)])

        assert state.properties["is_subscribed"] is True
        assert state.properties["subscription_cancel_at_period_end"] is True

    def test_the_newest_row_per_user_wins_whatever_order_mongo_returns(self) -> None:
        rows = [_row(ALICE, "active", updated=5), _row(ALICE, "expired", updated=2)]

        [state] = latest_states(rows)

        assert state.properties["subscription_status"] == "active"

    def test_an_active_row_wins_over_an_older_subscription_that_lapsed_later(self) -> None:
        """The app reads the newest active row; a replaced subscription expiring after must not demote the user."""
        replacement = _row(ALICE, "active", updated=3, created_at=datetime(2026, 1, 3, tzinfo=UTC))
        replaced = _row(ALICE, "expired", updated=9)

        [state] = latest_states([replacement, replaced])

        assert (state.properties["subscription_status"], state.properties["is_subscribed"]) == (
            "active",
            True,
        )

    def test_with_no_active_row_the_newest_lapsed_row_wins(self) -> None:
        rows = [_row(ALICE, "cancelled", updated=4), _row(ALICE, "expired", updated=7)]

        [state] = latest_states(rows)

        assert state.properties["subscription_status"] == "expired"

    def test_a_row_owned_by_a_non_user_id_stops_the_run(self) -> None:
        with pytest.raises(SystemExit, match="system"):
            latest_states([_row("system", "active")])


class TestResend:
    def test_only_persons_whose_values_differ_are_resent(self) -> None:
        states = latest_states([_row(ALICE, "active"), _row(BOB, "expired")])
        reader = FakeReader(
            {
                PERSON_STATE_HOGQL: [
                    [ALICE, "pro", "true", "active", "false"],
                    [BOB, "pro", "true", "active", "None"],
                ]
            }
        )

        assert [s.user_id.distinct_id for s in stale_states(reader, states)] == [BOB]

    def test_a_person_posthog_has_never_seen_is_sent(self) -> None:
        states = latest_states([_row(ALICE, "active")])

        assert stale_states(FakeReader({PERSON_STATE_HOGQL: []}), states) == states

    def test_apply_sets_the_projection_on_the_mongo_id(
        self, recording_sender: Sender, sent: list[dict[str, object]]
    ) -> None:
        states = latest_states([_row(ALICE, "active", amount=0)])

        apply(recording_sender, states)

        [message] = sent
        assert (message["event"], message["distinct_id"]) == ("$set", ALICE)
        assert message["$set"] == states[0].properties
