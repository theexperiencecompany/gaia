# Coverage-based test impact selection

A PR used to pay for all ~12k pytest tests in `apps/api` (~110-150s of pytest at
16 workers on the home runner — the dominant cost of a PR) to learn about a diff
that usually touches three files. Test impact selection runs only the tests that
can actually see the change.

## How the map is built

Every non-PR run of `test-python` (push to master, `workflow_dispatch`) runs
pytest with `--cov-context=test`, so coverage.py records a *dynamic context* per
test: which test id executed which line of which file. `scripts/ci/test_impact.py
record` reads that database and inverts it into

```json
{"meta": {"sha": "...", "slice": "unit"},
 "files": {"app/foo.py": ["tests/unit/test_foo.py::test_a"]},
 "test_files": {"tests/unit/test_foo.py": ["tests/unit/test_foo.py::test_a"]}}
```

One map per slice, uploaded as the workflow artifact `test-impact-map-<slice>`
(30-day retention). Not `actions/cache`: a pull_request run can only restore
caches written on its merge ref or on master, so a map recorded by a dispatch
run on the PR's own branch would be invisible to it.

Those runs trace with the C tracer (`sys.monitoring` cannot record the per-test
contexts the map needs). PR runs do not trace coverage at all — they do not
record a map, and their coverage total would be meaningless after selection.

## How a PR uses it

`test_impact.py fetch` downloads the map artifact of the newest SUCCESSFUL
push-to-`master` run of main.yml — resolved by run, and re-checked to be a
non-`pull_request` run whose head repository is this one, because a branch
name is not provenance (a fork can name its branch `master`, and a
`pull_request` run executes the fork's own workflow file); then
`test_impact.py select` diffs against
`git merge-base origin/$BASE HEAD`, and applies the rules below. The result
is the union of:

- every test covering a changed `app/**` file;
- every test in a changed or added `tests/**` file (emitted as the file path, so
  brand-new tests the map has never seen still run);
- `tests/contracts`, always — it is the API contract.

Minus whatever the slice's `matrix.slice.ignore` excludes: `unit-b`'s paths are
`tests/unit tests/meta` but it ignores the three directories `unit-a` owns, so
the selector is given the same `--ignore` list (`SLICE_IGNORE`) and drops those
node ids — from the selection AND from the `total` the 30% threshold is a
fraction of.

`scripts/ci/pytest.sh slice` reads the selection into a bash array and passes
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
- anything under `tests/**` that is not a `test_*.py` / `*_test.py` module
  changed — snapshots, fixtures, cassettes, helper modules. pytest collects
  nothing from such a path, and the map cannot name the tests that read it;
- anything that configures the run itself changed, wherever it lives: any
  `uv.lock` (the workspace lockfile is the **root** one — there is no
  `apps/api/uv.lock`), any `pyproject.toml`, `.python-version`, `pytest.ini`,
  `setup.cfg`, `tox.ini`, **anything under `scripts/ci/`**,
  `.github/workflows/main.yml`, `.github/actions/setup-python-test-env/**` —
  every script in `scripts/ci/` shapes the environment the suite runs in (the
  services, the sidecar, the parallelism, the image digests), and none of that
  is visible to coverage;
- any other non-source file under `apps/api` changed (Dockerfile, scripts, …).
  Tooling config and prose (`.pre-commit-config.yaml`, `*.md`, `docs/`) are the
  one narrow exception: they cannot change a test's outcome and select nothing;
- no map artifact exists yet, or the checkout has no merge-base;
- the selection would exceed 30% of the slice. A 10k-id argv is ~1 MB, close to
  `ARG_MAX`, and the saving at that size is not worth the risk.

The `bridge` slice is never selected against: it is one serial e2e file, so
selecting inside it saves nothing and skipping it is the least safe thing to do.

## Off switch

Selection is on by default. Setting `TEST_IMPACT_ENABLED=0` (or `false`) for a
run turns it off: `fetch` downloads no map, and
`select` writes `ALL` and prints
`test impact (<slice>): disabled by TEST_IMPACT_ENABLED=0, running ALL`. The
workflow exposes it as a `workflow_dispatch` input, so a full run on a branch is
one click away when a selection looks wrong.

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
