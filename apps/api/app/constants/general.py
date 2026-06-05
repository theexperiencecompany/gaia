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
PROFILE_EXTRACTION_LLM_PROVIDER = "gemini"
PROFILE_EXTRACTION_LLM_MODEL = "gemini-2.0-flash"
