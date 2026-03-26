# General Engineering Principles

These apply across the entire monorepo — frontend, backend, bots, and shared libs.

## DRY — Search Before You Build

Before writing any utility, type, hook, service, or model, grep the codebase for it.

- Shared Python logic belongs in `libs/shared/py/` — import it via `gaia-shared`, never copy it into app code
- Shared TypeScript logic belongs in `libs/shared/ts/src/` — consumed as `@gaia/shared`
- If you find the same logic in two places while working, consolidate before adding more
- Duplicated code that diverges silently is worse than no abstraction at all

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

## Feature-Based Organization

Organize code by domain/feature, not by technical type.

- A feature owns its components, hooks, types, API calls, stores, and utilities together
- Cross-feature code that is genuinely shared goes in a shared location (`src/components/`, `src/lib/`, `app/utils/`)
- Do not reach into another feature's internals — if you need something from another feature, it should be exported from that feature's `index.ts`

## File Size & Single Responsibility

- A file that does two things should be two files
- When a file exceeds ~200–300 lines, it is a signal to split by responsibility
- No monolithic files that accumulate unrelated logic over time

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
