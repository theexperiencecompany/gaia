# CI Gates, Local Repro, and the Drive-to-Green Loop

## What runs on a PR to master

Source of truth: `.github/workflows/` — read the workflow when you need a
lane's exact command; don't trust memory or this file for specifics.

- **Quality Checks** (`main.yml`) — build + test jobs over affected projects
  (Python tests run the full suite against live services). Required check:
  **`quality-gate`**; skipped jobs pass it.
- **Code Quality** (`code-quality.yml`) — many independent lint/analysis
  lanes, every one flat-enforced via the `LANES` array in the `quality-gate`
  verdict job (the old `.github/quality-gate/enforced/` marker-file ratchet
  was removed — see `.github/quality-gate/README.md`). Required check:
  **`Quality gate (required)`**. In both gates a skipped lane passes (skipped
  = your diff didn't touch that lane's language).
- **PR title check** (`pr-naming-conventions.yml`) — Conventional Commit
  title; the allowed type list lives in that workflow.
- **Desktop PR Build** — only when its path filters match (desktop app +
  shared TS).

Jobs that are red by design or advisory (e.g. changelog-sync, security
scanners marked `continue-on-error`) are excluded from the gates — check the
gate job's `needs` list before remediating anything, and never "fix" a check
the gate ignores.

## Run the gates locally BEFORE pushing

Mirror what CI will run, scoped to what you touched:

- Per-project basics: `pnpm exec nx run-many -t lint type-check build
  --projects=<touched>` and the project's test target. `nx run
  <proj>:lint:fix` first where a fixer exists.
- Code-quality lanes: each lane maps to a root `quality:*` script in
  `package.json` — run the ones for your languages (`pnpm run` with no args
  lists them). Lanes without a fixer (file size, components-per-file, type
  placement, complexity, docstring coverage, duplication, dead code) are
  design feedback: restructure the code, never suppress or split cosmetically.
- `mise tasks` lists the aggregate runners if you want one command per area.

**The diff-scoping trap:** many Code Quality lanes run only on files changed
vs the PR base (see `scripts/ci/changed-files.sh`). Locally the base-ref env
var is unset, so the same command runs repo-wide and can fail on files you
never touched. Reproduce a lane exactly as CI sees it by exporting the
base-ref variable the script reads (with `master` fetched), or by limiting
the tool to your changed files. Pre-existing repo-wide failures outside your
diff are not yours to fix in this PR.

## The drive-to-green loop

1. `subscribe_pr_activity` right after opening the PR. Where `send_later`
   exists, arm a ~1h fallback self-check-in in case events don't arrive;
   re-arm silently until the PR is done.
2. **CI failure** → pull the job log, find the lane's command in the
   workflow, reproduce locally, fix at the root, re-run, push. Never push a
   blind retry. Every failure event ends in a pushed fix or a PR comment
   explaining precisely why not — no third option.
3. **Merge conflict / base moved** → `git fetch origin && git merge
   origin/master` (plain merge — rebase is banned in this repo), resolve,
   re-run affected gates, push.
4. Green + mergeable + all threads answered → one concise status comment
   (what shipped, what was verified, evidence links) and stop. **Never merge.**

## CodeRabbit

CodeRabbit auto-reviews PRs; its comments arrive as PR activity events. Apply
`receiving-code-review` discipline:

- **Verify before implementing.** Read the referenced code and confirm the
  claim — CodeRabbit is confidently wrong at a meaningful rate, and blindly
  applied suggestions introduce bugs and style drift.
- Valid → fix at the root (repo standards beat its suggested patch when they
  differ), push, reply briefly, resolve the thread.
- Invalid → reply with the specific refuting evidence, resolve. Reasoned
  pushback is a resolution; silence is not.
- Conflicts with repo conventions (CLAUDE.md, DESIGN.md, biome/ruff) → the
  repo wins; say so in one line.
- After pushing a batch of fixes, comment `@coderabbitai review` to trigger a
  re-review, and confirm no thread remains unanswered.
- If no CodeRabbit review has arrived by the time CI is green plus one
  check-in cycle, it may not be installed on the repo — note its absence in
  the final status comment and finish without it.
