# CI Architecture & Conventions (.github/)

Read this before touching anything under `.github/`. It encodes decisions that
are invisible from the YAML alone and gotchas that have already burned us.
`workflows/README.md` holds the per-workflow flow diagram — if you change any
trigger, job dependency, deploy condition, or release path, update it in the
same PR (its header says so too).

## Two workflows, two responsibilities

- **`workflows/main.yml` ("Quality Checks") — correctness.** Build + tests
  only. Its `quality-gate` job is a branch-protection target.
- **`workflows/code-quality.yml` ("Code Quality") — hygiene.** Twenty
  lanes (Biome, tsc, `python-static` = ruff + custom AST lints + complexity +
  docstrings + security in one job, mypy, dead code, evlog-map observability
  score, wide-event cross-runtime conformance, semgrep, sharded mutation
  testing, …) behind the
  `Quality gate (required)` check.


**Never add a check to both.** Every static check lives in code-quality.yml
only. We previously ran ruff/mypy/Biome/tsc/dead-code in BOTH workflows on
every PR — pure duplicate spend with zero added enforcement.

## Where jobs run: home box first, GitHub-hosted fallback

Both gate workflows open with a `select-runner` job (`ubuntu-latest`, no
Tailscale needed) that probes the Actions runners API via
`scripts/ci/runner.sh select` through the `./.github/actions/select-runner`
composite. Online + a free instance on the `gaia-home` box → every compute lane
gets `runs-on: ${{ fromJSON(needs.select-runner.outputs.runner) }}`; anything
else → `["ubuntu-latest"]`. The fallback is total — no job ever carries a bare
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
- **Concurrency is per SHA** (`ci-<ref>-<sha>`): cancelling a self-hosted job
  wedges its worker for the listener's 5-minute cancellation timeout, so
  superseded runs are cancelled through the API instead
  (`scripts/ci/runner.sh cancel-superseded`).
- `self-hosted-runner/README.md` in the private `gaia-infra` repo documents the
  box, the twenty runner instances (eleven `gaia-home` for main.yml, nine
  `gaia-home-lint` for code-quality.yml), and the install/teardown path. It
  lives there, not here, because this repo is public and the box's topology is
  not.
- **What actually keeps fork code off the box is the repo's fork-PR approval
  policy** (all outside collaborators require approval before any workflow
  runs). `runner.sh select` does send a PR whose head repo is not this one to
  `ubuntu-latest` before it probes the runners API — but that is ROUTING, not a
  security boundary: on `pull_request` a fork supplies its own workflow file,
  so it can choose not to call the composite at all. Do not weaken the approval
  policy on the strength of that check. What keeps the box's PAT away from fork
  code is that GitHub passes no Actions secrets to a fork's `pull_request` run
  at all — `select-runner` states that in its `github-token:` expression rather
  than relying on the default. (Pinning that job's checkout to master would be
  better still, but the composite and `runner.sh` do not exist there yet; it
  fails with exit 127 until they land.) The repo is public and the runner
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
  run: bash scripts/ci/mutation.sh plan
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

Three layers, from cheap to precise:

1. **`code-quality.yml` `changes` job** — one no-toolchain job diffs the PR
   and skips whole language lanes (Python lanes on a TS-only PR and vice
   versa). Lanes skipped this way count as PASSING in the gate; a failed
   `changes` job fails the gate. The detect lists are a deliberate superset
   that includes workflow/config files (yaml/yml/toml/lock/json): a
   workflow-only (`.yml`) PR lights every lane up so changes to CI itself
   get validated, but each lane self-skips via its own narrower
   `changes.sh files` list — lane lists NEVER include yml.
2. **`main.yml` `detect` job** — `nx show projects --affected` (via
   `nrwl/nx-set-shas`, base `master`) computes the affected project lists
   that gate build/test jobs and scope their `-p` arguments.
3. **`scripts/ci/changes.sh files` inside lanes** — scopes each tool to the
   exact changed files. Contract: prints `__FULL__` (push/dispatch → full
   scan), nothing (PR with no relevant changes → skip & pass), or one path
   per line. Lanes using it need `fetch-depth: 0` checkouts.

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
on a dev machine; keep the two in sync (images, credentials, env vars).

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

`scripts/ci/mutation.sh plan` fans the changed modules across a matrix, capped
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

`code-quality.yml`'s gate enforces every lane: a lane that is neither
`success` nor `skipped` (the `changes` job proved its language untouched)
fails the merge. The old marker-file ratchet (`quality-gate/enforced/<lane>`)
is gone — the rollout it enabled is complete and the two sources of truth had
drifted. New lane: add the job, its result to the gate's `needs:` + `RESULT`
map, and its name to the `LANES` array; it is enforced from the first run.

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

Every step follows the convention documented at the top of code-quality.yml:
step name says WHAT is checked; raw tool output goes inside
`::group::`/`::endgroup::` collapsibles; the last line is a one-line verdict
(`ruff: OK (...)`). Exception: test steps leave pytest/vitest failure output
un-grouped — on failure the traceback is the signal and must be readable
without un-collapsing anything. Custom enforcer scripts print
rule/why/exact-fix/doc-pointer on failure (see `tools/lints/`).

## Known constraints & facts (measured 2026-07)

- Branch protection targets are the two gate jobs, not individual lanes —
  lanes can be added/removed without touching repo settings.
- Nx Cloud is disabled (`NX_NO_CLOUD=true`; plan exceeded — deliberate, don't
  re-enable). There is NO remote nx cache: each CI job recomputes everything.
  The Next.js compiler cache IS persisted (`actions/cache` on
  `apps/web/.next/cache` in main.yml build + desktop-pr-build prepare).
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
- Parallelism is detected, not hardcoded: `scripts/ci/runner.sh parallel`
  sizes `--parallel` / `-n` from the runner it lands on (16 threads on the home
  box, 4 vCPU on GitHub-hosted). Do not write a bare `-n auto` or
  `--parallel=3` into a lane.
