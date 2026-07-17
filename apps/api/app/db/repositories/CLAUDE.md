# Repository layer (`app/db/repositories/`)

The typed, cache-integrated boundary between services and MongoDB. Every read
and write of a Mongo collection goes through a repository here. Nothing above
this directory holds a raw Mongo dict, an `ObjectId`, a Mongo filter, or a cache
call — those exist only inside this directory.

## The rules

**Ownership.** One repository owns one collection. Only `todo_repository` touches
the `todos` collection; only `user_repository` touches `users`. A service that
needs another domain's data calls that domain's repository — onboarding updates a
user through `user_repository.update(...)`, never through `users_collection`.
Cross-domain writes that reach around the owning repository are the exact drift
this layer exists to prevent.

**No raw dicts across the boundary.** Public repository methods accept and return
typed Pydantic models (`XDocument`, `XUpdate`) — never `dict`, never `Any`. The
base does `model_validate` on every read and `model_dump` on every write, so
`_id → id`, `ObjectId → str`, and datetime tz-normalization happen in exactly one
place. Dict-shaped data may exist only inside a repository method's body.

**No manual cache calls.** The base does read-through, write-through, and
invalidation automatically (see Caching below). Do **not** import
`get_cache`/`set_cache`/`delete_cache` in a repository or a service for
repository-managed data. If you find yourself invalidating a cache by hand, the
design is being worked around — stop and fix the base instead.

**Named finders, not raw filters.** Every query is a named method with a typed
signature (`list_for_user`, `get_by_email`, `find_pinned`). Raw Mongo filter
dicts are allowed only inside these methods. There is no generic `query(filter)`
DSL — a filter dict must never travel across the boundary. Aggregations are named
methods returning a typed result model.

**`$set`-only updates.** Updates take an `XUpdate` model and apply
`model_dump(exclude_unset=True)` as `$set`. There is no full-document replace. An
update model with no set fields raises `EmptyUpdateError` — a write that changes
nothing is a bug (a typo'd field name, a caller that forgot to set anything), and
it fails loud rather than issuing a silent no-op. `$unset`/`$inc`/array ops are
exposed only as named, typed methods where a domain actually needs them.

**`_update_fields_no_invalidate` is almost never allowed.** It writes fields
without refreshing the entity cache or bumping the generation — a deliberate hole
in the invalidation guarantee. It exists for declared hot fields whose staleness
is harmless (e.g. `last_active_at`). Every use must be justified in the calling
method's docstring. If you are not certain a stale value is harmless, use the
normal `update` path.

## Caching (automatic — do not reimplement)

Each cache-enabled repository declares a `CachePolicy(prefix, entity_ttl,
query_ttl)`. Three key families per scope (`user_id` for user-scoped repos, the
literal `"global"` otherwise):

```
{prefix}:{scope}:{id}            entity cache  — read-through on get, write-through on create/update, evicted on delete
{prefix}:{scope}:gen             generation counter (Redis INCR)
{prefix}:{scope}:q:{gen}:{hash}  query cache — any @cached_query finder, keyed under the current generation
```

Every write in the base does two things: refresh/evict the entity key, and `INCR`
the generation. That single `INCR` orphans **all** query caches for that scope at
once — they still carry the old `gen` in their key, so the next read misses and
they expire by TTL. This is why there is no manual invalidation and no `KEYS`
scan anywhere: invalidation lives in the base write path, not in call sites.
Redis being down degrades to pure Mongo (a `None` generation means "skip the
query cache", never "serve stale").

Cache a finder with the `cached_query(result_model)` decorator — it keys on the
method name plus a hash of its arguments, under the scope's current generation.

## Why the type safety is enforced three ways

Reading the code is not enough to keep this boundary clean — so three mechanical
layers hold it, each catching what the others cannot:

1. **Strict-mypy island.** `app.db.repositories.*` (plus migrated document/update
   models) is compiled under mypy's strict flags. This is what makes the generics
   real: `todo_repository.update(...)` accepting only `TodoUpdate` and returning
   only `TodoDocument | None` is enforced at the call site, so cross-domain
   confusion is a type error, not a runtime surprise. The island only grows as
   more repositories and models are migrated onto it — a module is never removed.

2. **The `repository-boundaries` lint** (`tools/lints/`), because mypy strictness
   can be satisfied while types still leak. It bans `collections` imports outside
   this directory, `bson`/`ObjectId` outside `app/db/`, and `Any`/`dict[str, Any]`
   /missing annotations in **public** repository signatures (underscore-prefixed
   subclass primitives are the exempt internal seam). Its allowlist is a ratchet:
   entries are removed as each domain is migrated, never added.

3. **Runtime Pydantic validation at both boundaries.** `model_validate` on every
   read means a corrupt or legacy document fails loud **here**, at the boundary,
   not three layers up wearing a confusing shape. `extra="forbid"` on update
   models turns a mistyped field name into a `ValidationError` instead of a
   silently-dropped write. `__init_subclass__` validates a repository's ClassVars
   at import, so a misconfigured repository fails at startup, not on first query.

Document models use `extra="ignore"` on read (legacy stray fields must not crash a
read); update models use `extra="forbid"` on write (writes are fully controlled).

## Adding a repository

1. **Verify the collection's reality first** — run a throwaway script against dev
   Mongo: actual `_id` type (ObjectId vs string — this sets `uses_object_id`,
   never guess it), the real field inventory, tz-awareness, embedded shapes.
   Model from observed data, not from reading service code.
2. Add `XDocument` (`extra="ignore"`) and `XUpdate` (all-optional, `extra="forbid"`)
   to the existing `app/models/<domain>_models.py`.
3. Add `app/db/repositories/<domain>.py`: subclass `MongoRepository` /
   `UserScopedRepository`, set the ClassVars and `CachePolicy`, turn every query in
   the domain's services into a named finder and every aggregation into a named
   typed method, and export a module-level singleton `x_repository = XRepository()`.
4. Write contract tests: inherit the base contract, add a per-finder test with
   exact fixtures → exact expected outputs, run green against real Mongo + Redis.
   **A repository without contract tests does not merge.**
5. Migrate every call site (found by grep, not memory), delete the domain's direct
   `collections` imports, and remove those files from the lint allowlist.
6. Add the domain's models/repository/service modules to the strict-mypy island.

## Contract tests are the Postgres-migration certificate

The backend-agnostic contract suite (`tests/contracts/`) runs against real Mongo +
real Redis. It is not a formality: when a `PostgresRepository` later exists, the
same contract classes run against it, and green-on-both is the proof of behavioral
equivalence. Never mock the DB or Redis in a contract test; assert on concrete
values, never on "was called".
