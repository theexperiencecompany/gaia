# General Engineering Principles

These apply across the entire monorepo — frontend, backend, bots, and shared libs.

## DRY — Search Before You Build

Before writing any utility, type, hook, service, or model, grep the codebase for it.

- Shared Python logic belongs in `libs/shared/py/` — import it via `gaia-shared`, never copy it into app code
- Shared TypeScript logic belongs in `libs/shared/ts/src/` — consumed as `@gaia/shared`
- If you find the same logic in two places while working, consolidate before adding more
- Duplicated code that diverges silently is worse than no abstraction at all

### Libraries Over Hand-Rolling

Standard problems have standard solutions — never hand-roll what a maintained library already does well.

- Before implementing any well-known algorithm (text chunking, retries/backoff, parsing, date math, rate limiting, diffing), check the dependency tree first: the solution is often already installed or one small add away in an ecosystem we already use (e.g. LangChain, FastAPI, HeroUI)
- A hand-rolled version starts subtly wrong and stays unmaintained — the library version has had its edge cases fixed by thousands of users
- If you find hand-rolled logic that a library in our stack covers, replace it with the library call — deletion is the best diff
- The bar for writing it yourself: the problem is genuinely domain-specific, or the library would be a heavy new dependency for a trivial need

## Dead Code

After every change, clean up before considering work done.

- Remove unused imports, variables, functions, types, and files
- When moving logic to a shared lib, delete the originals at every previous location
- When replacing an implementation, remove the old one entirely — no "just in case" leftovers
- When renaming or restructuring, hunt every reference down and update or remove it
- Never comment out code instead of deleting it
- If unsure whether something is still used, grep for it — do not assume

## Constants Over Magic Values

No magic strings or numbers anywhere in the codebase.

- Extract all literal values that carry meaning to named constants
- Group constants by domain in dedicated files (`constants/cache.py`, `constants/llm.py`, `src/config/`, `src/features/{feature}/constants.ts`)
- Constants are the single source of truth — if the same value appears in two places, one of them should import from the other

## Type Safety Ratchet

Every file you touch leaves stricter than you found it, and never looser. Scope the tightening to the code you are already changing — a ratchet, not a licence to rewrite the file.

- Close what is in front of you: `Any`, unparametrized generics (`dict`, `list`, `Callable`), untyped empty collections, a bare `str` holding a fixed set of values.
- **Never introduce** a new `Any` or bare generic into a file that did not have one. Adding a hole is never in scope; closing one nearly always is.
- A literal repeated at both a definition site and a lookup site (registry keys, event names, queue names, config keys) is an enum — when the value set is closed and this repo owns every member. When the values are external, open-ended, or owned by someone else's schema (provider model ids, third-party API fields), a named constant referenced from both sites is the right shape; an enum there claims a closed world we don't control and goes stale. Either way, nothing else enforces that the two sites stay in sync, and the drift is silent until production.
- An existing annotation is a claim, not evidence. `Any` launders wrong types downstream, so confirm the real runtime type before trusting a neighbouring declaration.
- Prove the tightening bites. A checker that was green before *and* after proves nothing changed — a decorative annotation is exactly as green as a load-bearing one.

The full canon — including the `StrEnum` vs `(str, Enum)` trade-off and the `reveal_type` probe — is in `apps/api/CLAUDE.md` (Type Safety); frontend rules are in `apps/web/CLAUDE.md`.

## Feature-Based Organization

Organize code by domain/feature, not by technical type.

- A feature owns its components, hooks, types, API calls, stores, and utilities together
- Cross-feature code that is genuinely shared goes in a shared location (`src/components/`, `src/lib/`, `app/utils/`)
- Do not reach into another feature's internals — if you need something from another feature, it should be exported from that feature's `index.ts`

## File Size & Single Responsibility

- A file that does two things should be two files
- When a file exceeds ~200–300 lines, it is a signal to split by responsibility
- No monolithic files that accumulate unrelated logic over time

## No Pass-Through Wrappers

Never write a function whose whole body is a call to another function. A one- or
two-line wrapper that only unpacks arguments, renames a call, or guards a
precondition before delegating is not an abstraction — it is a second name for
something that already has one, and every reader now has to open two files to
learn what one of them does.

- **The test is whether the body does anything of its own.** Reshaping arguments,
  a `None` guard, and `return other_thing(...)` are not "anything" — that is a
  redirect. Real branching, real transformation of the result, or real assembly
  of several calls is.
- **The precondition belongs with the callee, not in a wrapper around it.** If a
  read is meaningless without a `user_id`, the read itself should say so and
  return empty — then no caller can forget the guard and no wrapper is needed.
- **Signature mismatch is not a reason to add a layer — it is a reason to fix the
  signature.** When callee and call site disagree on shape, change the callee to
  take the shape the call site already has. Where that would cause an import
  cycle, extract the shared type into a lower-level module (see Type Safety
  Ratchet and `apps/api/CLAUDE.md` §10); do not paper over it with an adapter.
- **A registry/table of callables is where these breed.** Uniform-signature
  tables tempt you to write one tiny adapter per row. Make the real functions
  match the table's signature and register them directly.
- **Exception:** a wrapper that exists to give a genuinely non-obvious call a
  domain name (and is used in more than one place) is documentation, and stays.

## Self-Documenting Code

- Write code that explains itself through naming and structure — not through comments
- A comment that restates what the code obviously does is noise, not documentation
- Reserve comments for non-obvious decisions: why something is done a particular way, not what it does
- If a function needs a long comment to be understood, the function probably needs to be refactored

## Cleanup Is Part of the Task

No change is done until the surrounding area is clean. "Working" and "complete" are different things.

- Fix the thing you were asked to fix, and remove any related dead code you encounter in the process
- Do not leave a file in worse shape than you found it
- Lint and type-check passes are not optional — run them before considering a task done

## Test Rules

The full conventions doc for API tests is `apps/api/tests/CLAUDE.md`. The rules below apply everywhere tests exist.

- **Quality bar** — a test must be able to fail (delete a line of product code and it goes red), assert behavior not implementation, cover the failure path, be deterministic, never mock the thing under test, and never assert on LLM-generated prose.
- **Red first** — write the failing test before the fix and watch it fail. A test never observed red proves nothing; it only asserts what the code now happens to do.
- **DRY applies to tests** — fixtures and factories live in the shared catalog (`tests/conftest.py`, `tests/helpers.py`, `tests/factories.py`). Search it before hand-rolling a fixture in a test file; never copy a fixture across files.
- **One tier per purpose, one file per subject** — tests live with the code they test in the tier that catches the bug (unit for logic, integration for wiring, real-infra for real DBs, e2e for user journeys, stress for races/retries). No folder-per-test-type sprawl, no duplicate proof of a tier that already covers it.
- **Bug regressions are named** — a bug's failing-then-passing test goes in the natural file, named `test_<subject>_<issue>.py`.
- **Deletion over padding** — when a test can't be made to fail, delete or rework it. Padding that cannot fail is theater; a weakened assertion suppresses the bug instead of fixing it.
