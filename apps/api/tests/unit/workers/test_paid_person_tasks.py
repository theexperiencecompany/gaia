"""The durable retry behind a billing change's paid-state person properties."""

from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from arq import Retry
from pymongo.errors import PyMongoError
import pytest

from app.constants.log_tags import LogTag
from app.constants.payments import PAID_PERSON_SYNC_RETRY_DELAY
from app.models.payment_models import SubscriptionDocument
from app.workers.tasks.paid_person_tasks import sync_paid_person_properties_task

EVENTS = "app.services.payments.subscription_events"
TASK = "app.workers.tasks.paid_person_tasks"
USER_ID = "507f1f77bcf86cd799439011"
SUB_ID = "sub_1"


def _row(status: str) -> SubscriptionDocument:
    return SubscriptionDocument.model_validate(
        {
            "id": "64b64b64b64b64b64b64b64b",
            "dodo_subscription_id": SUB_ID,
            "user_id": USER_ID,
            "product_id": "prod_1",
            "status": status,
            "quantity": 1,
            "cancel_at_next_billing_date": True,
        }
    )


@pytest.fixture(autouse=True)
def _no_other_active_subscription() -> Iterator[None]:
    with patch(
        f"{EVENTS}.subscription_repository.get_active_for_user",
        new_callable=AsyncMock,
        return_value=None,
    ):
        yield


@pytest.mark.unit
class TestSyncPaidPersonPropertiesTask:
    async def test_it_sets_the_paid_state_the_row_holds_now(self) -> None:
        client = MagicMock()
        with (
            patch(
                f"{EVENTS}.subscription_repository.get_by_dodo_id",
                new_callable=AsyncMock,
                return_value=_row("on_hold"),
            ) as get_by_dodo_id,
            patch("app.services.analytics_service._get_posthog_client", return_value=client),
            patch(f"{TASK}.log") as log,
        ):
            await sync_paid_person_properties_task({}, USER_ID, SUB_ID)

        get_by_dodo_id.assert_awaited_once_with(SUB_ID)
        log.set.assert_called_once_with(
            user={"id": USER_ID}, paid_person_sync={"subscription_id": SUB_ID}
        )
        client.set.assert_called_once_with(
            distinct_id=USER_ID,
            properties={
                "plan": "free",
                "is_subscribed": False,
                "subscription_status": "on_hold",
                "subscription_cancel_at_period_end": True,
            },
        )

    @pytest.mark.parametrize(("ctx", "factor"), [({}, 1), ({"job_try": 1}, 1), ({"job_try": 3}, 4)])
    async def test_an_unreadable_row_asks_arq_for_a_backed_off_retry(
        self, ctx: dict[str, int], factor: int
    ) -> None:
        defer = PAID_PERSON_SYNC_RETRY_DELAY * factor
        with (
            patch(
                f"{EVENTS}.subscription_repository.get_by_dodo_id",
                new_callable=AsyncMock,
                side_effect=PyMongoError("down"),
            ),
            patch(f"{TASK}.log") as log,
            pytest.raises(Retry) as retry,
        ):
            await sync_paid_person_properties_task(ctx, USER_ID, SUB_ID)

        assert retry.value.defer_score == defer / timedelta(milliseconds=1)
        log.warning.assert_called_once_with(
            f"{LogTag.PAYMENT} Paid person properties sync could not read the row; retrying",
            error_type="PyMongoError",
            defer_seconds=defer.total_seconds(),
        )

    async def test_a_row_gone_for_good_is_not_retried(self) -> None:
        client = MagicMock()
        with (
            patch(
                f"{EVENTS}.subscription_repository.get_by_dodo_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.services.analytics_service._get_posthog_client", return_value=client),
        ):
            await sync_paid_person_properties_task({}, USER_ID, SUB_ID)

        client.set.assert_not_called()
