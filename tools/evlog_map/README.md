# evlog map — observability score for the Python backends

A Python port of [evlog](https://github.com/HugoRCD/evlog)'s `map` command (MIT),
with a FastAPI/ARQ adapter and a LiveKit voice adapter for this repo's
wide-event runtime (`shared.py.wide_events`). It statically answers: *if
something goes wrong in production tonight, which parts of the backend will be
able to tell you why?*

Stdlib only — no deps, runs anywhere `python3` does.

```bash
python3 tools/evlog_map                  # full scan (apps/api/app + apps/voice-agent/src)
python3 tools/evlog_map --all            # per-entry check matrix
python3 tools/evlog_map --json           # full map as JSON (the evlog.map.json contract)
python3 tools/evlog_map --min-score 70   # exit 1 when the global score is below N
python3 tools/evlog_map --min-entries 308 # exit 1 when discovery finds fewer entry points
python3 tools/evlog_map --files-from -   # scan only listed files (CI diff mode)
python3 tools/evlog_map --baseline base.json \
  --baseline-root /tmp/obs-merge-base \
  --rename-map renames.txt               # per-file ratchet vs a previous --json run
```

`--baseline` ratchets **per file**, not on the aggregate: a file present in the
baseline must score at least what it scored there; a file with no baseline
entry (brand-new) must reach `--min-new-score` (default 70). Aggregates across
asymmetric file sets would let a dark new file hide behind a well-instrumented
touched file — and block PRs whose new files are merely below the average.
`--rename-map` (tab-separated `old<TAB>new`) matches renamed files to their
baseline entry so moving a legacy file is never punished as "new". It also
fails a **discovery collapse**: a file that had entry points at the baseline
and has none at HEAD, whose score would otherwise read a vacuous 100.

Every run writes `evlog.map.json` (gitignored) to the repo root unless
`--no-write`.

### Why `--min-entries` exists

**A score gate cannot see what was never discovered.** An empty map scores
100/100, so anything that breaks discovery — a FastAPI upgrade, a rewrite of
the router wiring, a bad `--files-from` list, a typo in the scanner — reads as
an *improvement* and every `--min-score` / `--baseline` gate waves it through.
`--min-entries N` exits 1 when fewer than N scored entry points were found, and
`--json` carries the same number as top-level `entryCount`. CI passes today's
count as the floor; raise it as the surface grows, and lower it only in the
same PR that deliberately deletes entry points.

## Entry points

| Kind | Discovered by |
|---|---|
| `api` | `@router.<verb>` / `@app.<verb>` decorated functions, plus imperative `router.add_api_route(path, handler, methods=[...])` registration (FastAPI serves both identically, so both must be discoverable) |
| `websocket` | `@router.websocket` handlers |
| `worker` | ARQ tasks **registered in `app/worker.py`** (helpers in `workers/tasks/` are not entry points) |
| `voice` | LiveKit callbacks wired in `apps/voice-agent/src/agent.py`'s `WorkerOptions` (`entrypoint_fnc`/`prewarm_fnc`), plus the per-turn coroutine the `LLM` subclass's `chat()` delegates to in `llm.py` (`voice.collect_voice_registry` parses both wirings) |

Infra routes (`/health`, `/metrics`, `/favicon.ico`) are exempt — nothing to
instrument, excluded from the score.

### Route paths are the ones the server actually serves

A decorator's path is only the last third of a served path: FastAPI also
prepends every `include_router(prefix=…)` on the way down from the app and the
module's own `APIRouter(prefix=…)`. `routers.collect_router_mounts` walks that
chain — `app/core/app_factory.py` → `app/api/v1/routes.py` → the two-level
nesting under `app/api/v1/endpoints/integrations/` — and hands each module its
mount prefix, so `endpoints/memory.py` reports `/api/v1/memory` instead of `""`.

This matters because everything path-based is judged on it: sensitivity
classification, `CREDENTIAL_ROUTES`, the infra exemption, and every path a
report prints. Like the worker and voice registries the wiring is parsed, never
hardcoded, and anything unresolvable (a moved app factory, a non-literal
prefix, a router included at two different prefixes) **raises** — silently
dropping a branch would hand ~90 handlers a path the server never serves and
nothing would say so. A module the app never includes keeps no prefix:
`services/embedding_sidecar/server.py` is its own ASGI app, not a branch of
this one. Mounts are keyed by repo-relative path so the CI merge-base worktree
resolves them identically to the working tree.

## Requirements (score-bearing)

| Check | Weight | Passes when |
|---|---|---|
| `wide-event` | 40 | handler calls `log.set()`/`log.set_ns()` (HTTP) or runs inside `wide_task()`/`log_context()` (worker); voice entry points require the boundary itself — the LiveKit worker has no middleware, so a bare `log.set()` is discarded |
| `audit` | 25 | *high-sensitivity routes only:* handler calls `log.audit(...)` |
| `structured-errors` | 20 | raises are `AppError`/`create_error`/`HTTPException(detail=...)` — not bare `ValueError("...")` |
| `context` | 15 | `log.set()` uses at least one canonical `WideEventFields` key (schema is parsed live from `wide_events.py`) |
| `error-handling` | 15 | every `except` clause keeps the caught error: it records it (`log.error`/`warning`/`audit`/`set`) **or** re-raises it intact — see below |
| `error-context` | 15 | every `log.error`/`log.warning` carries structured kwargs (`error_type=`, ids) instead of data interpolated into prose |
| `info-noise` | 10 | fewer than three `log.info()` lines per entry point — info never reaches the wide event, so narration belongs in `log.set()` fields |

The first five weights are evlog's. `error-context` and `info-noise` were
reported-but-unscored nudges until the backend was swept clean of both; they now
carry weight like every other check, so a regression costs score instead of
printing a suggestion. **Nothing in this scanner is non-scoring anymore** — every
rule a run reports is a requirement.

Per entry point: 100 minus failed weights. Global score: weighted average —
**money/auth routes count double**. Grades: ≥90 excellent, ≥70 good,
≥50 needs-work, else at-risk.

### What `error-handling` counts as handled

An `except` clause passes only when the error it caught survives it — one of:

- it **records** it: a `log.error`/`warning`/`exception`/`critical`/`audit`, or
  a `log.set`/`set_ns` that puts it on the wide event;
- a bare **`raise`**, which re-raises the caught exception;
- **`raise <name>`**, where `<name>` is the clause's own `except X as <name>`;
- **`raise Something(...) from <name>`**, same binding — `__cause__` survives,
  and the app's exception handler reads it.

Everything else fails, including three shapes that *look* handled:

```python
except Exception:
    raise HTTPException(status_code=500, detail="Failed to create todo")  # fail: original error gone
except Exception as e:
    raise HTTPException(status_code=500, detail="…") from None            # fail: cause deleted on purpose
except Exception:
    return {"ok": False}                                                  # fail: records nothing
```

Each of those produces a 500 with zero telemetry about *what* failed: the type
and message of the real exception are destroyed before anything reads them. A
`return` is fine — but only alongside a record; on its own it is a swallow.
This is stricter than upstream evlog, which counts any throw-or-return.

`scripts/ci/checks.mjs evlog-map-bots` holds `catch` to the same bar. `raise ... from e`
has no JS keyword, so the `cause` option carries it: `throw <caught>` is the
rethrow (JS has no bare `throw`, so nothing maps to bare `raise`) and
`throw new X(..., { cause: <caught> })` is the `from` — anything else drops the
error, including `throw new X("…")` and a bare `return`.

Sensitivity is classified from whole-word route/module terms (`payment`,
`auth`, `login`, …), payment/auth imports (`razorpay`, `stripe`, `workos`), and
PII field names next to write calls — upstream evlog's heuristics — plus
`sensitivity.CREDENTIAL_ROUTES`, an explicit list of mounted paths.

The term list deliberately drops `token`, `session` and `register`: here those
words name chat sessions, LiveKit media tokens and device registration far more
often than credentials, and adding them back mislabels dozens of routes. But a
handful of genuine account-takeover surfaces contain no auth word at all —
refresh-token rotation (`POST /api/v1/device/token`), device pairing, the
one-time connect-code redemption (`GET /api/v1/integrations/connect-link`), and
binding a chat account to a GAIA account (`/api/v1/platform-links/{platform}`,
`/api/v1/bot/*link*`). Naming those paths one at a time is the honest
mechanism: it is exact, it is reviewable, and it costs no false positives.
Because it matches the **mounted** path, it depends on the router mount
registry below.

### The voice rule is stricter, on purpose

`wide-event` accepts *either* a `log.set()` **or** a `wide_task()`/`log_context()`
boundary for `api`, `websocket` and `worker` entry points — those all run under
something that opens an event for them (`LoggingMiddleware`, or ARQ's registered
task wrapper). **Voice entry points require the boundary itself.** The LiveKit
worker has no middleware: with no boundary open, `log.set()` writes into a
`ContextVar` nobody ever emits, and the fields are discarded with no error and
no log line. So a bare `log.set()` in a voice callback proves nothing — it looks
instrumented and produces zero telemetry, which is the worst of both. If you
touch `apps/voice-agent/src`, check for the `async with log_context(...)` /
`wide_task(...)`, not for the `log.set()`.

## Suppressions

A finding you have consciously decided not to fix is waived with a comment —
it reports `n/a` (visible in the map), never `pass`:

```python
# evlog-map-disable-next-line audit -- covered by WorkOS's own audit log
# evlog-map-disable-line audit -- same, placed on the flagged line itself
# evlog-map-disable context, error-handling -- proxied request, no context to add
# evlog-map-disable -- waive every check in this file
```

Handler-level findings (wide-event, context, audit) anchor to the `def` line;
the directive may sit directly above the `def` **or** above the handler's
first decorator — both placements work. A directive naming a check id that
doesn't exist is reported as a warning, never silently ignored.

**The `--` reason is mandatory.** A directive without one waives nothing and is
reported as a warning, so the check keeps failing — dropping a 40-point
requirement is a decision that needs a name attached to it, not a bare comment.
Every report (terminal and `--github-summary`) prints `N check(s) waived across
M file(s)`, so waiver drift is visible on every run instead of accumulating
quietly.

## Extending the scanner

The modules are a pipeline, and each extension point lives in exactly one of
them: the registries (`routers.py` mount prefixes, `voice.py` LiveKit entry
points, `schema.py` canonical fields) → `facts.py` (one AST pass per file → the
reduced facts every rule reads) → `rules.py` (pure predicates over those facts)
→ `scan.py` (discovery, suppression, scoring) → `report.py` (terminal / JSON /
step-summary) → `compare.py` (the per-file ratchet). Rules never walk the AST
themselves.

**Adding a rule.** Add the fact it needs to `HandlerFacts`/`FileFacts` and
populate it in `_collect_handler_facts`, then append a `Rule` to `RULES` in
`rules.py` with an `id`, `kinds`, a `check` returning `Finding | None`, and —
for a requirement — a `weight`. The id is public API: it is what suppression
comments name and what the JSON contract keys on, so renaming one silently
invalidates every existing `evlog-map-disable` for it. Adding weight lowers
scores repo-wide, so land the instrumentation first or the ratchet fails every
open PR; re-run `python3 tools/evlog_map --all` to see what moved.

**Adding a surface.** Discovery is deliberately parsed, never hardcoded — the
worker registry from `app/worker.py`, the voice registry from `agent.py`'s
`WorkerOptions` and `llm.py`, the router mounts from `app_factory.py`'s
`include_router` chain, the field schema from `wide_events.py`. Follow
that: write a `collect_*_registry` that reads the real wiring and raises when
it finds nothing (a moved registry must fail loudly, not silently score zero
entry points), give the new kind a name in `HANDLER_KINDS`, and decide which
existing rules apply to it via each rule's `kinds`. Then raise the CI
`--min-entries` floor by the number of entry points you just added. A surface
on a different runtime (the TypeScript bots) gets its own port instead —
`scripts/ci/checks.mjs evlog-map-bots` mirrors the ids, weights, grade bands and JSON
schema so the two maps stay mergeable; any change to the contract here has to
land there too.

## Relationship to `tools/lints` and `tools/logcheck`

`route-contract` (pre-commit) is the hard floor: a handler with no `log.set` at
all cannot be committed. evlog map is the graded ceiling above it: how *well*
instrumented each entry point is, weighted by how much it matters. The two read
handlers with the same own-scope semantics, so they never disagree.

Both read *source*. `tools/logcheck` closes the loop from the other end: it
reads the NDJSON a running surface actually emitted and judges whether it is
usable (framing, core keys, secrets, the byte cap, "a failing request must
record why"). A file can score 100 here and still fail there — that is the
point of having both.

## Tests

`test_evlog_map.py` — one test per rule that has been wrong or could invert
silently, driven through the real scanner:

```bash
uv run --no-project --with pytest pytest tools/evlog_map -q
```

Every test is mutation-verified: inverting the rule it covers makes it fail. If
you add a rule, add the test the same way — and check it fails when you break
the rule on purpose, because a test that cannot fail is not a test.

## CI

The `observability` lane in `.github/workflows/code-quality.yml`:

0. runs this scanner's own test suite first (`pytest tools/evlog_map
   tools/logcheck`) — a rule that inverts silently keeps printing a score, so
   the tool is tested before it is trusted to gate anything,
1. always posts the full-repo score to the job summary, and fails if discovery
   drops below the `--min-entries` floor on either surface,
2. on PRs, scores the changed Python files at the merge-base and at HEAD with
   the same (HEAD) scanner and applies the per-file `--baseline` ratchet:
   regressions fail, brand-new files must reach the 70 floor, a file that went
   from having entry points to having none fails as a discovery collapse, and
   renames compare against their old path.

That makes the score a ratchet: legacy gaps don't block you, but the files you
touch must leave the map at least as bright as you found them. The lane is
enforced — the backend reached 100/100 before the flat-enforced lanes model
replaced the marker ratchet.

## Scope

The adapter observes the entire Python surface: every decorator-registered
FastAPI route/websocket (multi-decorator stacks collapse to one entry point),
every ARQ task registered in `app/worker.py`, and the LiveKit voice worker
(`apps/voice-agent/src`) — its session entrypoint runs inside a
`log_context("voice_session_start")` boundary and each turn inside `wide_task`;
`prewarm` is waived with a reason (sync per-fork bootstrap, no event loop for
a boundary), and the `start`/`download-files` CLI wrappers are not LiveKit
entry points, so they carry no runtime instrumentation to score. The
TypeScript bots (`apps/bots` + `libs/shared/ts`) run on a separate logging
stack and are scored by their own port, `scripts/ci/checks.mjs evlog-map-bots`.

## Limitations

Static analysis, same caveats as upstream evlog: it cannot judge whether the
attached context is *useful* at runtime, and it reads one file at a time — a
handler whose `log.set` lives in the service layer needs the call (or a
suppression) in the handler itself, exactly like the `route-contract` lint.
The PR gate scans only changed files, so a change to
`libs/shared/py/wide_events.py` (the schema), `app/worker.py` (the task
registry), the router wiring (`app_factory.py`/`routes.py`) or the voice wiring
(`agent.py`/`llm.py`) can move *unchanged* files' scores — the full-repo scan
in the same lane is where that shows up. Schema and registries are always read
from HEAD, for the base scan too.
