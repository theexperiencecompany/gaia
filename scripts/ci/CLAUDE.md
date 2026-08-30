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
| Where and how hard a job runs | `runner.sh` | `select`, `watchdog`, `cancel-superseded`, `prime-archive`, `parallel`, `dep-marker` |
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
convention), `service-images.sh` (the digest-pinned test-service images),
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
