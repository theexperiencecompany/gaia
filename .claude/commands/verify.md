Run full quality gates before marking work done. Stop and report any failures — do not mark work complete if any step fails.

```bash
# Lint and type-check all affected projects
nx run-many -t lint type-check

# Python tests
cd apps/api && uv run pytest
```

If lint fails: fix the issues (or report them if they're pre-existing).
If type-check fails: fix type errors before proceeding.
If tests fail: investigate and fix before marking done.

After all gates pass, run the session completion sequence:

```bash
git pull --rebase
git push
git status  # must show "up to date with origin"
```

> **Note on `bd`:** `bd` is a project-internal CLI for task tracking and dolt database sync.
> Only invoke `bd dolt push` when the user explicitly asks for it — never include it automatically.
