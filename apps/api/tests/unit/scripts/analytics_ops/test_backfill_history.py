"""Historical signups and activations: the record decides uuid and timestamp, so a re-run is the same rows."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from bson import ObjectId
import pytest
from scripts.analytics_ops import backfill_history
from scripts.analytics_ops.backfill_history import (
    Backfill,
    activation,
    apply,
    signup,
    untracked_activations,
)
from scripts.analytics_ops.posthog_api import Sender

from app.models.payment_models import SubscriptionDocument
from tests.unit.scripts.analytics_ops.conftest import FakeReader

ALICE = "6ac74a19fa5dfaf1f5770471"
CREATED = datetime(2025, 11, 3, 9, 30, tzinfo=UTC)


def _user(user_id: str = ALICE, created: datetime = CREATED) -> dict[str, object]:
    return {"_id": ObjectId(user_id), "created_at": created}


def _subscription(**overrides: object) -> SubscriptionDocument:
    return SubscriptionDocument.model_validate(
        {
            "dodo_subscription_id": "sub_1",
            "user_id": ALICE,
            "status": "active",
            "currency": "USD",
            "recurring_pre_tax_amount": 2000,
            "created_at": CREATED,
            **overrides,
        }
    )


def _send(
    sender: Sender, sent: list[dict[str, object]], backfills: list[Backfill]
) -> list[dict[str, object]]:
    start = len(sent)
    apply(sender, backfills)
    return sent[start:]


class TestDeterminism:
    def test_a_rerun_sends_byte_identical_signups_and_activations(
        self, recording_sender: Sender, sent: list[dict[str, object]]
    ) -> None:
        first = _send(recording_sender, sent, [signup(_user()), activation(_subscription())])
        rerun = _send(recording_sender, sent, [signup(_user()), activation(_subscription())])

        for a, b in zip(first, rerun, strict=True):
            assert (a["uuid"], a["timestamp"], a["event"], a["distinct_id"]) == (
                b["uuid"],
                b["timestamp"],
                b["event"],
                b["distinct_id"],
            )
            assert a["properties"] == b["properties"]

    def test_the_timestamp_is_the_records_created_at(
        self, recording_sender: Sender, sent: list[dict[str, object]]
    ) -> None:
        [message] = _send(recording_sender, sent, [signup(_user())])

        assert datetime.fromisoformat(str(message["timestamp"])) == CREATED
        assert UUID(str(message["uuid"])).version == 5

    def test_the_uuid_follows_the_record_id(self) -> None:
        one = signup(_user(ALICE))
        other = signup(_user("6ac74a19fa5dfaf1f5770472"))

        assert one.dedupe.key != other.dedupe.key

    def test_posthog_is_told_to_keep_the_records_time(
        self, recording_sender: Sender, sent: list[dict[str, object]]
    ) -> None:
        [message] = _send(recording_sender, sent, [activation(_subscription())])

        assert message["properties"]["$ignore_sent_at"] is True


class TestPayload:
    def test_a_backfilled_signup_is_marked_and_sets_no_person_properties(
        self, recording_sender: Sender, sent: list[dict[str, object]]
    ) -> None:
        [message] = _send(recording_sender, sent, [signup(_user())])

        assert (message["event"], message["distinct_id"]) == ("user:signed_up", ALICE)
        assert message["properties"]["backfilled"] is True
        assert "$set" not in message["properties"]
        assert "$set_once" not in message["properties"]

    def test_a_backfill_is_attributed_to_the_user_and_a_system_trigger(
        self, recording_sender: Sender, sent: list[dict[str, object]]
    ) -> None:
        [message] = _send(recording_sender, sent, [signup(_user())])

        props = message["properties"]
        assert (props["actor"], props["trigger"], props["surface"]) == ("user", "system", "worker")

    def test_an_activation_carries_the_subscription_and_its_amount(
        self, recording_sender: Sender, sent: list[dict[str, object]]
    ) -> None:
        [message] = _send(recording_sender, sent, [activation(_subscription())])

        props = message["properties"]
        assert (message["event"], props["subscription_id"], props["amount"], props["currency"]) == (
            "subscription:activated",
            "sub_1",
            20.0,
            "USD",
        )

    def test_a_subscription_with_no_creation_time_cannot_be_backfilled(self) -> None:
        with pytest.raises(ValueError, match="created_at"):
            activation(_subscription(created_at=None))


class TestOwnerFallbackIsPerSubscription:
    """An activation found only on the owner's person proves one subscription, not every one."""

    def test_a_lone_untracked_subscription_of_a_tracked_owner_is_skipped(self) -> None:
        rows = [_subscription(dodo_subscription_id="sub_1")]

        assert untracked_activations(rows, tracked_ids=set(), owners_tracked={ALICE}) == ([], [])

    def test_two_untracked_subscriptions_of_a_tracked_owner_go_to_review(self) -> None:
        rows = [
            _subscription(dodo_subscription_id="sub_1"),
            _subscription(dodo_subscription_id="sub_2"),
        ]

        backfill, review = untracked_activations(rows, tracked_ids=set(), owners_tracked={ALICE})

        assert backfill == []
        assert review == [
            f"user {ALICE}: 2 subscriptions have no activation by id and one is on the person; "
            "which one it reports is unknown (sub_1, sub_2)"
        ]

    def test_a_subscription_tracked_by_id_never_counts_against_its_sibling(self) -> None:
        rows = [
            _subscription(dodo_subscription_id="sub_1"),
            _subscription(dodo_subscription_id="sub_2"),
        ]

        assert untracked_activations(rows, tracked_ids={"sub_1"}, owners_tracked={ALICE}) == (
            [],
            [],
        )

    def test_an_untracked_owner_backfills_every_subscription(self) -> None:
        rows = [
            _subscription(dodo_subscription_id="sub_1"),
            _subscription(dodo_subscription_id="sub_2"),
        ]

        backfill, review = untracked_activations(rows, tracked_ids=set(), owners_tracked=set())

        assert ([row.dodo_subscription_id for row in backfill], review) == (["sub_1", "sub_2"], [])


