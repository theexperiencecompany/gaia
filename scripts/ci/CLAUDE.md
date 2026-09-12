# scripts/ci/ — one script per concept

**A new CI responsibility joins the script for its concept as a subcommand. It
never becomes a new file.** If nothing here fits, the responsibility is a new
concept — say so out loud and add one script, not one file per verb. The
directory used to hold ~40 scripts whose names were the only thing relating
them; the shape below is what keeps a reader able to find the code that runs a
lane without grepping the workflow first.

## Concept → script

| Concept | Script | Subcommands |
| --- | --- | --- |
| Where and how hard a job runs | `runner.sh` | `select`, `watchdog`, `cancel-superseded`, `prime-archive`, `parallel`, `dep-marker`, `with-slots` |
| The service containers a suite talks to | `test-services.sh` | `up`, `prepare`, `reset`, `down`, `janitor` |
| The embedding sidecar | `embedding-sidecar.sh` | `start`, `stop` |
| Running the Python suite | `pytest.sh` | `slice`, `flake-gate`, `regression-proof` |
| Is the suite strong enough | `mutation.sh` | `matrix`, `plan`, `shard`, `module`, `local`, `replay` |
| Which tests a diff can reach | `test_impact.py` | `record`, `select`, `fetch` |
| What this PR changed | `changes.sh` | `files`, `py-source`, `docker-inputs` |
| Standing dependency + pin gates | `audit.sh` | `pnpm`, `playwright-pin`, `alert-rule-tools`, `evlog` |
| Static hygiene over the TS/JS surface | `checks.mjs` | `file-sizes`, `components-per-file`, `types-location`, `duplication`, `evlog-map-bots`, `api-schema`, `api-schema-types` |
| Turning a run's output into a verdict | `verdict.py` | `emit`, `consolidate`, `dir`, `check-ownership`, `pytest-verdict`, `regression-proof-select`, `regression-proof-verdict`, `collect`, `step-outcomes` |
| Publishing what a green master produced | `release.sh` | `resolve-image-tags`, `promote-latest`, `dispatch-cli-publish`, `disable-cf-builds` |
| The release-metadata guards | `release.mjs` | `validate-manifest`, `verify-cli` |
| Shipping to production | `deploy.sh` | `plan`, `stack`, `verify`, `retag`, `notify` |

Release and deploy are two concepts, not one: `release.sh` publishes artifacts
(image tags, `:latest`, the CLI on npm); `deploy.sh` puts them on the Swarm.

`lib/` holds what the entrypoints share or delegate to: `log.sh` (the log
convention), `cpu-slots.sh` (the host CPU governor, below),
`service-images.sh` (the digest-pinned test-service images),
`image-repos.sh` (the GHCR repo per image group), `explicit-file-list.mjs` (the
`CHANGED_FILES` contract), `bots-facts.mjs` + `evlog-map-bots.mjs` (the bots
observability scanner behind `checks.mjs evlog-map-bots`) and
`mutation_matrix.py` (the AST detector behind `mutation.sh matrix`),
`mutation_gap.py` (the executable-line detector behind the no-covering-test
verdict) and `mutation_report.py` (the grouped human report, the shard's
`shard.verdict.json` replay artifact, and the `verdict.py emit` call that
reports each mutated module to the gate — `mutation.sh replay` is the engine it
drives).

The mutation lane produces TWO artifacts on purpose. `shard.verdict.json` sits
beside `shard.log` and carries every survivor with its mutant id, resolved line
and full diff — the only thing `replay` can reproduce a survivor from, and
deliberately NOT under `verify-logs/verdicts/`, because `verdict.py consolidate`
reads every JSON in that tree as a lane verdict and indexes `doc["lane"]`: a
foreign shape there does not degrade, it crashes the gate. The lane verdicts
themselves are written only by `verdict.py emit`, one per module, lane
`mutation/<module path>`.

The bots scanner and the three `mutation_*.py` modules live in `lib/` rather
than inline because they are large bodies with their own tests and a second
consumer: inlining the 1000-line bots scanner
would push `checks.mjs` past the 1200-line hard cap `checks.mjs file-sizes`
itself enforces, `mutation_matrix.py` is imported directly by
`scripts/test/mutation-sweep.sh` and by `tests/test_mutation_matrix.py`, and
`mutation_report.py` is read back by `mutation.sh replay` long after the run
that wrote it. A
`lib/` module is never an entrypoint — every one of them is reached through its
concept's script.

