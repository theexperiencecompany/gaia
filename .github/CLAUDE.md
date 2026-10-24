# CI Architecture & Conventions (.github/)

Read this before touching anything under `.github/`. It encodes decisions that
are invisible from the YAML alone and gotchas that have already burned us.
`workflows/README.md` holds the per-workflow flow diagram — if you change any
trigger, job dependency, deploy condition, or release path, update it in the
same PR (its header says so too).

## One workflow, one gate

**`workflows/ci.yml` ("CI")** is every lint, test, scan and build check behind
one required check, `quality-gate`. It replaced main.yml and code-quality.yml,
which ran 52 jobs per PR push between them, 24 of them for under a minute of
work behind a runner's setup.

- **Tiers.** A PR push runs the fast tier: `select-runner`, `detect`,
  `lint-node`, `lint-python`, `lint-mixed`, `ts-build-test`, the `unit-a` and
  `unit-b` slices, `test-mutation` on the changed modules (a survivor found
  only in the queue is an ejection plus a fix round), `quality-gate`. The merge
  queue (`merge_group`), master and dispatch run the full tier on top: the
  integration, bridge and browser slices (regression-proof rides integration,
  so it stays queue-only: the integration slice needs the services pool),
  `python-audit`, `scan`, `docker-image`, and on master `coverage` and the
  deploy phases. A PR reaches master only through the queue, so the slow checks
  run once per merge, not once per push. `detect` decides the tier
  (`tier` output) and `pytest.sh slices` cuts the slice matrix to it.
- **Grouped jobs.** Each check inside `lint-node`, `lint-python`,
  `lint-mixed`, `scan`, `python-audit` and `ts-build-test` is its own
  `continue-on-error` step with an `id`, listed once in the job's `CHECKS`
  YAML anchor. That list feeds `verdict.py post-statuses` (one `ci / <area> / <check>`
  commit status per check, linked to the job, its area from `CHECK_AREAS` in
  verdict.py so the PR list sorts into groups; skipped on fork and Dependabot
  PRs, whose token cannot write statuses) and `verdict.py step-outcomes`
  (fails the job if any check failed). A check that writes its own verdict
  reports under `<job>/<check>`, the job's namespace.
- **Never add a check twice.** One check, one step, one job.

## Where jobs run: home box first, GitHub-hosted fallback

ci.yml opens with a `select-runner` job (the control-plane runner, no
Tailscale needed) that probes the Actions runners API via
`scripts/ci/runner.py select` through the `./.github/actions/select-runner`
composite, once. It publishes three pools — `light` (detect, the lint jobs,
the scans), `heavy` (ts-build-test, the unit slices, the image) and `services`
(the slices and mutation shards that need the test-services namespace) — and
every compute job takes `runs-on: ${{ fromJSON(needs.select-runner.outputs.<pool>) }}`. The fallback is total — no job ever carries a bare
`runs-on: [self-hosted]`, so an offline box degrades to slower CI, never to a
queue that never drains. `build.yml` and the deploy workflows are deliberately
NOT routed through it: release images and deploys stay GitHub-hosted.

Consequences to keep in mind when editing a lane:

- **The workspace persists.** Every self-hosted checkout uses `fetch-depth: 0`
  (`clean:` only off self-hosted): a depth-1 checkout marks the persistent
  clone shallow and the next depth-0 fetch re-unshallows over a residential
  uplink (measured 21-104 s).
- **Service containers are shared, not per job** — `scripts/ci/test-services.sh`
  namespaces one shared container set per runner instance; every lane that
  starts them must release its namespace in an `if: always()` teardown step
  (`test-services.sh down`). The script decides shared-vs-per-job itself from
  `RUNNER_ENVIRONMENT`/`RUNNER_INDEX` — no caller branches on runner kind.
