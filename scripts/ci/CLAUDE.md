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
| Is the suite strong enough | `mutation.sh` | `matrix`, `plan`, `shard`, `module`, `local` |
| Which tests a diff can reach | `test_impact.py` | `record`, `select`, `fetch` |
| What this PR changed | `changes.sh` | `files`, `py-source`, `docker-inputs` |
| Standing dependency + pin gates | `audit.sh` | `pnpm`, `playwright-pin`, `alert-rule-tools`, `evlog` |
| Static hygiene over the TS/JS surface | `checks.mjs` | `file-sizes`, `components-per-file`, `types-location`, `duplication`, `evlog-map-bots` |
| Turning a run's output into a verdict | `report.py` | `regression-proof-select`, `regression-proof-verdict`, `annotations`, `step-outcomes` |
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
`mutation_matrix.py` (the AST detector behind `mutation.sh matrix`).

The last two live in `lib/` rather than inline because they are large bodies
with their own tests and a second consumer: inlining the 1000-line bots scanner
would push `checks.mjs` past the 1200-line hard cap `checks.mjs file-sizes`
itself enforces, and `mutation_matrix.py` is imported directly by
`scripts/test/mutation-sweep.sh` and by `tests/test_mutation_matrix.py`. A
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

The three non-bash entrypoints keep the same shape in their own language:
`checks.mjs` and `release.mjs` dispatch on `process.argv[2]` into `cmd*`
functions and exit 2 with the usage on an unknown subcommand; `report.py`
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
