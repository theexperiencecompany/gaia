"""Background executor constants.

Shared key names and internal markers used by the background executor run and
its handoff to the comms agent. Centralized so the executor runner, capture,
and any future consumers reference a single source of truth.
"""

from app.constants.hil import HIL_RESUME_CONFIG_KEY
from app.models.agent_models import AgentConfigurable

# SSE frame key carrying the executor's narrated answer for voice-mode TTS.
# Must match VOICE_TTS_KEY in apps/voice-agent/src/constants.py — the voice
# agent matches on this exact string to decide what to speak.
VOICE_TTS_KEY = "voice_tts"
# SSE frame key carrying the saved bot message's id alongside the voice answer,
# so the voice agent can forward a display frame keyed by it and the frontend
# reconciles it with the WebSocket push. Must match MESSAGE_ID_KEY in
# apps/voice-agent/src/constants.py.
MESSAGE_ID_KEY = "message_id"

# Internal markers prefixing the executor result handed to comms as context.
# Comms re-voices the payload; these markers are stripped from its reply.
EXECUTOR_RESULT_MARKER = "[EXECUTOR_RESULT]"
EXECUTOR_ERROR_MARKER = "[EXECUTOR_ERROR]"

# User-facing error text when the executor exhausts its recursion budget
# (GraphRecursionError). Handed to comms as the error result so it's re-voiced in
# GAIA's persona instead of leaking the raw LangGraph traceback string.
EXECUTOR_STEP_LIMIT_MESSAGE = "This task hit its step limit — try breaking it into smaller pieces."

# result_type for a run that stopped on a HIL approval instead of finishing. Such
# a run has nothing to deliver and KEEPS the busy lock: its thread is checkpointed
# with pending work, so no queued task may run on it until the approval resolves.
EXECUTOR_PAUSED = "paused"

# User-facing text when a run paused for approval but its resume context could not be
# recorded, so no decision could ever restart it. Handed to comms as the error result
# rather than parking the conversation behind a lock nothing will ever release.
EXECUTOR_APPROVAL_LOST_MESSAGE = (
    "I couldn't set up the approval for that action, so I've stopped. Please try again."
)

# Task text for the wake-up turn queued when background-subagent work lands after
# the executor rested (finished its turn without collecting). The queued run's
# join gathers results and pauses for any approvals; SubagentJoinMiddleware
# backstops it if the model tries to end without collecting.
EXECUTOR_COLLECTION_TASK = (
    "Background subagent work has finished or is waiting for the user's approval. "
    "Call wait_for_subagents() to collect the outcomes, then report them to the user."
)

# Dedup marker: at most one queued collection turn per conversation at a time.
# Set when a collection run is enqueued; cleared when a join actually runs. TTL
# is crash insurance so a lost run can't suppress wake-ups forever.
EXECUTOR_COLLECT_MARKER_PREFIX = "executor:collect_queued:"
EXECUTOR_COLLECT_MARKER_TTL = 600


# What survives a queue hop / HIL resume. Every GAIA-owned configurable key is
# safe to carry by construction, so AgentConfigurable IS the allowlist: the
# hand-maintained list this replaces had fallen behind it and was dropping the
# OpenRouter provider pin, plan_type, root_request_id, langfuse_trace_id and the
# HIL intent judge's user_messages — a queued run was not a smaller run, it was a
# different one. What must still be filtered is LangGraph's own runtime keys
# (checkpoint_ns, checkpoint_id, __pregel_*, Runtime objects), which are exactly
# the keys NOT declared on AgentConfigurable.
CONFIGURABLE_OWNED_KEYS: frozenset[str] = frozenset(AgentConfigurable.__annotations__)

# Owned keys that are nonetheless scoped to ONE dispatch and must not ride along
# to the next: hil_resume_replay means "this exact call is a replay", so carrying
# it would make a fresh run probe its subagent threads for interrupts it cannot have.
CONFIGURABLE_RUN_SCOPED_KEYS: frozenset[str] = frozenset({HIL_RESUME_CONFIG_KEY})
