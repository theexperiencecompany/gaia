---
name: logging-best-practices
description: GAIA's wide-event logging - how to instrument code with log.set/set_ns/audit, wide_task boundaries, and the traps that silently lose context
metadata:
  version: "2.0.0"
---

# GAIA Logging Best Practices

GAIA already ships a complete wide-event (canonical log line) system — **do not
build one**. The middleware and task boundaries own the event lifecycle; your
only job in application code is to attach context to the event that will be
emitted for you. This skill documents the API and, more importantly, the traps.

The philosophy (one context-rich event per unit of work; high cardinality; high
dimensionality; business context on every event — loggingsucks.com, Stripe's
canonical log lines) is implemented as infrastructure:

| Unit of work | Who emits the event | Emitted line |
|---|---|---|
| HTTP request | `LoggingMiddleware` (`apps/api/app/api/v1/middleware/logging.py`) | `http_request` |
| ARQ worker task | `wide_task("task_name", ...)` context manager | `worker_task` |
| Background asyncio work | `log_context("operation", ...)` context manager | `background_task` |
| Bot interaction (TypeScript) | `withWideEvent(...)` (`libs/shared/ts/src/bots/utils/wide-events.ts`) | `bot_event` |

The rest of this skill covers the Python facade; the bots use the TS analogue
(`wideLog.set`/`setNs`/`warning`/`error`/`audit`) with the same semantics and
its own scanner, `scripts/ci/checks.mjs evlog-map-bots`.

`trace_id`, `task`, `duration_ms`, `outcome` and `final_level` are stamped by
the boundary; `env`/`service`/`commit` by the JSON sink, on every line. The
middleware also attaches `user.id`/`user.email` from the authenticated request.

Setting any of those keys yourself does not work and is not silent: the sink
re-emits a colliding field as `ctx_<key>`, and the `wide-events-logging` lint
rejects it at commit time.

## The API (`from shared.py.wide_events import log`)

```python
# Attach context — this is 90% of what you should write:
log.set(user={"id": user_id}, todo={"operation": "create"})   # merge top-level keys
log.set_ns("todo", id=result_id)      # merge INTO a namespace by name (see trap 2)

# Record problems — these land on the event AND emit a real-time line:
log.warning("rate limited", provider="google", retry_in_s=30)  # -> warnings[]
log.error("sync failed", error_type=type(e).__name__, error=str(e),  # -> errors[]
          account_id=aid)   # error_type + error is THE exception vocabulary,
                            # identical on the TypeScript bots (contract.json)

# Audit trail for sensitive ACTIONS (auth, payments, PII writes) — required
# by the evlog-map `audit` check on money/auth routes:
log.audit("subscription cancelled", actor=user_id, resource=sub_id)  # -> audit[]

# Real-time narration only — NEVER reaches the wide event (trap 1):
log.info(f"{LogTag.SANDBOX} mounted")

# Domain errors that explain themselves:
raise create_error(message="Payment failed", why="card declined",
                   fix="try another card", status_code=402)
```

Use the canonical namespaces from `WideEventFields`
(`libs/shared/py/wide_events.py`) — `user`, `chat`, `todo`, `payment`,
`memory`, `device`, … — so dashboards and LogQL queries work uniformly. Don't
invent top-level keys when a namespace fits; if a new domain genuinely needs
one, add a TypedDict to the schema (the evlog-map `context` check reads it
live).

## The five traps (each has burned someone)

1. **`log.info()` never reaches the wide event.** It is real-time narration
   only. If a fact matters for debugging later, it belongs in `log.set()`.
   Narrating steps with `log.info` instead of accumulating fields is the #1
   anti-pattern in this codebase (flagged by evlog-map as `info-noise`).
2. **Namespaces accumulate — `set` and `set_ns` are the same operation.** A
   second `log.set(todo={...})` merges into the first rather than replacing it,
   so every layer of a request adds to one namespace. `log.set_ns("todo",
   key=value)` is the same write with the namespace named explicitly; prefer it
   on multi-step paths because it reads as "add to", not "assign". The merge is
   one level deep and dict-into-dict only — a scalar still overwrites.
3. **No boundary, no event.** Code outside an HTTP request (ARQ tasks,
   `asyncio.create_task` work, post-OAuth callbacks) has no middleware; without
   a boundary every `log.set()` is silently discarded. ARQ tasks wrap in
   `wide_task()`; fire-and-forget work is spawned with
   `spawn_logged_task("operation", coro(...))` (never bare
   `asyncio.create_task`) — it opens a `log_context()` carrying the spawning
   request's `trace_id` and keeps the task GC-safe.
4. **Structured data goes in kwargs, never interpolated into the message.**
   `log.error(f"failed: {e}")` is unqueryable prose (and if kwargs are also
   passed, braces in `str(e)` can break loguru's formatting). The one
   sanctioned f-string is the `LogTag` message prefix for greppability.
5. **`log.bind()` is not loguru's `bind()`.** It merges into the wide event; it
   does NOT tag subsequent real-time lines (so `bind(performance=True)` cannot
   route to the performance sink).

## The mechanical contract

- Route handlers: `log.set()` what you know at entry (user, operation, ids) →
  delegate to the service → `log.set_ns()` result ids/counts. Enforced by the
  `route-contract` lint; scored by `python3 tools/evlog_map` (CI `observability`
  lane fails PRs that regress a file's score).
- Every `except` must log (`log.error`/`log.warning` with `error_type=`),
  re-raise, or return an error response — never swallow silently. Genuinely
  intentional swallows carry an `# evlog-map-disable-next-line error-handling
  -- <reason>` directive so the decision is visible.
- Only the `log` facade in `app/` — stdlib `logging` and bare `loguru` are
  banned by the `wide-events-logging` lint. The one deliberate exception is
  `app/config/sentry.py`, which is allowlisted so it can install the Loguru →
  Sentry sink directly; nowhere else may touch Loguru/logging.

## Querying what you logged

See `docs/developers/logging.mdx` (LogQL primer + recipes) and the
`reading-gaia-logs` skill. The one-liner: labels select the stream
(`{service="gaia-backend"}`), everything else is `| json | field = "value"`.

**The arrays are the exception.** `errors[]` / `warnings[]` / `audit[]` are
absent (not empty) when nothing was recorded, and bare `| json` **drops arrays
entirely** — so `| errors != "[]"` matches every line, including clean 200s.
Use an explicit JSON expression:

```logql
{service="gaia-backend"} | json | message="http_request"
  | json first_error="errors[0].msg" | first_error != ""
```

For "show me failed requests" prefer `| final_level =~ "ERROR|CRITICAL"` — it
folds in the HTTP status, so it also catches a 5xx that logged nothing.