class _Collection:
    def __init__(self, docs: list[dict[str, object]]) -> None:
        self.docs = docs

    def find(self, _query: object) -> list[dict[str, object]]:
        return self.docs

    def find_one(self, _query: object, sort: object = None) -> dict[str, object] | None:
        return min(self.docs, key=lambda doc: str(doc["created_at"]), default=None)


class _Db:
    def __init__(self, subscriptions: list[dict[str, object]]) -> None:
        self.subscriptions = _Collection(subscriptions)

    def __getitem__(self, name: str) -> _Collection:
        return getattr(self, name)


@pytest.mark.regression
def test_an_owners_activation_already_matched_by_id_does_not_cover_an_older_subscription() -> None:
    """The owner fallback counted sub_1's own activation as proof for sub_2, so sub_2 was never sent."""
    activations_on_alice = [(ALICE, "sub_1")]
    db = _Db(
        [
            _subscription(dodo_subscription_id="sub_1").model_dump(),
            _subscription(dodo_subscription_id="sub_2").model_dump(),
        ]
    )
    reader = FakeReader(
        {
            backfill_history.TRACKED_SUBSCRIPTIONS_HOGQL: [["sub_1"]],
            backfill_history.USERS_WITH_UNMATCHED_ACTIVATION_HOGQL: lambda values: [
                [owner]
                for owner, subscription_id in activations_on_alice
                if owner in values["ids"] and subscription_id not in values["known"]
            ],
        }
    )

    planned, review = backfill_history.plan_activations(reader, db)

    assert [backfill.event.subscription_id for backfill in planned] == ["sub_2"]
    assert review == []


def test_a_held_user_is_left_out_of_both_backfills() -> None:
    bob = "6ac74a19fa5dfaf1f5770472"
    history = backfill_history.HistoryPlan(
        signups=[signup(_user()), signup(_user(bob))],
        activations=[activation(_subscription()), activation(_subscription(user_id=bob))],
        unbuildable=[],
    )

    kept = history.holding_out({ALICE})

    assert [b.user_id.distinct_id for b in kept.signups + kept.activations] == [bob, bob]
