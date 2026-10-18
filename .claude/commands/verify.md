Run the quality gates your change can break before marking work done. Stop and report any failure — do not mark work complete if any step fails.

Run the gates CI runs, per what changed (CLAUDE.md, "Verify with the CI command"):

| Changed | Run |
|---|---|
| any `.py` | `mise run lint:py` and `mise ci:local --only python-mypy` |
| `apps/api/app/**` | the above, plus `mise ci:local --only custom-lints,lint-imports` |
| any `.ts`/`.tsx` | `mise run lint` and `mise run type-check` |
| `apps/api` routes or models | `mise api:types` |
| new/changed dependency | `mise ci:local --only dead-code,package-hygiene` |

Tests: run only the files that cover the change, one command, no xdist — `mise test:one <test file> [more files]`. Never run the full suite locally; that is CI's job.

If a gate fails: fix the cause (or report it if it is pre-existing on master). If a test fails: investigate and fix before marking done.

After all gates pass, run the session completion sequence:

```bash
git fetch origin
git merge origin/master  # plain merge, never rebase
git push
git status  # must show "up to date with origin"
```
