# Custom Python lints (`tools/lints/`)

Mechanical enforcement of the `apps/api/CLAUDE.md` rules that ruff has no rule
for. Plain-Python AST checkers, stdlib only, one file per rule plus a shared
runner. They run in the `static-python` CI job and the api pre-commit config.

```bash
# Run against the API app tree (exits non-zero on any violation):
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

## ignore-ratchet

Not an AST rule — a config ratchet, so it runs as its own script/hook rather than
through `run.py`:

```bash
python3 tools/lints/check_ignore_ratchet.py           # check
python3 tools/lints/check_ignore_ratchet.py --update  # record a deliberate change
```

**Rule:** the escape hatches in the root `pyproject.toml` may only ever *shrink*.
Three kinds are tracked:

| source | an escape hatch is |
| --- | --- |
| `[tool.ruff.lint] ignore` | a rule switched off everywhere |
| `[tool.ruff.lint.per-file-ignores]` | a rule switched off for a path glob |
| `[[tool.mypy.overrides]]` | a per-module setting that *weakens* checking |

The check fails if a rule is added to either ruff list, a new file entry appears,
or a mypy override starts weakening a check for a module it did not before.

Only mypy *loosenings* count. The strict-island block that sets the same keys to
`true` is a tightening and is deliberately untracked — this guards holes, not
strictness. The edit it is really there to catch is widening an existing block's
`module` list: dropping `"app.services.*"` in beside `"tests.*"` turns off type
checking for every service and reads as a one-word diff.

**Why:** both lists are the residue of a cleanup campaign. They are the only two
places a ruff rule can be switched off wholesale, and editing them is invisible
in review in a way a failing check is not — a single line quietly re-opens
exactly the hole the campaign closed. Comparing against the checked-in baseline
turns "loosen the linter" from an unnoticed config edit into a conscious,
reviewable decision.

**Baseline:** `tools/lints/ignore_ratchet_baseline.txt`, one line per escape
hatch, sorted, checked in. Compared as a **set**, not a count — a count check
passes when someone removes one entry and adds another. Line shapes:

```
ignore<TAB><rule>
per-file-ignores<TAB><glob><TAB><rule>
mypy-override<TAB><module><TAB><setting>
```

**Fix:** delete the offending rule from the list and fix the code it silences.
If the exemption is genuinely warranted (a framework contract, a generated file),
justify it in review and run `--update`; the baseline diff then shows the new
escape hatch on its own line for a reviewer to accept or reject.

**Removals always pass** — that is the ratchet turning. The check prints what was
removed and suggests `--update` to lock the win in; until someone does, the
baseline stays at the old high-water mark, so a removed entry can be re-added
without failing. Running `--update` as part of the cleanup closes that window.

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
