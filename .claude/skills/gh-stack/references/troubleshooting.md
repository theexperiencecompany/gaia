# Troubleshooting and recovery

## Contents

- [Rebase conflicts (exit 3)](#rebase-conflicts-exit-3)
- [After a squash merge](#after-a-squash-merge)
- [Local and remote stacks have diverged](#local-and-remote-stacks-have-diverged)
- [Restructuring a stack](#restructuring-a-stack)
- [Branch belongs to several stacks (exit 6)](#branch-belongs-to-several-stacks-exit-6)
- [Driving stacks from another tool or worktree](#driving-stacks-from-another-tool-or-worktree)
- [Stack file is locked (exit 8)](#stack-file-is-locked-exit-8)
- [An interrupted modify session (exit 10)](#an-interrupted-modify-session-exit-10)
- [Reading CI on a stacked PR](#reading-ci-on-a-stacked-pr)
- [Cancelled is not failed](#cancelled-is-not-failed)
- [A conflicting PR gets no runs at all](#a-conflicting-pr-gets-no-runs-at-all)
- [Batch fixes; one push per round](#batch-fixes-one-push-per-round)
- [Fix at the lowest layer that has the defect](#fix-at-the-lowest-layer-that-has-the-defect)
- [Never truncate the conflict list](#never-truncate-the-conflict-list)
- [Landing a new gate inside a stack](#landing-a-new-gate-inside-a-stack)

## Rebase conflicts (exit 3)

`rebase` and `sync` both exit 3 on conflict. `sync` restores every branch to its pre-rebase state
first, so a failed `sync` leaves nothing half-applied; a failed `rebase` stops mid-flight and waits.

```bash
gh stack rebase
# exit 3 — conflicted paths are listed on stderr
git add <resolved paths>
gh stack rebase --continue     # repeat if the next branch also conflicts
```

`gh stack rebase --abort` restores every branch in the stack, not just the current one.

Because `init` enables `git rerere`, a conflict you resolve once is replayed automatically the next
time the same conflict appears — which is common, since a change low in the stack is rebased through
every branch above it. Without `rerere`, repeated conflicts may need manual resolution on each
affected layer.

## After a squash merge

A squash merge replaces the branch's commits with one new commit, so the originals no longer exist
in the trunk's history and an ordinary rebase would try to replay them again.

`gh stack sync` detects this and rebases with `--onto` against the correct target, skipping the
merged branch:

```bash
gh stack sync
gh stack view --json    # merged branch reports "isMerged": true, "state": "MERGED"
```

No manual action is needed. If the replay conflicts, `sync` restores all branches and exits 3.
Run `gh stack rebase` to rerun the rebase, which will stop at the conflict and allow you to resolve
and then `--continue` until complete. Use `gh stack sync --prune` to also delete local branches for
merged PRs.

## Local and remote stacks have diverged

Divergence means the local stack and the stack on GitHub changed in different ways — for example
branches were added locally while a PR was added to the stack on github.com.

When non-interactive, `sync` prints both chains, changes nothing, and exits **0** with
`Sync aborted`. Success here does not mean the sync happened; check for that message, or re-run
`gh stack view --json` and compare.

Two resolution paths (a composition mismatch on `checkout` is the same situation: it exits **3**,
not 0, printing both chains — do not answer it with `rebase --continue`):

- **Keep the remote version.** Drop local tracking and pull the stack back down.

  ```bash
  gh stack unstack --local          # keeps the stack on GitHub
  gh stack checkout <stack-number>  # or a PR number
  ```

- **Keep the local version.** Remove the grouping on GitHub, then recreate it from local state.

  ```bash
  gh stack unstack                  # removes the grouping; PRs and branches survive
  gh stack submit --auto
  ```

Neither path deletes pull requests or branches.
Remote unstacking leaves PRs that are merging (auto-merge enabled) or are queued (in a merge queue)
stacked — and merged PRs pin a husk of the stack too (verified: the open PRs moved to a new stack
while the merged ones kept the old stack number alive). If needed, clear that state before retrying.

## Restructuring a stack

There is no non-interactive reorder, rename, or removal. `add` run from the wrong branch suggests
`gh stack modify`, but that is TUI-only. Tear the stack down and rebuild it instead:

```bash
gh stack unstack                       # removes local tracking and the GitHub grouping
# Drop branches and rewrite ancestry as needed. Keep branch names unchanged.
# Never `git branch -D` a layer and move on: the deleted name stays in stack tracking and
# shows up in `view` until the stack is rebuilt.
gh stack init --base main branch-1 branch-2 branch-3
gh stack submit --auto                 # re-link on GitHub
```

`init` adopts branches that already exist, so the rebuild reuses them rather than creating new ones.
When branch names are unchanged, existing PRs survive: once Git ancestry is correct, `submit` finds
each PR by its branch name, updates base branches, and re-links the stack on GitHub. Renaming a
branch breaks this lookup — `submit` matches open PRs by the new `headRefName`, misses the existing
PR, and creates a new one. To rename, either keep the old branch until the new PR is ready, or
update and verify the remote PR head afterwards (`gh stack view --json`, `gh pr view`), then
re-link.

Changing metadata does **not** change Git ancestry. Reorder commits first, then rebuild the stack.
For example, to change `main <- models <- migration <- ui` into
`main <- migration <- models <- ui`:

```bash
old_models=$(git rev-parse models)
old_migration=$(git rev-parse migration)
git rebase --onto main "$old_models" migration
git rebase --onto migration main models
git rebase --onto models "$old_migration" ui
gh stack unstack
gh stack init --base main migration models ui
gh stack submit --auto                 # re-link the rebuilt order on GitHub
```

The first rebase moves migration-only commits onto trunk, the second replays model commits above
them, and the third replays UI-only commits above models. Preserve the old boundary SHAs before
moving any branch. For a different reorder, identify each layer's range with
`git log <old-parent>..<branch>`, then replay the ranges bottom to top. Without the final
`submit`, the GitHub grouping and PR bases stay in the old order while local branches use the
new one.

## Branch belongs to several stacks (exit 6)

Commands exit 6 when the current branch cannot identify a single stack — typically because it is the
trunk of more than one stack. There is no flag to disambiguate.

```bash
gh stack checkout <a-branch-unique-to-the-intended-stack>
```

Then rerun. Commands that take an explicit stack number (`merge 7`, `unstack 7`) sidestep the
problem entirely, since they do not infer the stack from the current branch.

## Driving stacks from another tool or worktree

`gh stack link` creates and updates stacks purely through the API, with no local tracking state.
Use it when branches are managed by jj, Sapling, git-town, a separate worktree, or any workflow
where the local `.git/gh-stack` file would be wrong or absent.

```bash
gh stack link branch-a branch-b branch-c        # bottom to top
gh stack link --base develop --open a b c       # non-default trunk, ready for review
gh stack link 10 20 30                          # by PR number
gh stack link 7 feature-d                       # append to existing stack #7
```

Because `link` writes no local state, the local navigation commands (`up`, `down`, `top`, `bottom`)
will not work on the result. Use `gh stack checkout <stack-number>` if you later want local tracking.

## Stack file is locked (exit 8)

Another `gh stack` process holds the exclusive lock on `.git/gh-stack.lock`. The lock times out
after several seconds (about 12s observed once against a held lock, not 5), so wait and retry.
A persistent exit 8 means another process still holds the lock; identify and stop that process
before retrying. Note read-only commands such as `view` do not take the lock — only writes contend.

## An interrupted modify session (exit 10)

Bare `gh stack modify` is TUI-only and must never be invoked by an agent. The non-interactive
recovery flags are safe: `gh stack modify --abort` restores the pre-modify state and
`gh stack modify --continue` resumes after a resolved conflict. If a repository is left in
this state by someone else, restore it:

```bash
gh stack modify --abort
```

Related: `submit` also detects a pending modify state. Under a TTY it asks before deleting the
remote stack grouping and recreating it from local state. Without a TTY (`--auto` in CI or any
non-interactive run) it skips that confirmation and overwrites the remote grouping. Get explicit
operator approval for the remote grouping change before running `submit` with a pending modify
state.

## Reading CI on a stacked PR

`gh pr checks <n>` aggregates **every** run for the branch, superseded ones included. On a stack you
push each layer repeatedly, so it reports failures from heads that no longer exist and a PR reads red
while its current head is green. Resolve the head sha and ask for that sha's runs instead:

```bash
sha=$(gh pr view <n> --json headRefOid --jq .headRefOid)
gh api "repos/<owner>/<repo>/actions/runs?head_sha=$sha&per_page=30" \
  --jq '.workflow_runs[] | "\(.name)=\(.status)/\(.conclusion)"' | sort -u
```

That is the only authoritative read. Do this for every layer before concluding anything about the
stack's health — on a nine-PR stack the aggregated view produced hours of chasing failures that had
already been superseded.

## Cancelled is not failed

A contended runner kills jobs at `timeout-minutes`, and GitHub reports that as `cancelled`, not
`failure`. A superseded run reports the same thing. Neither is a code defect. Compare each job's span
against the lane's cap before diagnosing anything:

```bash
gh api repos/<owner>/<repo>/actions/runs/<run>/jobs --paginate \
  --jq '.jobs[] | select(.conclusion=="failure" or .conclusion=="cancelled")
        | "\(.name): \(.conclusion) \(.started_at)->\(.completed_at)"'
```

A span that equals the cap is a clock problem: re-run it when the box is quiet
(`gh run rerun <run> --failed` re-runs cancelled jobs too). A job that failed well inside the cap is
real — diagnose that one. Re-running on a loaded box just reproduces the timeout and costs another
full round.

## A conflicting PR gets no runs at all

When a PR's `mergeable` state is `CONFLICTING`, GitHub creates no `pull_request` runs — silently, with
no queued entry and no error. If CI appears to have stopped for one layer, check this before anything
else:

```bash
gh pr view <n> --json mergeable,mergeStateStatus
```

Re-merge the parent and resolve before pushing further. This is easy to miss mid-stack because the
layers above and below keep running normally.

## Batch fixes; one push per round

Every push to a lower layer propagates into every layer above it, and each layer starts its own CI
run. A nine-PR stack is roughly eighteen workflow runs per round, which on a self-hosted box can be
hours. So do not push a fix the moment you find it: collect every red across the whole stack, fix each
at its owning layer, then chain and push once from the bottom. Pushing mid-round also supersedes the
runs already in flight, which throws away work that was about to go green.

## Fix at the lowest layer that has the defect

"Fix at the bottom" is wrong as a reflex. Fix at the lowest layer where the defect actually manifests.
A gate that lands at layer 1 may only be violated by code introduced at layer 6 — fixing it at layer 1
touches a branch that does not have the problem and forces every layer in between through another CI
round for nothing.

## Never truncate the conflict list

`git diff --name-only --diff-filter=U` piped through `head`/`tail` silently hides conflicted files.
Resolving the visible subset leaves conflict markers in the tree, and the next command fails somewhere
unrelated — a syntax error in a file you never opened. Always read the list in full, and confirm it is
empty before committing:

```bash
git diff --name-only --diff-filter=U            # read all of it
grep -rl '^<<<<<<< ' -- . | head                # belt and braces
```

## Landing a new gate inside a stack

A lint, contract or coverage gate added at a low layer is enforced on every layer above it, against
code those layers already contain. Expect the top of the stack to surface real violations the bottom
never had, and budget a fix round for them. That is the gate working, not a regression — but if you
land the gate and the stack in the same push, you will discover the debt one layer at a time, each
discovery costing a full CI round.