- **Concurrency is per SHA** (`ci-<ref>-<sha>`), not per PR: with a per-PR
  group and cancel-in-progress the new push waits for the old run to FINISH
  cancelling, and a cancelled self-hosted pytest step wedges its worker for the
  listener's 5-minute cancellation timeout. Superseded runs are cancelled
  through the API instead (`scripts/ci/runner.py cancel-superseded`), so a new
  push starts at once.
- `self-hosted-runner/README.md` in the private `gaia-infra` repo documents the
  box, the twenty runner instances (eleven `gaia-home`, nine `gaia-home-lint`,
  a pool ci.yml no longer asks for), and the install/teardown path. It
  lives there, not here, because this repo is public and the box's topology is
  not.
- **What actually keeps fork code off the box is the repo's fork-PR approval
  policy** (all outside collaborators require approval before any workflow
  runs). `runner.py select` does send a PR whose head repo is not this one to
  `ubuntu-latest` before it probes the runners API — but that is ROUTING, not a
  security boundary: on `pull_request` a fork supplies its own workflow file,
  so it can choose not to call the composite at all. Do not weaken the approval
  policy on the strength of that check. What keeps the box's PAT away from fork
  code is that GitHub passes no Actions secrets to a fork's `pull_request` run
  at all — `select-runner` states that in its `github-token:` expression rather
  than relying on the default. That job checks out the commit under test, not
  master: a master pin adds no boundary (a same-repo PR edits the workflow
  itself) and makes a selector change untestable on its own PR. The repo is public and the runner
  user's workspace, caches and network are shared state.

## Workflow files are thin orchestration — nothing else

A workflow step is one command line. Any logic beyond that — computing file
lists, parsing output, loops, multi-line shell — lives in a script under
`scripts/ci/` (or `scripts/test/` for tooling), and the step calls it.
**`scripts/ci/CLAUDE.md` is the contract for that directory** — one script per
concept, a new responsibility joins the script for its concept as a subcommand
and never becomes a new file. Read it before adding anything there:

```yaml
- name: Compute the mutation matrix
  run: python3 scripts/ci/mutation.py plan
```

Not heredocs, not inline `for` loops, not python embedded in YAML. Scripts
are reviewable, testable, and don't re-indent badly under YAML parsing.
Every new lane ships its logic in a script from day one.

**A conflicting PR gets no workflow runs.** Empirically verified three
times on this repo: when the PR's `mergeable` state is `CONFLICTING`,
`pull_request`-triggered runs are not created — silently, with no error,
no queued entry, nothing. If CI "stopped" with no new runs, the first thing
to check is `gh pr view --json mergeable`. Keep the branch merged with
`master`; re-merge and resolve before pushing further.

## Skipping work that isn't needed

Four layers, from cheap to precise, all decided in the one `detect` job:

1. **The tier** — a PR push never starts a full-tier job (see above).
2. **Affected projects and path signals** — `nx show projects --affected`
   (via `nrwl/nx-set-shas`, base `master`) computes the affected project lists
   that gate jobs and scope their `-p` arguments; `has_api_schema`,
   `has_analytics`, `has_alert_rules` and `has_go` are path-scoped. A job or
   check skipped this way counts as PASSING; a failed `detect` fails the
   gate. A workflow-only (`.yml`) PR lights the lint jobs up so changes to CI
   itself get validated, but each check self-skips via its own narrower
   `changes.sh files` list — check lists NEVER include yml.