`wide-event-conformance/` is the one directory that is not a single script, and
deliberately so: it is a multi-file tool, not a responsibility that could be a
subcommand. `contract.json` is the cross-runtime contract data, and `run.py`
drives two separate runtimes through `emit_python.py` and `emit_typescript.ts`
to diff what they actually print. Folding an entry point into `checks.mjs` would
leave the other three files behind and hide where the tool really lives.

## The host CPU governor (`lib/cpu-slots.sh`)

The box is 8 physical cores / 16 threads, but the heavy lanes size their own
parallelism independently and land together: the four `test-python` slices alone
budget ~16 threads (unit-a=5, unit-b=7, integration=4, bridge serial), and on the
SAME cores at the same time run main.yml's `build` (nx `--parallel 6`),
`test-typescript`, `docker-image`, and all of code-quality.yml — including
`mutation.sh shard` four at a time, each wanting nproc-2. Two overlapping pushes
double it. The 15-min load average was measured at ~18.5 (~2.3x oversubscription);
the same PR ran 3.6 min on an idle box vs 11.3 min loaded.

`cpu-slots.sh` is a weighted counting semaphore over a token pool in a
HOST-SHARED dir (`/run/gaia-ci/cpu-slots`, or `$HOME/ci-cache/cpu-slots` — shared
across every runner instance because they share `$HOME`; deliberately NOT
`RUNNER_LOCAL_CACHE`, which is per-instance and would give each runner its own
budget). A lane takes tokens equal to its real thread appetite and releases them
at the end, so the concurrent heavy work is capped at the pool size and lanes
queue instead of thrash. Pool size is `GAIA_CPU_TOKENS`, defaulting to the
thread count (`nproc`, 16 on the box). That default is measured, not assumed:
the test-python slices' static worker shares (5+7+4) sum to the 16 threads by
design for a single run, so a smaller pool would serialise a lone run's own
slices and regress the single-push case; at `nproc` a single run is unaffected
while two overlapping runs still halve the oversubscription (measured: two
concurrent `main.yml` dispatches drove the 1-min loadavg peak to 59 with the
governor off vs 32 with the pool at 16, per-run wall 6.4/6.1 min -> 5.5/4.8 min).

Two rules make it safe to have in the gate at all:

- **It fails open, always.** It is a no-op off the box
  (`RUNNER_ENVIRONMENT != self-hosted`), with no `flock`, with an uncreatable
  dir, or for a non-positive N. Every acquire has a timeout
  (`GAIA_CPU_SLOTS_TIMEOUT`, 600s); on expiry it logs `::warning::` and PROCEEDS
  WITHOUT the tokens. The governor can never hang or fail a lane.
