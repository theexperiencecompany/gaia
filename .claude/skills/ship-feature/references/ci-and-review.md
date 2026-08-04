# CI Gates, Local Repro, and the Drive-to-Green Loop

## What runs on a PR to develop

- **Quality Checks** (`main.yml`) — affected-project build (TS), full pytest
  suite vs live services (`uv run --frozen pytest -n auto -m 'not composio'`
  from `apps/api`), vitest for affected TS projects, and harness-tool tests
  (`tools/lints` + `tools/llm-stub`, always on). Required check:
  **`quality-gate`** (skipped jobs pass).
- **Code Quality** (`code-quality.yml`) — 16 lanes, all enforced via marker
  files in `.github/quality-gate/enforced/`. Required check:
  **`Quality gate (required)`** — here a skipped enforced lane **fails**,
  unlike the other gate.
- **Validate PR Title** — Conventional Commit type from: `feat fix docs style
  refactor test chore ci build revert perf release deps infra security env
  i18n ux config assets meta`.
- **Desktop PR Build** — only when `apps/desktop/**` or `libs/shared/ts/**`
  changed.

Non-blocking noise — never remediate: `changelog-sync` (self-heals via its
own PR and still exits 1; excluded from the gate), `trivy-scan`, `pip-audit`.

## Run the gates locally BEFORE pushing

Typical web+api feature sweep:

```bash
pnpm exec nx run-many -t lint type-check --projects=web,api --parallel=3
pnpm exec nx build web
(cd apps/api && uv run pytest tests/unit --tb=short -q)   # full suite needs live infra

pnpm run quality:circular
pnpm run quality:size
pnpm run quality:components        # tsx changed
pnpm run quality:types-location    # ts/tsx changed
pnpm run quality:type-coverage
pnpm run quality:dead:strict
pnpm run quality:py:interrogate    # py changed
pnpm run quality:py:xenon          # py changed
uvx bandit -c pyproject.toml -r apps/api/app libs/shared/py --severity-level low --confidence-level low   # py changed
```

Auto-fixers — reach for these first: `nx run <proj>:lint:fix` (biome/ruff),
`pnpm run quality:deps:fix` (syncpack/manypkg), `uvx ruff format <files>`.

No auto-fix — these are design feedback, fix the code: file-size (400-line
target), components-per-file (max 2), types-location (> 3 exported types →
`*.types.ts`), type-coverage, xenon complexity, interrogate docstrings, jscpd
duplication, dead-code.

**The diff-scoping trap:** most Code Quality lanes run only on files changed
vs the PR base (`scripts/ci/changed-files.sh`). Locally that variable is
unset, so the same command runs repo-wide and can fail on files you never
touched. Reproduce a lane exactly as CI sees it:

```bash
git fetch origin develop
GITHUB_BASE_REF=develop scripts/ci/changed-files.sh ts tsx   # prints CI's file list
```

Pre-existing repo-wide failures outside your diff are not yours to fix in
this PR — confirm CI scopes them out rather than "fixing" half the codebase.

Also: `nx affected` defaults to base `master` locally (`nx.json`); always
pass `--base=origin/develop`.

## The drive-to-green loop

1. `subscribe_pr_activity` right after opening the PR. Where `send_later`
   exists, arm a ~1h fallback self check-in in case events don't arrive;
   re-arm silently until the PR is done.
2. **CI failure** → pull the job log, reproduce locally with the matching
   command above, fix at the root, re-run the local gate, push. Never push a
   blind retry. Every failure event ends in a pushed fix or a PR comment
   explaining precisely why not — no third option.
3. **Merge conflict / base moved** → `git fetch origin && git merge
   origin/develop` (plain merge — rebase is banned in this repo), resolve,
   re-run affected gates, push.
4. Green + mergeable + all threads answered → one concise status comment
   (what shipped, what was verified, evidence links) and stop. **Never merge.**

## CodeRabbit

CodeRabbit auto-reviews PRs with default settings (the checked-in config at
`config/.coderabbit.yaml` is not at repo root, so it is inert). Its comments
arrive as PR activity events. Apply `receiving-code-review` discipline:

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