3. **`scripts/ci/changes.sh files` inside checks** — scopes each tool to the
   exact changed files. Contract: prints `__FULL__` (push/dispatch → full
   scan), nothing (no relevant changes → skip & pass), or one path per line.
   The base is `detect`'s `base_ref`: the PR's real parent, or on a merge
   group the commit the group was built on (`merge_group.base_sha` — for the
   second PR in the queue that is the first PR's group commit, not master).
   `changes.sh base-rev` is the one place that turns it into a revision.
   Jobs using it need `fetch-depth: 0` checkouts.
4. **`verdict.py reuse-plan` in `detect`** — across pushes to the same PR.
   A check whose last pass on this PR (same base, not a manual re-run) is still
   valid — nothing in the union of its lanes' `verify-lanes.json` scopes and
   nothing under `.github/`, `scripts/`, `tools/`, `config/`, `patches/`, the
   repo root or any config manifest (`GLOBAL_INVALIDATORS` in verdict.py)
   changed between that pass and this run, on the head OR on the base it was
   merged into — is skipped and labelled `reused`. The pass is read from the
   check's own `ci / <area> / <check>` commit status, never the job API (a failed
   `continue-on-error` step reports conclusion `success` there). Each plan
   annotates the base tip it validated on its `detect` job
   (`::notice title=reuse-plan base`); a run without that note never anchors.
   A check needs `ci_check` in the lane table to be reusable; one without it
   always runs. Anything the plan cannot read means no reuse.

**Fail loud is non-negotiable in detection code.** Never
`nx ... 2>/dev/null || echo ""` — a broken nx invocation must fail the job.
Swallowed, it yields an empty affected list, every lane skips, and the gate
goes green on an unchecked PR (this bug shipped once; build.yml's variant
could silently skip production deploys).

## Python tests: runner-native against live services

**A PR has no coverage gate.** diff-cover was retired with the slice split: a
PR's slices run a test-impact selection, and a coverage percentage measured
over a subset is not a coverage percentage. The full suite and the 80%
combined gate run on master, which is the backstop — do not restore diff-cover
to a PR lane.

`test-python` (and master-only `coverage`) run pytest directly on the runner
against PostgreSQL/Redis/MongoDB/ChromaDB/RabbitMQ started by
`scripts/ci/test-services.sh` via the composite action
`actions/setup-python-test-env`. Plain `docker run`, not GitHub `services:`,
because Redis needs a command override (`--databases 32` for xdist isolation)
which `services:` cannot express.

Why not Dagger in CI: the suite itself takes ~2.5 min, but rebuilding the
Dagger environment (engine pull + apt + monorepo pnpm install + uv sync) on an
ephemeral runner cost ~5 min per run, its exit code needed a session-cleanup
workaround (grep for a `GAIA_PYTEST_EXIT` sentinel), and its engine-image pull
was flaky enough to need a retry loop. **The Dagger module (`.dagger/`) is the
local harness** — `dagger call test-python` gives you the identical topology
on a dev machine; keep the two in sync (images, credentials, env vars). The
browser slice (`engines: true` in `test-slices.json`) is the one slice a bare
`dagger call test-python` leaves out: it needs Chromium and an Obscura build, so
it runs only by name, `dagger call test-python --slice-name browser`, which
builds Obscura from the Dockerfile's `obscura-bin` stage and installs Chromium.
In CI the engine slices run as their own job, `test-python-engines` (test-python's
steps by YAML alias), which needs `obscura-bin`: that job builds Obscura through
`.github/actions/build-obscura` (the composite obscura-compat uses, one GHA cache
scope) under a 60-minute cap, so a cold build never spends the slice's 15. The
slice finds both engines through `scripts/ci/browser.sh locate` and fails, never
skips, when either is missing.

Gotcha that will bite conversions: the repo has no `.npmrc` any more — pnpm's
default isolated linker is what runners, dev machines and the Dagger env all
get, so a package's bins live in ITS `node_modules/.bin`, not only the repo
root. The device-bridge e2e test resolves `tsx` from both locations, and
`deploy-web.yml` must run wrangler as `pnpm --filter ./apps/web exec`.

## Dead code: tests are NOT live references

Both scanners treat code reachable only from tests as dead — that is the
intended semantic, keep it:

- **vulture** (`[tool.vulture]` in root `pyproject.toml`): `exclude` drops
  `*/tests/*`, `test_*.py`, `conftest.py` from the scan.
