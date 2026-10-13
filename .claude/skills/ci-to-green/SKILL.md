---
name: ci-to-green
description: >
  Take a red GAIA PR to green in one push: read every failing lane, fix in the order that
  stops one failure from masking another, prove each fix locally with the lane's own
  script (slow and sure, not a lookalike), then push once. Use when a PR has failing CI,
  mutation survivors or "no verdict" modules, regression-proof errors, red lint lanes, or
  when a combined/stacked branch was just merged onto a moved master.
---

# CI to green, in one push

Every push re-runs the whole pipeline, and one failure hides others. So: read
everything, fix in dependency order, verify each lane locally with the script CI runs,
push once.

## 1. Read the whole failure, once

```bash
mise ci:remote <PR#> --no-stack --verbose > /tmp/ci.txt   # every lane, survivor diffs, failing tests
grep -E "^FAIL|^PEND" /tmp/ci.txt
```

Sort each failure into one bucket before touching code:

| Bucket | Examples | Fixed in |
|---|---|---|
| Failing tests | `test-python (unit-a)` | step 2 |
| Mutation | survivors, or a module that "reached no verdict" | step 3 |
| regression-proof | "ERRORED on base", "SKIPPED on base" | step 4 |
| Lint / static | mypy, ruff, ratchets, package-hygiene | step 5 |
| Not ours | new advisory, stale runner cache, timing flake | prove it (step 6) |

GitHub's API allows 5,000 calls an hour across all tools. Save output to files and
re-read them instead of re-querying.

## 2. Failing tests first: they cause the mutation errors

A mutation module with **"no verdict / mutmut produced no state"** almost always means its
mapped suite has a failing test: mutmut's stats run stops at the first failure and
grades nothing. Confirm from the shard log, then fix the tests:

```bash
gh run download <run-id> -p 'mutation-log-*' -D /tmp/mutlogs
grep -hE "^FAILED|failed to collect stats|AttributeError" /tmp/mutlogs/*/shard.log
```

Then run **every** test file the mutation lane maps, once, serially. It's ~70s for 268
files, and it catches each remaining blocker before a slow mutation run trips on it:

```bash
GAIA_PR_BASE=master bash scripts/ci/mutation.sh matrix > /tmp/matrix.json
python3 -c "import json;print('\n'.join(sorted({t for m in json.load(open('/tmp/matrix.json')) for t in m['testfiles']})))" > /tmp/tests.txt
cd apps/api && LOG_LEVEL=ERROR uv run pytest -p no:xdist -q $(cat /tmp/tests.txt)
```

After merging a branch onto a moved master, expect test fallout, not product bugs. A test
patches a function master renamed (`record_activity` → `record_run_finished`), stubs a
config shape master now writes into (`{}` → `{"configurable": {}}`), or pins an enum
order master extended. Fix the test to follow master.

## 3. Mutation survivors

Each survivor in `/tmp/ci.txt` comes with its diff. Fix in this order:

1. **Missing assertion.** Assert the exact output (whole string, exact key, exact
   boundary). `in` checks let most mutants through. Freeze time with
   `@time_machine.travel(..., tick=False)` for `<=` vs `<` at "now".
2. **Redundant code.** When no input can tell the mutant apart, ask whether the line does
   anything. `x or "UTC"` in front of a parser that already defaults to UTC is dead: delete it.
3. **Provably equivalent.** Only when the value is never observed (e.g. a payload built
   only to measure `len()`, where a same-length key rename changes nothing), add
   `# pragma: no mutate — <why>` on that line.

## 4. regression-proof

It runs the PR's **newly marked** `@pytest.mark.regression` tests against the base app
and needs each one to FAIL there. An ERROR (import) or SKIP proves nothing.

- The test imports a **module** that doesn't exist on base, or tests a feature base
  doesn't have: the test is gap-fill, so remove the mark (`apps/api/tests/CLAUDE.md`).
- Only a **name** is new: read it as a module attribute inside the test (`todo_models.ExternalRef`).
  Rewrite by AST positions, not regex, so strings stay untouched.
- A new name used **at import time** (inside `parametrize`, a module constant, or a class
  attribute) still errors as an attribute. Move that case into its own test body.
- Once a file is unmarked, move its lane-only function-scope imports back to the top.

Verify locally. It diffs `base...HEAD`, so commit first:

```bash
cd apps/api && USE_REAL_SERVICES=1 bash ../../scripts/ci/pytest.sh regression-proof origin/master
```

## 5. Prove mutation locally, slow and sure

The lane's own runner on only the modules that failed, one at a time. Detach it: a
harness-managed background job was killed mid-run (exit 144).

```bash
MONGO_DB=mongodb://localhost:27017/gaia_test REDIS_URL=redis://localhost:6479/0 \
USE_REAL_SERVICES=1 MUTATION_JOBS=1 MUTMUT_MAX_CHILDREN=4 \
nohup bash scripts/ci/mutation.sh local app/x.py app/y.py > /tmp/mut.out 2>&1 < /dev/null &
```

- Watch `/tmp/mut.out` for `pass` / `SURVIVORS` / `ERROR`. Per-module logs are in
  `verify-logs/mutation/`.
- Contract-mapped modules refuse to run without `MONGO_DB` and `REDIS_URL`. That refusal
  is correct: without them every contract test would skip.
- The local run can find **more** survivors than CI reported. Trust it; it's the same
  engine over the same diff.

## 6. Lint last, in small batches

Only after the code stops moving. Run the exact CI lanes, a few at a time (13 lanes at once
ran out of memory on a 16 GB machine):

```bash
mise ci:local --only python-mypy,python-ruff,custom-lints,lint-imports
mise ci:local --only suppression-hygiene,ignore-whys,ignore-staleness,typed-boundaries,plr-complexity
mise ci:local --only interrogate,xenon,file-size,observability-ratchet,wide-event-conformance,doc-comments
mise ci:local --only package-hygiene,deps        # after any JS dependency change
```

`--only` takes one comma-separated list; a second `--only` replaces the first.

**Prove "not ours" before dismissing a failure:**
- **Static error naming a symbol that exists and is unchanged from master:** the runner
  has a stale cache. Show the CI lane is green locally.
- **New audit advisory:** master's last run passed before it was published, and the PR
  touches no package files. Bump inside the PR if the user wants one CI run; it's still a
  dependency change, so verify type-check, tests and the audit.
- **A build that fails locally:** build the pre-change commit in a throwaway
  `git worktree` too. Identical failure there means it's this machine, not your change.
- **A test that's slow on CI and fast locally:** runner-load timing.

## 7. Push once

Commit each phase locally as it lands, then push everything at the end, so CI runs once.
Then `mise ci:remote <PR#>` to confirm.

## Environment traps (each cost a round)

- zsh doesn't word-split `$VAR`. Use `${=VAR}` or an array:
  `T=(${(f)"$(git diff --name-only)"})`.
- A stale venv (`No module named bson/bubus`): `cd apps/api && uv sync --frozen --group backend --group dev`.
- A fresh worktree needs `mise trust` and `pnpm install` before hooks or `mise` tasks run.
- `git worktree add` fails when the branch name is already taken. Check it with
  `git ls-remote --heads origin <name>` first, and never chain `&& cd` after it: a failed add
  leaves you in the old tree.
- `git config rerere.enabled` is on: a merge can arrive pre-resolved from an older
  resolution. Read the result; don't trust the absence of conflict markers.
