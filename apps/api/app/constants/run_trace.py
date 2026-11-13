"""Run-trace constants: retention, liveness, and the bounds on what one call may store."""

from typing import Final

from app.constants.cache import ONE_DAY_TTL

#: Executor run traces (runs, calls, payloads) are dropped by a TTL index this long after creation.
RUN_TRACE_RETENTION_SECONDS: Final = 30 * ONE_DAY_TTL

#: A run still "running" with no call or heartbeat for this long, and no live busy lock, is abandoned.
RUN_ABANDONED_AFTER_SECONDS: Final = 2 * 60 * 60

#: How many stale runs one reaper sweep closes; the next sweep takes the rest.
RUN_REAP_BATCH_LIMIT: Final = 200

#: Minutes between reaper sweeps (an ARQ cron).
RUN_REAP_EVERY_MINUTES: Final = 5

#: Longest the one-line summary of a call may be (it lands in a todo's activity log).
CALL_SUMMARY_MAX_CHARS: Final = 120

#: Longest a stored call input or output may be; past it the text is cut and flagged truncated.
CALL_PAYLOAD_MAX_CHARS: Final = 200_000

#: Most calls or runs one read returns.
RUN_TRACE_LIST_MAX_LIMIT: Final = 500
RUN_TRACE_LIST_DEFAULT_LIMIT: Final = 100

#: Mongo collections of the run trace.
RUNS_COLLECTION: Final = "executor_runs"
RUN_CALLS_COLLECTION: Final = "executor_run_calls"
CALL_PAYLOADS_COLLECTION: Final = "executor_call_payloads"

#: What one read of the record by comms returns: runs listed, calls per run, and characters of one call's input or output.
WORK_RECORD_RUNS: Final = 3
WORK_RECORD_CALLS_PER_RUN: Final = 30
WORK_RECORD_DETAIL_CHARS: Final = 8_000
#: Runs searched for a call comms names; bounds the lookup of one call by its id.
WORK_RECORD_SEARCH_RUNS: Final = 20
