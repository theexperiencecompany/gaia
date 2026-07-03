"""
General Constants.

Centralized general-purpose constants.
"""

ORCHESTRATOR_MAX_ITERATIONS = 10
NEW_MESSAGE_BREAKER = "<NEW_MESSAGE_BREAK>"

# Name of the explicit "this is my final answer" tool subagents call to
# return a result to their parent. Routing logic in the bigtool override
# and the subagent runner both key off this — keep them in sync via this
# single constant.
FINISH_TASK_NAME = "finish_task"

# Comms tool that hands the turn off to the background executor. The
# user-visible answer arrives later as a separate message, so follow-ups are
# generated in the executor path rather than the current turn.
CALL_EXECUTOR_NAME = "call_executor"

MAX_EMAILS_PER_PLATFORM = 20
DEDUPLICATION_SIMILARITY_THRESHOLD = 0.9

# --- LangGraph checkpoint retention -----------------------------------------
# The DeltaChannel-backed state key (see app/override/langgraph_bigtool/utils.py).
# Its persistence is what makes checkpoint pruning non-trivial: most checkpoints
# store only a per-step delta, with a full snapshot every MESSAGES_SNAPSHOT_FREQUENCY
# updates, so reconstruction of the head walks the parent chain back to the
# nearest snapshot. Pruning must never sever that chain.
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
