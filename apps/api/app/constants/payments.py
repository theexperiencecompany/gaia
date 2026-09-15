"""Payment and billing constants."""

from datetime import timedelta
from enum import StrEnum

# How many charges a payment-history read returns. Deep history belongs in the
# billing portal; the agent only ever needs "what have I been charged lately".
PAYMENT_HISTORY_LIMIT = 10

# How many recent checkout sessions payment verification asks Dodo about. It
# scans, not just the newest, because every paywall block mints a fresh session
# so the paid one is often buried under later ones; the scan stops at the first paid session.
CHECKOUT_SESSION_SCAN_LIMIT = 10

# How long a lifecycle webhook for a subscription GAIA has no row for is still
# retried; subscription.active is a separate delivery that may just be behind.
# Past this age it is not coming, and redelivery only masks that.
WEBHOOK_ROW_WAIT_MAX = timedelta(hours=1)


class SubscriptionWorkflowSync(StrEnum):
    """Which way a billing change moves the user's workflows.

    Here rather than beside the two service functions it selects between: the
    webhook reducer names a direction when it queues the retry, and importing it
    from the workflow stack would recreate the cycle that stack is already
    deferred around.
    """

    PAUSE = "pause"
    RESUME = "resume"


#: The ARQ task that reapplies a billing change's workflow pause/resume when the
#: webhook's own attempt could not finish it. Named here because the enqueue site
#: and the worker registration have to agree and nothing else enforces that.
SUBSCRIPTION_WORKFLOW_SYNC_TASK = "sync_workflows_for_subscription_state"

#: Delay before the first retry of that task; each further try doubles it. Long
#: enough for a Composio or Mongo blip to clear, short enough that a lapsed
#: user's automation stops within minutes rather than hours.
SUBSCRIPTION_WORKFLOW_SYNC_RETRY_DELAY = timedelta(minutes=2)

NO_USER_MESSAGE = "Could not identify the user, so their billing state is unavailable."

#: Everything a checkout opened outside production prefills. The country
#: matters: Dodo's test card (4242 4242 4242 4242) is a US Visa, and the
#: Indian rail (chosen by the developer's IP) declines it.
DODO_TEST_MODE_BILLING_ADDRESS: dict[str, str] = {
    "country": "US",
    "street": "548 Market St",
    "city": "San Francisco",
    "state": "CA",
    "zipcode": "94104",
}
DODO_TEST_MODE_PHONE_NUMBER = "+14155550123"