- **knip** (`config/knip.config.ts`): every workspace with tests excludes
  `*.test.ts` / `__tests__/**` from `project` — otherwise knip's vitest
  plugin registers test files as entry points and test-only-referenced code
  counts as used. When adding a workspace, add the exclusion.

## The mutation lane's shard count

`scripts/ci/mutation.py plan` fans the changed modules across a matrix, capped
at **the matrix's own `max-parallel`**. Do not raise the cap to "get more
parallelism" — GitHub runs only `max-parallel` jobs at a time regardless, so a
wider matrix cannot finish sooner. What it does cost is one check row per job
(a 430-module diff produced 250 of them, which no reviewer can read past) and a
full checkout + `uv sync` per job rather than per shard.

Under the cap each module gets its own shard and the check is named after it,
which is the common case and the most useful thing to read at a glance. Over
it, modules pack in round-robin and the check says `shard N/M (K modules)`; the
step then names every failing module in an `::error::` annotation and the job
summary, because "this shard is red" is useless without saying which module.

If the two ever drift, the plan silently either wastes runners or under-uses
them — keep `MAX_SHARDS` and `max-parallel` in step.

## The quality gate

The gate enforces every lane: a lane that is neither `success` nor `skipped`
fails the merge. ci.yml does not run on a title or body edit at all (see
"PR edits" below), so every gate run consolidates a run that had lanes. It
never waits — the old 40-minute poll held a runner for 225 of 431 minutes on
2026-10-23.

**PR edits.** ci.yml listens to the default `pull_request` types only. A run
on `edited` creates every job's check row, so a title or body edit replaced the
head commit's real rows with "Skipped". `edited` still matters for one case, a
retarget, whose lanes must re-scope to the new base: pr-title.yml (which runs on
`edited` for the title check anyway) re-runs the head's latest CI run with
`runner.py rescope` when `github.event.changes.base` is set, force-cancelling it
first if it is still going. A re-run reuses no earlier pass, and detect
resolves the base from the API, so the re-run checks the new base.

It reaches its verdict through `scripts/ci/verdict.py consolidate`
rather than a hand-rolled result loop, so the gate prints what each lane
actually FOUND (file, line, message) instead of the word `failure`, and a lane
that merely ran out of clock reads `timed_out` rather than `failure`. **New
check: a `continue-on-error` step in the grouped job that has its toolchain,
plus its line in that job's `CHECKS`. New job: add it to the gate's `needs:`,
add `<job>=${{ needs.<job>.result }}` to the gate's `EXPECT` env, and end the
job with the `./.github/actions/upload-verdict` composite under
`if: always()`.** Either is enforced from the first run, and
`scripts/ci/tests/test_workflow_verdicts.py` fails if you forget a half. The full contract — the JSON shape, why a
missing verdict is itself a failure, why the job result travels with the lane
name — is in `scripts/ci/CLAUDE.md` under "The verdict contract".

## Suppression hygiene (every inline suppression carries its why)

The `suppression-hygiene` lane is stateless: there is no baseline. A suppression
(`# noqa` / `# type: ignore` / `// biome-ignore`) may only exist inline, at the
offending line, WITH a written reason on that same line —
`tools/lints/check_suppressions.py` fails at the exact line otherwise. Staleness
is hunted by the compilers themselves: mypy's `warn_unused_ignores` flags dead
`# type: ignore`, ruff's RUF100 flags dead `# noqa`, and biome's
`suppressions/unused` diagnostic for dead `// biome-ignore` is gated in the
biome lane. Reproduce locally:
`python3 tools/lints/check_suppressions.py` (add paths to scope). Escape hatches
in `pyproject.toml` (`[tool.ruff.lint] ignore`, `per-file-ignores`, weakening
mypy overrides) must each carry a why-comment beside them — checked by
`tools/lints/check_ignore_whys.py`; see `tools/lints/README.md#ignore-whys`.

## Log readability (for humans AND agents)

