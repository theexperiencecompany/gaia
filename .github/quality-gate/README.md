# Quality gate

The `quality-gate` job in `.github/workflows/code-quality.yml` is one of the
two branch-protection gate jobs on `master` (the other is `main.yml`'s
`quality-gate`). It aggregates every code-quality lane and **fails the merge
if any lane is red**.

## Enforcement model

Every lane is enforced: a lane whose result is neither `success` nor `skipped`
(where `skipped` means the `changes` job proved the lane's language was
untouched) fails the gate. There is no informational tier.

This replaced the old marker-file ratchet (`.github/quality-gate/enforced/<lane>`)
that let lanes start informational and be ratcheted up by resolution PRs. The
rollout is complete — every lane is enforced — and the two sources of truth
(marker files vs the `LANES` array) had drifted. A flat "all lanes block" is
the end state: one list, no directory scan, no sync to maintain.

## Adding a new lane

1. Add the job to `.github/workflows/code-quality.yml`.
2. Add its result to the `needs:` list and the `RESULT` map in the `quality-gate`
   job.
3. Add its name to the `LANES` array in the verdict step.

The gate enforces it from the first run — there is no informational grace
period. If a rollout period is ever wanted again, that is a deliberate decision
to reintroduce, not a default.

## Lane names

`biome`, `deps`, `circular`, `file-size`, `types-location`, `components-per-file`,
`duplicates`, `package-hygiene`, `type-check`, `python-static`,
`python-mypy`, `observability`, `wide-event-conformance`, `dead-code`, `alert-rules`,
`suppression-hygiene`, `gitleaks`, `semgrep`, `test-mutation-plan`, `test-mutation`
(twenty — keep this list, the `LANES` array and the `needs:` list in step).
