# Custom Python lints (`tools/lints/`)

Mechanical enforcement of the `apps/api/CLAUDE.md` rules that ruff has no rule
for. Plain-Python AST checkers, stdlib only, one file per rule plus a shared
runner. They run in the `static-python` CI job and the api pre-commit config.

```bash
# Run against the API app tree (exits non-zero on any violation or crashed rule):
python3 tools/lints/run.py apps/api/app

# Unit tests:
uv run --project apps/api pytest tools/lints/test_lints.py -q
```

Each failure prints the rule, why it exists, the offending `file:line`, the exact
remediation, and a link back to the relevant section here.

## Ratchet allowlists

Every rule carries an `ALLOWLIST` of the offenders that predate it, checked into
the rule file with a per-entry reason. The list is a **ratchet**: remove an
entry when you fix its target; never add one. A new violation cannot be
allowlisted away — it must be fixed, which is the point.

---

## route-contract

**Rule:** every handler in `app/api/v1/endpoints/` decorated with
`@router.<method>` must call `log.set(...)`.

**Why:** the 3-step route contract (`apps/api/CLAUDE.md` → "FastAPI — Route
Handlers") opens with `log.set()` carrying the user/operation/IDs known at
entry. A handler that never calls it emits a request with no wide-event context,
so the request is invisible to the per-request Loki/Grafana queries.

**Fix:** add `log.set(...)` at the top of the handler with what is known at
entry. This lint only checks step 1 (that `log.set` is called at all) — the full
contract (delegate to a service, `log.set` the result, return `JSONResponse`)
still lives in the prose.

**Allowlist** groups the grandfathered handlers by reason: infra endpoints
(health, favicon), pre-auth OAuth flows (no user at entry), deprecated
endpoints, and operational handlers that are fixable follow-ups.

---

## no-service-classes

**Rule:** a class named `*Service` under `app/services/` must not have instance
methods (methods taking `self`).

**Why:** services are async module-level functions (`apps/api/CLAUDE.md` →
"Service Layer"). A `*Service` class with instance state is a hidden singleton
with injected dependencies — the anti-pattern the rule guards against.

**Fix:** convert the class to module-level async functions, or — if grouping is
genuinely wanted — make every method `@staticmethod` (no `self`).

**Scope:** deliberately the `*Service` naming convention. Connection pools,
registries, watchers, stores and SDK-client wrappers legitimately hold state and
are not named `*Service`, so they are out of scope. Classes whose base is a
data/enum/exception/protocol/ABC type are skipped (a `*Service` ABC is a
polymorphic base, not a stateful service).

---

## wide-events-logging

**Rule:** modules under `app/` must not `import logging` / `from logging import`
or import `loguru` directly.

**Why:** structured logging goes through `from shared.py.wide_events import log`
(`apps/api/CLAUDE.md` → Code Style). That wrapper emits one context-rich
canonical event per request; stdlib logging or bare loguru bypasses it, so those
lines never join the wide event and are invisible to per-request queries.

**Fix:** replace with `from shared.py.wide_events import log` and use
`log.set()` / `log.info()` / `log.error()`.

**Allowlist:** `app/config/sentry.py` alone — it installs the loguru → Sentry
sink and must touch loguru directly. Relative imports (`from .logging import
...`, a local module) are not flagged.

### Reserved wide-event keys

**Rule:** `log.set(...)` / `log.set_ns(...)` / `log.bind(...)` must not write a
key named `time`, `level`, `message`, `logger`, `module`, `line`, or `worker`
(the JSON line's core keys — `_CORE_KEYS` in `libs/shared/py/logging.py`).

**Why:** the JSON sink guarantees core keys always win: a colliding extra field
is re-emitted as `ctx_<key>` instead of corrupting the line's real
level/message. So a reserved key never lands where the caller expects — this
catches the mistake at commit instead of at query time. Applies to the facade
whatever it is imported as (`log`, or an alias like `wide_log`); the sentry.py
import allowlist does not exempt it.

Only setters whose keywords land at the JSON **top level** are checked.
`set_ns` merges its keywords *under* the namespace (so sub-keys can safely be
named `level`, `worker`, …) — for it, only the namespace argument itself is a
top-level write and the only collision candidate.

**Fix:** rename the field to a domain-specific name (e.g. `job_level`,
`source_module`).

### Constant log messages

**Rule:** the message passed to `log.debug` / `log.info` / `log.warning` /
`log.error` / `log.exception` / `log.critical` must be a constant string. The one
interpolation allowed is a leading `{LogTag.X}` prefix — anything else in the
f-string (`{e}`, `{user_id}`, `{len(items)}`) is a violation.

**Why:** a wide-event message is an identifier, not a sentence. Grouping,
alerting and every Loki query key off the literal string, so
`f"upload failed for {user_id}"` shards one event into as many distinct messages
as there are users, and the interpolated value lands in prose where nothing can
query, filter or aggregate it. Applies to the facade whatever it is imported as
(`log`, or an alias like `wide_log`).

**Fix:** keep the message constant and move the data to structured kwargs —
`log.error(f"{LogTag.X} upload failed", error_type=type(e).__name__, user_id=user_id)`.
Exception logs carry `error_type=`; add the ids already in scope. Never pass
secrets or raw user content (tokens, message bodies, email addresses) as a field
— log a count, a length, or a type instead.

---

## repository-boundaries

**Rule:** the repository layer is the only path to MongoDB. Four checks:

1. `app.db.mongodb.collections` is imported only inside `app/db/repositories/`
   and `app/db/mongodb/`.
2. `bson` / `ObjectId` is imported only inside `app/db/`.
3. Public methods of classes in `app/db/repositories/` are fully annotated with
   no `Any` / `dict[str, Any]`. Underscore-prefixed methods are exempt.
4. The entity-cache helpers (`get_cache` / `set_cache` / `delete_cache` /
   `delete_cache_by_pattern` / `get_and_delete_cache`) are imported only inside
   `app/db/` (the repository `CachePolicy`) and `app/decorators/` (the
   `@Cacheable` / `@CacheInvalidator` machinery). The raw `redis_cache` client
   (locks / rate-limits) is not banned.

**Why:** services reach Mongo through typed domain repositories
(`app/db/repositories/CLAUDE.md`). Raw collection handles, `ObjectId`, Mongo
filters, and dict-shaped documents must not cross that boundary — that is what
keeps ids `str` above the layer, invalidation automatic, and every returned value
a typed model. mypy strictness cannot catch all of this (a strict module can
still hand a `dict[str, Any]` outward), so the boundary is held mechanically here.

**Fix:** call the domain repository (`todo_repository.get(...)`) instead of the
collection; keep `ObjectId` conversion inside the repository; annotate public
repository methods with the domain's typed models.

**Allowlist:** checks 1, 2 and 4 each carry a ratchet `ALLOWLIST` of the call
sites that predate the repository layer (grouped by reason). Entries are removed
as each remaining reader migrates — never added; a new violation must be fixed,
not allowlisted. Check 4's allowlist is the legitimate NON-entity caches
(aggregate rollups, tokens, external-data / derived-display caches) — the ban is
only on hand-caching a repository-managed *entity* behind the repo's back. Check 3
has no allowlist (the layer is new — it starts clean).

---

## ignore-whys

Not an AST rule — a config check on the root ``pyproject.toml``:

```bash
python3 tools/lints/check_ignore_whys.py
```

**Rule:** every escape hatch in the root config must carry a why-comment —
trailing on the entry's line, or in a comment block directly above it:

| source | an escape hatch is |
| --- | --- |
| ``[tool.ruff.lint] ignore`` | a rule switched off everywhere |
| ``[tool.ruff.lint.per-file-ignores]`` | a rule switched off for a path glob |
| ``[[tool.mypy.overrides]]`` | a per-module setting that *weakens* checking (rationale goes above the block header) |

Adjacency is strict: a distant group comment does not cover a newly appended
entry. One rationale may still document a short run of siblings by sitting
directly above the first — but each entry must be able to point at its why.

**Why this replaced the old set-ratchet:** a baseline that blocks additions
cannot tell a load-bearing exemption from stale debt, and the stock never gets
re-litigated. An escape hatch WITH a stated why is a decision; one WITHOUT is a
hole. If you cannot state the reason in one sentence, fix the code instead of
exempting it.

---

## suppression-hygiene

Not an AST rule — a stateless scan of every source file:

```bash
python3 tools/lints/check_suppressions.py            # whole tree
python3 tools/lints/check_suppressions.py app/foo.py # scoped
```

**Rule:** an inline suppression may only exist at the offending line, WITH a
written reason on that same line:

```python
builder = create_agent(**kwargs)  # type: ignore[arg-type]  # langgraph ships no stubs
result = run(cmd)  # noqa: S603 -- operator-supplied command is the feature
```

```ts
const x: any = load(); // biome-ignore lint/suspicious/noExplicitAny: gallery-only demo
```

The reason states the ROOT CAUSE (upstream typing gap, framework contract,
deliberate choice). Another tool directive (``NOSONAR …``) is not a reason.
The bar is presence; review judges quality.

**There is no baseline and no memory.** Two stateless properties hold the line:

1. HERE — a suppression without a why fails at its exact line.
2. The compilers hunt staleness: mypy's ``warn_unused_ignores`` flags dead
   ``# type: ignore``, ruff's RUF100 flags dead ``# noqa``, and biome emits
   ``suppressions/unused`` for dead ``// biome-ignore`` (gated in CI). A
   suppression that no longer masks anything breaks the build on its own —
   strictly stronger than any growth ratchet, because nothing can rot silently.

This replaces the old count-baseline (``config/suppressions-baseline.json``,
deleted): counting suppressions was always a proxy for "every suppression is
justified" — now the real invariant is enforced directly.

### Staleness watchdog (per-file entries)

Inline noqas clean themselves up via RUF100; config exemptions cannot. The
suppression-hygiene lane therefore also runs:

```bash
python3 tools/lints/check_ignore_staleness.py
```

which re-runs every concrete `per-file-ignores` entry's rule against its file
with only that entry stripped from a temp copy of the config — every other
setting stays exactly as configured — and fails when an entry masks nothing
anymore: delete it. Pattern globs are skipped: they are category policy, not
per-file debt.

---

## plr-complexity-ratchet

Not an AST rule — runs its own `ruff` invocation, so it's a standalone
script/hook rather than something through `run.py`:

```bash
python3 tools/lints/check_plr_complexity.py           # check
python3 tools/lints/check_plr_complexity.py --update  # record the current baseline
```

**Rule:** ruff's `PLR0911`/`PLR0912`/`PLR0913`/`PLR0915` (too many returns /
branches / arguments / statements) are enforced everywhere, but the debt that
existed when they were switched on is grandfathered per file in
`tools/lints/plr_complexity_baseline.txt` — **until a PR touches that file**.
A genuinely new violation (a new file, or a rule an existing file didn't
already have) is never grandfathered, touched or not.

This is deliberately *not* a plain `[tool.ruff.lint.per-file-ignores]` entry:
that silences a rule for the whole file forever, with no way to notice a PR
making an already-flagged function worse. `PLR0911/0912/0913/0915` sit in
`[tool.ruff.lint] ignore` only so the main ruff lane doesn't double-report a
debt this script already owns — they are not actually off.

**Why:** the debt was too large (240 violations across 180 files) to fix in
one pass, but a static exemption never shrinks on its own. Tying the
exemption to "has this PR touched the file" turns each PR that happens to
edit a grandfathered file into the moment its debt gets paid down, without
blocking unrelated work everywhere else.

**Fix:** if the violation is new, simplify the function (or, if it's a
genuine one-off, justify it in review and add it to the baseline with
`--update`). If it's grandfathered but your PR touches that file, fix the
violation now and delete its line from the baseline.

**Scope:** on a PR, "touched" is the same `scripts/ci/changed-files.sh py`
diff every other lane uses. On a push/full scan (no PR base ref), there is no
notion of "touched" — grandfathered violations stay quiet, same as before.

---

## no-silent-fallback

**Rule:** a broad `except` (`Exception` / `BaseException` / bare) may not both stay
silent *and* hand back a falsy stand-in — `None`, `False`, `0`, `""`, `[]`, `{}`,
or falling out of the handler.

**Why:** it makes a total failure indistinguishable from a real empty result at
every call site. This has shipped here more than once: notification search
returned an empty list when the backend was down and rendered as an empty inbox,
and a swallowed `AttributeError` did the same thing one layer below it. The
caller has no way to tell "nothing matched" from "the query never ran".

**Scope** is deliberately narrower than ruff's `BLE001` (1001 findings, mostly
benign top-level safety nets). Three things must all be true to be reported: the
except is broad, nothing in the handler logs or re-raises, and it substitutes a
falsy value. A handler that logs is fine. A handler that re-raises is fine. A
handler that returns a real value is fine.

