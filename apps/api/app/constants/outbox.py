"""The outbox: the one way a message leaves GAIA for the user."""

from typing import Final

from app.constants.cache import ONE_DAY_TTL

ITEMS_COLLECTION: Final = "outbox_items"
MESSAGES_COLLECTION: Final = "outbox_messages"

#: An item, and the message it produced, expire this long after they were written.
OUTBOX_ITEM_RETENTION_SECONDS: Final = 90 * ONE_DAY_TTL
OUTBOX_MESSAGE_RETENTION_SECONDS: Final = 180 * ONE_DAY_TTL

#: The ARQ job that takes a submitted report; its job id is OUTBOX_JOB_ID_PREFIX + report_id.
OUTBOX_INTAKE_TASK: Final = "outbox_intake"
OUTBOX_JOB_ID_PREFIX: Final = "outbox:"

#: The per-user lock that spares a second flusher a compose the first is already doing.
#: Only an optimisation: the compare-and-set on the items keeps a message single.
OUTBOX_USER_LOCK_PREFIX: Final = "outbox:user:"
OUTBOX_USER_LOCK_LEASE_SECONDS: Final = 60.0
OUTBOX_USER_LOCK_RENEW_SECONDS: Final = 20.0
OUTBOX_USER_LOCK_ACQUIRE_TIMEOUT_SECONDS: Final = 2.0
OUTBOX_USER_LOCK_MAX_HOLD_SECONDS: Final = 300.0

#: Compose asks the model again once when its answer drops an item that must be said.
COMPOSE_MAX_ATTEMPTS: Final = 2

#: Messages of the destination thread, and of the outbox's own earlier sends, compose reads.
COMPOSE_THREAD_SNAPSHOT_MESSAGES: Final = 12
COMPOSE_LEDGER_MESSAGES: Final = 5

#: The locale the prerendered copy falls back to when it has none for the user's.
DEFAULT_LOCALE: Final = "en"

#: What the compose model call is named in traces and metering.
OUTBOX_COMPOSE_LABEL: Final = "outbox_compose"
