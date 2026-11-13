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
#: The same job handed back to the queue to be judged once its user's other reports have arrived.
OUTBOX_BATCHED_JOB_ID_SUFFIX: Final = ":batched"

#: An outbox job (intake or flush) is tried this many times, each retry twice as late as the last.
OUTBOX_TASK_MAX_TRIES: Final = 5
OUTBOX_TASK_RETRY_DELAY_SECONDS: Final = 15
#: A message the chat apps' queue refused this many times is told in the app instead.
OUTBOX_TRANSPORT_MAX_RETRIES: Final = 3
OUTBOX_TRANSPORT_RETRY_DELAY_SECONDS: Final = 30

#: The per-user lock that spares a second flusher a compose the first is already doing.
#: Only an optimisation: the compare-and-set on the items keeps a message single.
OUTBOX_USER_LOCK_PREFIX: Final = "outbox:user:"
OUTBOX_USER_LOCK_LEASE_SECONDS: Final = 60.0
OUTBOX_USER_LOCK_RENEW_SECONDS: Final = 20.0
OUTBOX_USER_LOCK_ACQUIRE_TIMEOUT_SECONDS: Final = 2.0
OUTBOX_USER_LOCK_MAX_HOLD_SECONDS: Final = 300.0

#: An unsent item untouched for this long was dropped by a job that died; the recovery sweep drives it again.
OUTBOX_RECOVERY_AFTER_SECONDS: Final = 10 * 60
#: The sweep drives one item this many times, then fails it loudly instead of looping forever.
OUTBOX_RECOVERY_MAX_ATTEMPTS: Final = 5
#: Items one sweep takes up, so a backlog is worked off over several sweeps.
OUTBOX_RECOVERY_BATCH: Final = 100

#: The intake job a recovery attempt enqueues is the report's own job id plus this and the attempt number.
OUTBOX_RECOVERY_JOB_ID_SUFFIX: Final = ":recover"

#: Compose asks the model again once when its answer drops an item that must be said.
COMPOSE_MAX_ATTEMPTS: Final = 2

#: Messages of the destination thread, and of the outbox's own earlier sends, compose reads.
COMPOSE_THREAD_SNAPSHOT_MESSAGES: Final = 12
COMPOSE_LEDGER_MESSAGES: Final = 5

#: The locale the prerendered copy falls back to when it has none for the user's.
DEFAULT_LOCALE: Final = "en"

#: A user who wrote on a surface this recently is watching it live; progress older than that is not worth a ping.
LIVE_WATCH_WINDOW_SECONDS: Final = 5 * 60

#: What the compose model call is named in traces and metering.
OUTBOX_COMPOSE_LABEL: Final = "outbox_compose"

#: A report's id names the fact: its producer, the thing it is about, and the run that made it.
ASK_REPORT_PREFIX: Final = "ask:"
WORKFLOW_REPORT_PREFIX: Final = "wf:"
TODO_REPORT_PREFIX: Final = "todo:"
APPROVAL_REPORT_PREFIX: Final = "hil:"
APPROVAL_SUBJECT_PREFIX: Final = "approval:"
#: System notices are named by what happened and its natural key: sys:{kind}:{key}.
SYSTEM_REPORT_PREFIX: Final = "sys:"

#: What a subject is called to the user when the producer has no name for it: an ask is the request.
ASK_LABEL_FALLBACK: Final = "Your request"
WORKFLOW_LABEL_FALLBACK: Final = "Your workflow"
SUBJECT_LABEL_MAX_CHARS: Final = 120

#: Earlier occurrences of one producer that compose is told what GAIA did with, and how much of each message.
COMPOSE_EARLIER_RUNS: Final = 3
COMPOSE_EARLIER_RUN_CHARS: Final = 200
