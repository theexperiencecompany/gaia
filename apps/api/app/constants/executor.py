"""Background executor constants.

Shared key names and internal markers used by the background executor run and
its handoff to the comms agent. Centralized so the executor runner, capture,
and any future consumers reference a single source of truth.
"""

# SSE frame key carrying the executor's narrated answer for voice-mode TTS.
# Must match VOICE_TTS_KEY in apps/voice-agent/src/constants.py — the voice
# agent matches on this exact string to decide what to speak.
VOICE_TTS_KEY = "voice_tts"
# SSE frame key carrying the saved bot message's id alongside the voice answer.
# Must match MESSAGE_ID_KEY in apps/voice-agent/src/constants.py.
MESSAGE_ID_KEY = "message_id"

# User-facing error text when the executor exhausts its recursion budget
# (GraphRecursionError). Handed to comms as the error result so it's re-voiced in
# GAIA's persona instead of leaking the raw LangGraph traceback string.
EXECUTOR_STEP_LIMIT_MESSAGE = "This task hit its step limit. Try breaking it into smaller pieces."

# User-facing text when a run crashed outright. Said plainly, because part of the
# work may already have happened: a re-run is the caller's call, never GAIA's.
EXECUTOR_CRASH_MESSAGE = (
    "The background task stopped before it finished, so there is no result and part "
    "of the work may have already happened. Tell the user plainly that it could not "
    "be completed, and ask how they would like to proceed. Never offer to re-run it "
    "yourself, and never claim a result."
)

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

# User-facing text when comms narration of a finished run is unavailable. The
# executor's own terminal text is never substituted: it is internal monologue,
# and on the error path can be a raw exception string.
EXECUTOR_NARRATION_FAILED_MESSAGE = (
    "I finished that task, but I couldn't write up the result. Please ask me again."
)
EXECUTOR_NARRATION_FAILED_ERROR_MESSAGE = (
    "That task didn't finish, and I couldn't write up what went wrong. Please try again."
)

# Seed task for a run started for inbox work no live run will absorb (late work, a
# subagent landing on a rested executor). The entries arrive through the drain hook;
# this only has to get the run to its first model call.
EXECUTOR_CARRY_TASK = (
    "New work arrived in this conversation after your previous turn ended. Read it and act on it."
)


# Stamped onto an injected inbox message so a later drain pass recognises it as
# already committed to the thread — the drain's whole basis of idempotency: the
# thread is the record of what was delivered, so no cursor is kept in sync.
INBOX_ENTRY_ID = "inbox_entry_id"

# What a stopped run tells the run that follows it. Carries no instruction of its
# own, which is why it never counts as work (see ``ExecutorInbox.announce_interruption``).
INTERRUPTION_NOTICE = (
    "The task you were working on was INTERRUPTED by the user. Do not "
    "resume it, retry it, or finish what it left half-done unless the "
    "user asks for it again."
)
