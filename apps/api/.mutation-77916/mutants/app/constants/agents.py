"""Internal agent routing markers.

These bracketed tags prefix the payloads passed between the comms and executor
agents (e.g. the executor's result handed to comms for re-voicing). They are
context for the agents ONLY and must never surface to the user. Centralized here
so the strings have one source of truth — used both where the markers are
constructed and where they are stripped from user-facing text.
"""

EXECUTOR_RESULT_MARKER = "[EXECUTOR_RESULT]"
EXECUTOR_ERROR_MARKER = "[EXECUTOR_ERROR]"
EXECUTOR_CANCELLED_MARKER = "[EXECUTOR_CANCELLED]"
RETURNED_TO_FRONTEND_MARKER = "[RETURNED_TO_FRONTEND]"
PLATFORM_DELIVERY_MARKER = "[PLATFORM_DELIVERY]"

# Every internal marker that could be parroted into a user-facing reply by a weak
# model. Stripped deterministically before delivery (see strip_internal_agent_markers).
INTERNAL_AGENT_MARKERS = (
    EXECUTOR_RESULT_MARKER,
    EXECUTOR_ERROR_MARKER,
    EXECUTOR_CANCELLED_MARKER,
    RETURNED_TO_FRONTEND_MARKER,
    PLATFORM_DELIVERY_MARKER,
)
