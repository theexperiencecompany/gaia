# Coverage-based test impact selection

A PR used to pay for all ~12k pytest tests in `apps/api` (~110-150s of pytest at
16 workers on the home runner — the dominant cost of a PR) to learn about a diff
that usually touches three files. Test impact selection runs only the tests that
can actually see the change.

## How the map is built

Every non-PR run of `test-python` (push to master, `workflow_dispatch`) runs
pytest with `--cov-context=test`, so coverage.py records a *dynamic context* per
test: which test id executed which line of which file. `scripts/ci/test-impact.py
record` reads that database and inverts it into

```json
{"meta": {"sha": "...", "slice": "unit"},
 "files": {"app/foo.py": ["tests/unit/test_foo.py::test_a"]},
 "test_files": {"tests/unit/test_foo.py": ["tests/unit/test_foo.py::test_a"]}}
```

One map per slice, cached under `test-impact-map-<slice>-<sha>`.

`COVERAGE_CORE=sysmon` is dropped for that run only: `sys.monitoring` cannot
record dynamic contexts, so the map run pays for the C tracer. PRs keep sysmon —
they do not record a map.

## How a PR uses it

`scripts/ci/test-impact-select.sh` restores the newest map for its slice
(`restore-keys: test-impact-map-<slice>-`), diffs against
`git merge-base origin/$BASE HEAD`, and runs `test-impact.py select`. The result
is the union of:

- every test covering a changed `app/**` file;
- every test in a changed or added `tests/**` file (emitted as the file path, so
  brand-new tests the map has never seen still run);
- `tests/contracts`, always — it is the API contract.

`scripts/ci/run-python-slice.sh` reads the selection into a bash array and passes
it to pytest, so node ids containing spaces or brackets survive intact.

## Everything uncertain widens to ALL

Selection is deliberately one-directional. It falls back to running the whole
slice when:

- `tests/conftest.py`, `tests/helpers.py` or `tests/factories.py` changed —
  fixtures are wired by name, and coverage cannot see which tests depend on
  which conftest;
- a changed `app/**` file is not in the map at all (new module, or never
  covered);
- any `.py` outside `apps/api` changed (`libs/shared/py`, tooling) — the map
  only covers `app/**`;
- a non-source file under `apps/api` changed (`pyproject.toml`, `uv.lock`, …);
- no map is cached yet, or the checkout has no merge-base;
- the selection would exceed 30% of the slice. A 10k-id argv is ~1 MB, close to
  `ARG_MAX`, and the saving at that size is not worth the risk.

The `bridge` slice is never selected against: it is one serial e2e file, so
selecting inside it saves nothing and skipping it is the least safe thing to do.

## Staleness

A map older than the PR's merge-base is still valid, because selection is by
*file*, not by revision: if `app/foo.py` was covered by those tests last week and
the PR changes `app/foo.py`, those tests still want to run. What an old map can
miss is coverage that only exists after a refactor — but every shape of that
(new file, moved file, changed conftest, changed dependency) is one of the ALL
fallbacks above.

## The safety net

Master always runs the full suite with the 80% coverage gate enforced. On PRs
the gate is report-only (`--fail-under=0`), because a partial run cannot reach
80% by construction; the step summary says `test impact: ran N of M (reason)` so
the selection is never silent. A wrong-but-wide selection costs seconds; a
wrong-but-narrow one would let a broken tree go green, which is why every
ambiguity resolves to ALL.
