"""What the delegation runner tells the executor about a subagent it started.

Tool results and inbox entries, read by the executor model and never shown to the
user as-is. Used by spawn_subagent's runner.
"""

BACKGROUND_DELEGATION_ACK = (
    "{name} started in the background as subagent {subagent_id}. Keep working: its "
    "result arrives in your inbox on its own, and wakes you if you have already "
    'finished. Steer it with message_subagent(subagent_id="{subagent_id}", ...) or '
    'stop it with cancel_subagent(subagent_id="{subagent_id}").'
)

STOPPED_BEFORE_START = (
    "{name} was not started: the user stopped this task. Do not start it again unless they ask."
)

THREAD_BUSY_REFUSAL = (
    "{name} is already running on this integration, and a second run would corrupt "
    "its thread. Find it with list_running_subagents, then steer it with "
    "message_subagent, stop it with cancel_subagent, or wait for its result to arrive."
)

#: One inbox entry per landing; the entry carries no attribution of its own.
SUBAGENT_RESULT_ENTRY = "{name} (subagent {subagent_id}): {result}"

SUBAGENT_FAILED_RESULT = "Error from {name}: {error}"

SUBAGENT_NARRATION_ONLY_RESULT = (
    "The {name} subagent ended without running any tool; it only produced planning text: "
    '"{text}". Re-issue the task with an explicit instruction to perform the action.'
)