**Fix:** log why it failed before returning the fallback, or let the exception
propagate. If the empty value genuinely *is* the right answer, catch the specific
exception that means that — `except ValueError` is a decision; `except Exception`
is a blanket.

**Allowlist:** keyed `<path>::<enclosing function>`, so an unrelated edit above a
handler does not shift it and fire a false alarm. It grandfathers ten probe/parse
sites that predate the rule. Like the `no-service-classes` allowlist it is a
ratchet — remove an entry when the site is fixed, never add one.

---

## tool-dump-boundary

**Rule:** every `model_dump()` call under `app/agents/tools/` must pass
`mode="json"` literally. A bare call (or any other mode, or `**kwargs`) is
reported.

**Why:** Pydantic's two dump modes have opposite contracts — python mode keeps
native `datetime` objects, JSON mode produces ISO strings — and they differ by
three invisible characters at the call site. Inside the tools tree every dump
crosses into model/SSE text, where python-mode output either crashes stdlib
`json.dumps` (`TypeError: Object of type datetime is not JSON serializable`) or
silently degrades to Python reprs. Issue #917 shipped exactly this:
`search_reminders_tool` returned its serialization error on every call for
months because one tool used a bare dump while the rest of the tree used
`mode="json"`; the unit tests mocked `model_dump()` with plain strings and never
saw it.

**Scope** is deliberately the tools tree only. Service- and repository-layer
dumps legitimately stay in python mode: those dicts persist to MongoDB as BSON
dates, which the scheduler's `$lte` recovery scans match on — converting them to
ISO strings would break scheduling silently.

**Fix:** pass `mode="json"`. If a dump under `tools/` genuinely feeds a
Mongo write rather than the model/stream boundary, that logic belongs in the
service/repository layer anyway (see `repository-boundaries`).

**Allowlist:** keyed `<path>::<enclosing function>` with an **audited call
count**, grandfathering thirteen sites whose models the #917 audit verified are
string-only (`ImageData`, `SearchResultItem`/`WebSearchResult`, the calendar
wire models, `TodoLabelCount`) — both dump modes produce identical output
there. The count is the ratchet, not just the entry: a *new* bare dump added to
an allowlisted function pushes its count past the audited number and is
reported, so a historical exemption can never absorb new code. An entry comes
out when its model gains a datetime field and the calls take `mode="json"`;
never raise a count.