- **Leaked tokens self-heal.** Available is computed under `flock` as
  `TOTAL - sum(live holder files)`, so a counter cannot drift. A grant whose
  holder pid is dead (a SIGKILL'd cancelled job that never ran its EXIT trap) or
  that is older than `GAIA_CPU_SLOTS_TTL` (3600s) is reclaimed by the next
  acquirer.

Wiring: `pytest.sh slice` takes `XDIST_N` tokens, `mutation.sh shard` takes its
`nproc-2` budget (and bounds `MUTMUT_MAX_CHILDREN` to match), and the nx `build`
step takes `NX_PARALLEL` via `runner.sh with-slots N -- <cmd>` (the wrapper exists
so a scriptless lane's step stays one command line). The lib lives in the repo
checkout and is sourced like `log.sh`; no `setup.sh` re-run is needed on the box.

## Conventions every script here follows

- `#!/usr/bin/env bash`, then a header comment listing the subcommands and the
  env contract, then `set -euo pipefail`.
- `# shellcheck source=…` + `source "$(dirname "$0")/lib/log.sh"`.
- One `cmd_<sub>` function per subcommand. Nothing runs at source time.
- A `main` with a `case "${1:-}"` dispatch that prints the usage and exits 2 on
  an unknown subcommand.
- Fail loud. Never `2>/dev/null || echo ""` in detection code: a swallowed
  error yields an empty list, every lane skips, and the gate goes green on an
  unchecked PR.
- An array that may be empty is expanded `${arr[@]+"${arr[@]}"}`, never
  `"${arr[@]}"`. macOS runners are bash 3.2, where expanding an empty array
  under `set -u` is itself an "unbound variable" error — bash only stopped
  treating that as unset in 4.4. These scripts reach a mac: `setup-node-pnpm`
  calls `runner.sh dep-marker` on the desktop build. The plain form broke
  `Package desktop (mac)` on every run for two days while every Linux lane
  (bash 5) stayed green, which is exactly how long it takes to notice.
- The log convention, via `lib/log.sh`: raw tool output inside
  `ci_group`/`ci_endgroup`, and the LAST line a one-line verdict (`ci_ok`).
  Test steps are the exception — a traceback must be readable uncollapsed.
- A GATED lane says that same last line through the verdict contract instead:
  `ci_verdict` / `ci_verdict_die`, which are one-line wrappers over
  `verdict.py emit`. See "The verdict contract" below.

## The verdict contract

`verdict.py` was `report.py`: same concept, renamed when it grew the two
subcommands that make the concept enforceable. It is the ONLY producer of a
lane's verdict, and every gated lane goes through it.

The measured problem: a lane's verdict was the last ~100 lines of a 20k-190k
line log, which is unreadable until the whole run completes. Whether a lane
emitted an `::error file=,line=` annotation at all was per-lane folklore —
`python-static` did, `test-python` and `regression-proof` did not, so a red
test slice showed nothing on the PR's Files tab. And the gate printed
`failure` for a lane that had merely run out of clock, sending readers to hunt
a finding nobody had written. Triaging one red lane cost a dozen commands.

`verdict.py emit` writes all of it from one call — the JSON, the annotations,
the step-summary block, the one-line human verdict — so a lane cannot ship
three quarters of a verdict:

```json
{"lane": "test-python/unit-a", "status": "pass|fail|skip|timed_out|error",
 "summary": "<one line a human reads first>",
 "findings": [{"file": "<repo-relative>", "line": 1, "message": "…", "detail": "…"}],
 "advice": ["<actionable sentence>"]}
```

Files land in `<dir>/<lane>.json`, where `<dir>` is `$GAIA_VERDICT_DIR` if set,
else `$RUNNER_TEMP/verdicts` on a runner, else `verify-logs/verdicts` in a
checkout (gitignored). **Never the checkout on CI**, and that is not a
preference: a self-hosted workspace persists between jobs (`clean:` is false
there), so verdicts left in the tree are uploaded by the NEXT job to land on
that runner — stale lanes from another PR reaching a gate. A job also uploads a
DIRECTORY, so anything else running in it that writes a verdict rides along:
run 34586506166's gate table carried `mutation/app/does_not_exist.py`, a
fixture path from an end-to-end test that `test-harness-tools` had just run.
`RUNNER_TEMP` is per-job and GitHub wipes it, which fixes the first by
construction; `verdict.py check-ownership`, which the composite runs BEFORE the
upload, fixes the second by failing the step with `::error file=` at the stray
file. A verdict belongs to a job when its lane is the job's `family` (default:
its `lane`) or sits under `<family>/` — the mutation shards pass
`family: mutation`, since mutation.sh writes per MODULE rather than per shard.

**A script that needs that path reads `verdict.py dir`; it never re-derives it.**
A bash `${GAIA_VERDICT_DIR:-$REPO_ROOT/verify-logs/verdicts}` looks equivalent
and is not — it has no `RUNNER_TEMP` rung, so on a runner it names the checkout
while the composite uploads from the runner's temp dir, and every verdict
written through it misses the gate without a single error.

A lane id may name a sub-unit — `test-python/unit-a`, `mutation/<module>` — and
the slash is a real directory, so one matrix's shards write side by side.

Every job in a `quality-gate` `needs:` list ends with the
`./.github/actions/upload-verdict` composite under `if: always()`. It uploads
`verdict-<job>`, and fills in a bare status-derived verdict for a lane that has
not adopted the contract yet (`--only-if-missing`, which matches by lane id
across the whole tree rather than by file name, so a lane that DID report keeps
its own findings even when it named the file differently). Adopting a lane is
therefore a strict improvement, not a prerequisite. The gate downloads every
`verdict-*` and runs `verdict.py consolidate` with
`--expect "<job>[@<family>]=<job result>,…"` covering exactly its `needs:` list.

Two jobs CANNOT report, and say so: the composite is a path in the checked-out
tree, so `probe` (no checkout at all) and `select-runner` (checks out the
DEFAULT BRANCH on purpose — it handles a PAT and must not run PR-authored code,
so a composite this branch adds is not in its tree) are declared
`<job>@result-only=…`. They are still enforced on their job result; they just
have no artifact to wait for. Declaring is the point — silence from an
UNDECLARED lane stays a failure. The same constraint is why a composite must
never read `matrix`, `needs`, `strategy` or `job`: it has none of those
contexts, and the runner rejects the whole action at parse time on every job
that uses it. Anything matrix-dependent is an input the caller fills. Both
rules are enforced by `scripts/ci/tests/test_composite_actions.py`, which reads
every `.github/actions/*/action.yml` — including expressions inside an input's
`description`, which are template-parsed exactly like a step's and are how this
first shipped broken.

A lane may report as a FAMILY of sub-units — `test-python` as one verdict per
slice (`test-python/unit-a`), `test-mutation` as one per mutated MODULE
(`mutation/<module>`, plus `mutation/shard-<n>`) — and the family is satisfied
by any member, because how many members exist is decided at runtime by the
matrix or by `mutation.sh plan`. Where the job name and the family differ, the
`--expect` entry says so: `test-mutation@mutation=${{ … }}`. A family with NO
members is still `NO VERDICT`, reported under the job name.

Two rules make that enforceable rather than decorative:

- **A lane that reports NOTHING is a failure.** `NO VERDICT` is how the gate
  catches a lane that stopped running — which otherwise looks exactly like a
  lane with no failures. `scripts/ci/tests/test_workflow_verdicts.py` is the
  other half: it fails if any gated job loses its upload step, or if `--expect`
  drifts from `needs`.
- **The job result travels with the lane name.** It is the only way to tell the
  two silences apart: a `skipped` lane (the `changes` job proved its language
  untouched) runs no steps and CANNOT write a verdict, while a lane that ran
  and wrote nothing has lost its reporting. Conflating them either reds every
  TS-only PR or hides the bug the contract exists to catch.

`timed_out` is its own status, not a flavour of `fail`, because the two need
opposite reactions: a failure has a finding to open, a timeout has a diff to
split or a cap to raise. The `upload-verdict` composite emits it when the job
is CANCELLED, which is what exceeding `timeout-minutes` produces. A lane killed
by a STEP-level cap surfaces as `error` ("failed before it could report") —
the step outcome does not distinguish a cap from a crash, and guessing would be
worse than saying so.

The three non-bash entrypoints keep the same shape in their own language:
`checks.mjs` and `release.mjs` dispatch on `process.argv[2]` into `cmd*`
functions and exit 2 with the usage on an unknown subcommand; `verdict.py`
dispatches on `sys.argv[1]` into `cmd_<sub>` functions and returns 2 the same
way. Nothing in any of them runs at import time.

## One command line per workflow step

A workflow step is one command line. Any logic beyond that — computing file
lists, parsing output, loops, multi-line shell — lives here and the step calls
it:

```yaml
- name: Compute the mutation matrix
  run: bash scripts/ci/mutation.sh plan
```

Not heredocs, not inline `for` loops, not python embedded in YAML. That is why
the CI-facing subcommands read their inputs from the environment and default
every path: the flags exist so the tests can drive them hermetically.

## Testing

```
pytest scripts/ci
```

The tests drive the real scripts with stubbed externals (a fake `docker` on
PATH, a throwaway git repo, a stubbed `gh api`) — never a reimplementation of
the logic under test. A test that cannot be shown to fail proves nothing:
break the line it covers, watch it go red, restore.

## The one deliberate copy

`.dagger/src/gaia_ci/main.py` repeats the service-image pins from
`lib/service-images.sh`. That copy is intentional — the Dagger module is the
local harness and cannot source a shell file — and those two files are the ONLY
places a service image reference may appear. Bump them together.
