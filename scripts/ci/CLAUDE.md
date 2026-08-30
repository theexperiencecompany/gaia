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
| Is the suite strong enough | `mutation.sh` | `plan`, `shard`, `module`, `local` |
| Which tests a diff can reach | `test_impact.py` | `record`, `select`, `fetch` |
| What this PR changed | `changes.sh` | `files`, `docker-inputs` |
| Standing dependency + pin gates | `audit.sh` | `pnpm`, `playwright-pin`, `alert-rule-tools`, `evlog` |
| Shipping to production | `deploy.sh` | `plan`, `stack`, `verify`, `retag`, `notify` |

`lib/` holds what several of them share: `log.sh` (the log convention),
`service-images.sh` (the digest-pinned test-service images), `image-repos.sh`
(the GHCR repo per image group).

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
- The log convention, via `lib/log.sh`: raw tool output inside
  `ci_group`/`ci_endgroup`, and the LAST line a one-line verdict (`ci_ok`).
  Test steps are the exception — a traceback must be readable uncollapsed.

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