Every step follows one convention: step name says WHAT is checked (a check
step's name starts with its id); raw tool output goes inside
`::group::`/`::endgroup::` collapsibles; the last line is a one-line verdict
(`ruff: OK (...)`). Exception: test steps leave pytest/vitest failure output
un-grouped — on failure the traceback is the signal and must be readable
without un-collapsing anything. Custom enforcer scripts print
rule/why/exact-fix/doc-pointer on failure (see `tools/lints/`).

## Known constraints & facts (measured 2026-07)

- Branch protection targets `quality-gate` and `Validate PR Title`
  (pr-title.yml; it runs on a merge group and passes there, since the title
  was validated on the PR), not individual lanes — lanes can be added/removed
  without touching repo settings.
- Nx Cloud is disabled (`NX_NO_CLOUD=true`; plan exceeded — deliberate, don't
  re-enable). There is NO remote nx cache: each CI job recomputes everything.
  The Next.js compiler cache IS persisted (`actions/cache` on
  `apps/web/.next/cache` in ci.yml ts-build-test + desktop-pr-build prepare).
- `nx.json` `defaultBase` is `master` (the single base branch). CI passes
  explicit bases; `defaultBase` matters for local `nx affected` / mise tasks.
- Versions are pinned where a trusted SHA/number was resolvable (nx 22.7.7 in
  nx.json `installation`, uv 0.10.6 (same as the Dockerfiles), `uvx ruff@<uv.lock version>` in the ruff
  lane, pnpm/action-setup + docker/login-action by SHA).
  `actions/checkout`/`setup-node`/`cache`/`nx-set-shas` still float on major
  tags — pin them from a machine with GitHub API access.
- Never run a linter unpinned in a lane: ruff 0.16.0 shipped new rules
  (ISC004, RUF036) four minutes before a scheduled run and turned the lane
  red with zero code changes. Pin to the uv.lock version; bump deliberately.
- Test-service images are digest-pinned (`tag@sha256:...`) in
  `scripts/ci/lib/service-images.sh` AND `.dagger/src/gaia_ci/main.py` —
  those two files are the ONLY places a service image reference may appear,
  and they are bumped together; the tag part is a readability label, the digest is
  what's pulled. The readiness wait recreates a container once on
  timeout (a genuine boot flake costs ~90s instead of a red build); a second
  timeout fails loud with container logs.
- RabbitMQ readiness probes MUST use `docker exec -u rabbitmq`. The image has
  no USER directive, so a plain exec runs as root with
  HOME=/var/lib/rabbitmq; probing during boot creates a root-owned
  `.erlang.cookie` and the server crashes with `eacces`
  (docker-library/rabbitmq#318). This bit us as an intermittent-looking
  failure that was actually a race our own probe caused — restart-retry
  couldn't save it because the recreated container got re-poisoned instantly.
- Wall-clock per PR ≈ the slowest `test-python` slice; the four slices
  (`unit-a`, `unit-b`, `integration`, `bridge`) run concurrently on separate
  runner instances, so the lane costs `max(slice)`, not their sum. Worker
  shares are static per slice and sum to the box — a runtime probe sees zero
  neighbours because the lanes start together.
- `pnpm install --filter <pkg>` does NOT meaningfully shrink installs here:
  with our lockfile it still materializes the full virtual store (verified:
  filtered install still unpacked `next`, ~1.4 GB). Don't reach for it as a
  CI optimization.
- Wall-clock perf assertions in tests must budget for shared-runner jitter
  (a 500ms bound flaked at 506ms; use order-of-magnitude tripwires, ~2x the
  observed worst case).
- Parallelism is detected, not hardcoded: `scripts/ci/runner.py parallel`
  sizes `--parallel` / `-n` from the runner it lands on (16 threads on the home
  box, 4 vCPU on GitHub-hosted). Do not write a bare `-n auto` or
  `--parallel=3` into a lane.
