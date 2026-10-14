"""
General Constants.

Centralized general-purpose constants.
"""

ORCHESTRATOR_MAX_ITERATIONS = 10
# The canonical bubble-break sentinel the comms prompt tells the model to emit.
# Recognizing the near-miss spellings it actually emits (and splitting on them)
# is ``app.utils.message_breaks`` — this is only the token we ask for.
NEW_MESSAGE_BREAKER = "<NEW_MESSAGE_BREAK>"

# Upper bound for every 1-based `page` query parameter. Unbounded, `page`
# converted to a Mongo skip can overflow BSON's int64 and 500. int32 max is the
# largest bound that cannot overflow for any page size we accept.
MAX_PAGE_NUMBER = 2_147_483_647

# Name of the explicit "this is my final answer" tool subagents call. The
# bigtool override and the subagent runner both key off this constant.
FINISH_TASK_NAME = "finish_task"

# Comms tool that hands the turn off to the background executor. The
# user-visible answer arrives later as a separate message, so follow-ups are
# generated in the executor path rather than the current turn.
CALL_EXECUTOR_NAME = "call_executor"


# Agent name of a spawned subagent's graph. Lives here because the graph builder
# and the middleware that drives it must not import each other (the builder pulls
# in create_agent, which imports the middleware package).
SPAWN_AGENT_NAME = "spawned_subagent"

# Thread-id prefix for a spawn's checkpoint thread (`spawn_<conversation>_<call>`).
# Shared because the middleware mints these and the nightly retention sweep selects
# on them — a drift between the two would silently strand every spawn thread.
SPAWN_THREAD_PREFIX = "spawn_"

# Thread-id prefix for the executor's checkpoint thread (`executor_<conversation>`).
# Shared because prepare_executor_execution mints these and the workflow thread
# reset selects on them — a drift would replay a workflow's whole history.
EXECUTOR_THREAD_PREFIX = "executor_"
# SubagentExecutionContext.integration_id of an executor run — the one run the
# executor tier drives with the worker driver without being a delegated worker.
EXECUTOR_INTEGRATION_ID = "executor"

MAX_EMAILS_PER_PLATFORM = 20
DEDUPLICATION_SIMILARITY_THRESHOLD = 0.9

# The DeltaChannel-backed state key (app/override/langgraph_bigtool/utils.py).
# Most checkpoints store only a per-step delta with a full snapshot every
# MESSAGES_SNAPSHOT_FREQUENCY updates; pruning must never sever that parent chain.
CHECKPOINT_MESSAGES_CHANNEL = "messages"

# Blob `type` written by the Postgres saver when a channel has no value at a
# checkpoint (DeltaChannel non-snapshot steps). A real snapshot blob has a
# serializer type (e.g. "msgpack"); this sentinel means "no value stored here".
CHECKPOINT_EMPTY_BLOB_TYPE = "empty"

# Nightly version-prune caps. Threads are processed largest-first so the worst
# offenders shrink first; the rest are covered on subsequent nights.
CHECKPOINT_PRUNE_MAX_THREADS_PER_RUN = 1000
# Skip threads that cannot yield savings (a lone head has no prunable ancestors).
CHECKPOINT_PRUNE_MIN_CHECKPOINTS = 2
# Upper bound on orphan (deleted-conversation) threads swept per run.
CHECKPOINT_ORPHAN_SWEEP_MAX_THREADS = 2000

# How long a finished spawn's thread is kept before the nightly sweep reclaims it.
# It only has to outlive its parent turn's replay window, and HIL_APPROVAL_TIMEOUT_SECONDS
# caps a pause at hours — days of margin buys post-hoc inspection of what a spawn did.
CHECKPOINT_SPAWN_THREAD_RETENTION_DAYS = 7
# Upper bound on stale spawn threads swept per run.
CHECKPOINT_SPAWN_SWEEP_MAX_THREADS = 2000
