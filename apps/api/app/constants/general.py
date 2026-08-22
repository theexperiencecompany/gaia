"""
General Constants.

Centralized general-purpose constants.
"""

import re

ORCHESTRATOR_MAX_ITERATIONS = 10
NEW_MESSAGE_BREAKER = "<NEW_MESSAGE_BREAK>"

# The model occasionally emits a near-miss spelling of the bubble-break sentinel
# (e.g. <NEW_LINE_BREAK> instead of <NEW_MESSAGE_BREAK>). Every spelling is
# treated as the canonical break so it splits bubbles; none ever ships to a
# platform as literal text. Kept beside NEW_MESSAGE_BREAKER so the sentinel
# vocabulary lives in one place.
MESSAGE_BREAK_SENTINEL_RE = re.compile(r"<\s*NEW_(?:MESSAGE|LINE)_BREAK\s*>", re.IGNORECASE)

# Upper bound for every 1-based `page` query parameter. Paginated endpoints turn
# `page` into a Mongo `skip` of `(page - 1) * page_size`; unbounded, a large
# enough `page` produces a value BSON cannot encode as an int64, and the driver
# error surfaces as a 500. int32 max is the largest bound that cannot overflow
# for any page size we accept (2^31 * 100 is still ~9 orders of magnitude below
# int64 max), so it rejects the absurd without capping legitimate paging.
MAX_PAGE_NUMBER = 2_147_483_647

# Name of the explicit "this is my final answer" tool subagents call to
# return a result to their parent. Routing logic in the bigtool override
# and the subagent runner both key off this — keep them in sync via this
# single constant.
FINISH_TASK_NAME = "finish_task"

# Comms tool that hands the turn off to the background executor. The
# user-visible answer arrives later as a separate message, so follow-ups are
# generated in the executor path rather than the current turn.
CALL_EXECUTOR_NAME = "call_executor"

# Executor-only join tool: collects background subagents and doubles as the HIL
# approval barrier. The graph builder, the join middleware and the HIL exempt
# set all key off it — keep them in sync via this single constant.
WAIT_FOR_SUBAGENTS_NAME = "wait_for_subagents"

# Agent name of a spawned subagent's graph. Lives here because the graph builder
# and the middleware that drives it must not import each other (the builder pulls
# in create_agent, which imports the middleware package).
SPAWN_AGENT_NAME = "spawned_subagent"

# Thread-id prefix for a spawn's checkpoint thread (`spawn_<conversation>_<call>`).
# Shared because the middleware mints these and the nightly retention sweep selects
# on them — a drift between the two would silently strand every spawn thread.
SPAWN_THREAD_PREFIX = "spawn_"

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

# How long a finished spawn's thread is kept before the nightly sweep reclaims it.
# It only has to outlive its parent turn's replay window, and HIL_APPROVAL_TIMEOUT_SECONDS
# caps a pause at hours — days of margin buys post-hoc inspection of what a spawn did.
CHECKPOINT_SPAWN_THREAD_RETENTION_DAYS = 7
# Upper bound on stale spawn threads swept per run.
CHECKPOINT_SPAWN_SWEEP_MAX_THREADS = 2000
