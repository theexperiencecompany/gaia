# Unit Tests — Workers

Tests for the ARQ background task functions (`app/workers/tasks/`). These workers run outside the HTTP request cycle on a separate Redis-backed queue.

The focus is on the task's decision logic: which users or records are selected for processing, what jobs are enqueued, how partial failures are handled, and what the summary string returned to the job scheduler looks like. Database collections and the Redis pool are mocked so tests run without any infrastructure.

Where tests inspect the raw MongoDB query dict passed to `find()` or `update_one()`, they verify the actual query structure — not just that the method was called.
