---
name: verify
description: Run full quality gates (lint, type-check, tests) before marking work done. Use before every commit or when claiming a task is complete.
---

Run these commands in order. Stop and report any failures — do not mark work complete if any step fails.

```bash
# Lint and type-check all affected projects
nx run-many -t lint type-check

# Python tests
cd apps/api && uv run pytest
```

If lint fails: fix the issues (or report them if they're pre-existing).
If type-check fails: fix type errors before proceeding.
If tests fail: investigate and fix before marking done.

After all gates pass, proceed with the session completion protocol from AGENTS.md:
1. `git pull --rebase`
2. `bd dolt push`
3. `git push`
4. Confirm `git status` shows "up to date with origin"
