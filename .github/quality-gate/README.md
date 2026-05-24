# Quality gate ratchet

The `quality-gate` job in `.github/workflows/code-quality.yml` is the single
required status check on `develop`. It runs all 15 code-quality lanes but only
**fails** when an *enforced* lane is red. Every other lane is reported and
non-blocking, so develop stays green while violations are fixed lane by lane.

## How a lane becomes enforced

A lane is enforced if and only if a marker file exists at:

```
.github/quality-gate/enforced/<lane>
```

The verdict step lists this directory to build the enforced set. To enforce a
lane, add its marker file. To relax one, delete it.

## Why marker files instead of a list

Each resolution PR enforces exactly one lane. If enforcement were a shared list
in one file, every PR would edit the same lines and they would all merge-conflict
with each other. Separate marker files live at distinct paths, so any number of
lane PRs can be open at once and merge in any order without conflicts.

## Per-lane resolution PR recipe

1. Branch off `develop`.
2. Fix that lane's violations (verify locally with its `pnpm run quality:*`
   script or the command in the workflow step).
3. `touch .github/quality-gate/enforced/<lane>` — do **not** edit the workflow.
4. Push, open PR. The gate enforces the lane once the PR merges.

## Lane names

`biome`, `deps`, `circular`, `file-size`, `types-location`, `components-per-file`,
`duplicates`, `type-coverage`, `package-hygiene`, `type-check`, `python-ruff`,
`python-mypy`, `python-interrogate`, `python-xenon`, `python-security`.
