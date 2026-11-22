"""The pieces an app-event subscription is built from: its trigger config, its error and the accounts a change reaches."""

from collections.abc import Mapping
from dataclasses import dataclass

from app.models.trigger_subscription_models import TriggerSubscription
from app.models.workflow_models import TriggerConfig, TriggerType

DEFAULT_COOLDOWN_SECONDS = 900


class SubscriptionError(Exception):
    """A subscription could not be registered, with a message the agent can act on."""


def build_trigger_config(
    trigger_name: str, trigger_data: Mapping[str, object] | None
) -> TriggerConfig:
    """Build the TriggerConfig a handler expects, for a task's subscription rather than a workflow.

    trigger_data carries the registration-time knobs the payload cannot express
    (a calendar's minutes_before_start, a Slack channel id). The discriminated
    union keys on trigger_name, so it is stamped into both halves.
    """
    return TriggerConfig.model_validate(
        {
            "type": TriggerType.INTEGRATION.value,
            "trigger_name": trigger_name,
            "trigger_data": {**(trigger_data or {}), "trigger_name": trigger_name},
        }
    )


@dataclass(frozen=True)
class AccountScope:
    """The subscriptions one account's change reaches.

    Those limited to that account, and, when the change holds for the whole
    integration, those watching every account.
    """

    account_id: str | None
    every_account: bool

    def covers(self, subscription: TriggerSubscription) -> bool:
        """Whether this change reaches the subscription."""
        if subscription.account_id is None:
            return self.every_account
        return subscription.account_id == self.account_id
