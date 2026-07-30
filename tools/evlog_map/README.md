# evlog map — observability score for the FastAPI backend

A Python port of [evlog](https://github.com/HugoRCD/evlog)'s `map` command (MIT),
with a FastAPI/ARQ adapter for this repo's wide-event runtime
(`shared.py.wide_events`). It statically answers: *if something goes wrong in
production tonight, which parts of the backend will be able to tell you why?*

Stdlib only — no deps, runs anywhere `python3` does.

```bash
python3 tools/evlog_map                  # full scan (apps/api/app), terminal report
python3 tools/evlog_map --all            # per-entry check matrix
python3 tools/evlog_map --json           # full map as JSON (the evlog.map.json contract)
python3 tools/evlog_map --min-score 70   # exit 1 when the global score is below N
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
baseline entry so moving a legacy file is never punished as "new".

Every run writes `evlog.map.json` (gitignored) to the repo root unless
`--no-write`.

## Entry points

| Kind | Discovered by |
|---|---|
| `api` | `@router.<verb>` / `@app.<verb>` decorated functions |
| `websocket` | `@router.websocket` handlers |
| `worker` | ARQ tasks **registered in `app/worker.py`** (helpers in `workers/tasks/` are not entry points) |

Infra routes (`/health`, `/metrics`, `/favicon.ico`) are exempt — nothing to
instrument, excluded from the score.

## Requirements (score-bearing, evlog's weights)

| Check | Weight | Passes when |
|---|---|---|
| `wide-event` | 40 | handler calls `log.set()`/`log.set_ns()` (HTTP) or runs inside `wide_task()`/`log_context()` (worker) |
| `audit` | 25 | *high-sensitivity routes only:* handler calls `log.audit(...)` |
| `structured-errors` | 20 | raises are `AppError`/`create_error`/`HTTPException(detail=...)` — not bare `ValueError("...")` |
| `context` | 15 | `log.set()` uses at least one canonical `WideEventFields` key (schema is parsed live from `wide_events.py`) |
| `error-handling` | 15 | every `except` clause logs or re-raises — no silent swallows |

Per entry point: 100 minus failed weights. Global score: weighted average —
**money/auth routes count double**. Grades: ≥90 excellent, ≥70 good,
≥50 needs-work, else at-risk.

Sensitivity is classified from whole-word route/module terms (`payment`,
`auth`, `login`, …), payment/auth imports (`razorpay`, `stripe`, `workos`), and
PII field names next to write calls — same heuristics as upstream evlog.

## Opportunities (reported, never scored)

- `error-context` — `log.error(f"...")` with zero structured kwargs
- `info-noise` — handlers narrating with `log.info()` (which never reaches the wide event) instead of accumulating `log.set()` fields

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

## Relationship to `tools/lints`

`route-contract` (pre-commit) is the hard floor: a handler with no `log.set` at
all cannot be committed. evlog map is the graded ceiling above it: how *well*
instrumented each entry point is, weighted by how much it matters. The two read
handlers with the same own-scope semantics, so they never disagree.

## CI

The `observability` lane in `.github/workflows/code-quality.yml`:

1. always posts the full-repo score to the job summary,
2. on PRs, scores the changed Python files at the merge-base and at HEAD with
   the same (HEAD) scanner and applies the per-file `--baseline` ratchet:
   regressions fail, brand-new files must reach the 70 floor, renames compare
   against their old path.

That makes the score a ratchet: legacy gaps don't block you, but the files you
touch must leave the map at least as bright as you found them.

## Limitations

Static analysis, same caveats as upstream evlog: it cannot judge whether the
attached context is *useful* at runtime, and it reads one file at a time — a
handler whose `log.set` lives in the service layer needs the call (or a
suppression) in the handler itself, exactly like the `route-contract` lint.
The PR gate scans only changed files, so a change to
`libs/shared/py/wide_events.py` (the schema) or `app/worker.py` (the task
registry) can move *unchanged* files' scores — the full-repo scan in the same
lane is where that shows up. Both schema and registry are always read from
HEAD, for the base scan too.
