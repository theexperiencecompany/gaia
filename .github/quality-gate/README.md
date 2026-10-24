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

Inside a grouped job (lint-node, lint-python, lint-mixed, scan, python-audit,
ts-build-test) every check is its own `continue-on-error` step. The job's
`verdict.py step-outcomes` step fails it if any check failed, and
`verdict.py post-statuses` posts each check as its own `ci / <check>` commit
status. A check skipped because its last pass on the PR still holds
(`verdict.py reuse-plan`) counts as a pass.

## Adding a check

1. Add it as a `continue-on-error` step with an `id` to the grouped job that
   already has its toolchain, gated on the `detect` output that scopes it.
2. Add `<id>=${{ steps.<id>.outcome }}` to that job's `CHECKS` list (one YAML
   anchor, read by both the status step and the verdict step).
3. To make it reusable on PR pushes, give its `scripts/dev/verify-lanes.json`
   row `"ci_check": "<id>"` and gate the step on
   `!contains(fromJSON(needs.detect.outputs.reused_checks || '[]'), '<id>')`.

A new JOB goes in the gate's `needs:` list and its `EXPECT` entry, and uploads
its verdict through `./.github/actions/upload-verdict`;
`scripts/ci/tests/test_workflow_verdicts.py` fails if any of those drift.

The gate enforces a check from its first run. There is no informational grace
period. If a rollout period is ever wanted again, that is a deliberate decision
to reintroduce, not a default.
