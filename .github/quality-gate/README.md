# Quality gate

The `quality-gate` job in `.github/workflows/ci.yml` is the branch-protection
gate on `master` and the merge queue's required check. It reads every lane's
verdict (`scripts/ci/verdict.py consolidate`) and **fails the merge if any lane
is red**.

## Enforcement model

Every lane is enforced: a lane whose result is neither `success` nor `skipped`
fails the gate. `skipped` means `detect` proved the lane had nothing to check
(its language untouched, or the lane belongs to the full tier and this is a PR
push). There is no informational tier. A lane that ran and reported nothing is
`NO VERDICT` and fails too.

Inside a grouped job (lint-node, lint-python, lint-mixed, repo-policy, scan,
python-audit, ts-build-test) every check is an nx task: `runner.py run-job`
runs the job's affected ones and `verdict.py post-statuses` posts each as its
own `ci / <area> / <check>` commit status and fails the job if any failed. A
check skipped because its last pass on the PR still holds
(`verdict.py reuse-plan`) counts as a pass.

## Adding a check

1. Add it as a target of `tools/ci/project.json` (or of the code project it
   checks), with the `inputs` it reads and
   `"metadata": {"ci": {"job": "<grouped job>", "check": "<id>", "area": "<area>"}}`.
   That is the whole change: detect selects it, run-job runs it, post-statuses
   posts it, reuse-plan may reuse it (`"reuse": false` opts out) and
   `mise ci:local` runs it.
2. A check that only runs on some events names them (`"events": [...]`, and
   `"branch"` for master-only). A check an action runs takes `"runner": "action"`
   and a step in its job with `id: <id>`, passed to post-statuses as
   `--step <id>=${{ steps.<id>.outcome }}`.

A new JOB goes in the gate's `needs:` list and its `EXPECT` entry, and uploads
its verdict through `./.github/actions/upload-verdict`;
`scripts/ci/tests/test_workflow_verdicts.py` fails if any of those drift.

The gate enforces a check from its first run. There is no informational grace
period. If a rollout period is ever wanted again, that is a deliberate decision
to reintroduce, not a default.
